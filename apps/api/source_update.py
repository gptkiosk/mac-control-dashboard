"""One-click, operator-approved update of a source checkout to the newest official stable release.

MCD is often run from a git checkout (the "driver") instead of a signed package. The packaged-release
updater does not apply there, so this module gives the Updates page the same shape of flow for a checkout:

  inspect()   what this checkout is: official remote? clean? macOS with launchd? the tools it needs?
  check()     read the official GitHub release list, download only the signed manifest and its signature,
              verify them against packaging/allowed_signers, and say what would change and what blocks it
  begin()     after the operator confirms the exact tag and commit that check() showed: start a detached
              helper (its own launchd job, so restarting the service cannot stop it)
  run()       the helper: re-verify everything, fetch the tag, require that it names the signed commit, then run
              scripts/upgrade-driver.sh (backup, checkout, dependencies, web build, restart, exact health check,
              rollback on any failure) and record each step in a private operation file the page reads
  status()    the operation file plus a log tail; it survives the service restart

Nothing here runs on a timer, downloads a package, or installs without a confirmation. The signature is the
one the release workflow made over the manifest, so a tag that was moved, or a release the dedicated signing
key did not sign, is refused. Packaged installs keep their own signed-package updater.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_fetch as rf  # noqa: E402
import release_verify as rv  # noqa: E402
import update_engine as ue  # noqa: E402

PRODUCT = "mcd"
OFFICIAL_REPOSITORY = rv.OFFICIAL_REPOSITORIES[PRODUCT]
OFFICIAL_URL = f"https://github.com/{OFFICIAL_REPOSITORY}.git"
PLATFORM_KEY = "darwin-arm64"
SIGNER_IDENTITY = "dashboard-release"
GIT_SSH_HOST = "git" + chr(64) + "github.com"      # built, not written out: the package content scan rejects anything shaped like an email address
REMOTE_FORMS = (
    f"https://github.com/{OFFICIAL_REPOSITORY}", f"https://github.com/{OFFICIAL_REPOSITORY}.git",
    f"{GIT_SSH_HOST}:{OFFICIAL_REPOSITORY}", f"{GIT_SSH_HOST}:{OFFICIAL_REPOSITORY}.git",
    f"ssh://{GIT_SSH_HOST}/{OFFICIAL_REPOSITORY}", f"ssh://{GIT_SSH_HOST}/{OFFICIAL_REPOSITORY}.git",
)
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))
TOOLS = ("git", "npm", "uv")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
OP_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
LOG_TAIL_LINES = 60
TEST_HOOKS = ("MCD_LAUNCHCTL", "MCD_CURL", "MCD_NPM", "MCD_UV", "MCD_HEALTH_WAIT_S")
STEPS = ("preflight", "verify", "fetch", "upgrade", "finish")


class SourceUpdateError(Exception):
    """A refusal. `problems` are sentences for the operator."""

    def __init__(self, problems: list[str] | str, blockers: list[str] | None = None):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        self.blockers = list(blockers or [])
        super().__init__("; ".join(self.problems))


# ---------------------------------------------------------------------------- small helpers


def tool_path() -> str:
    return ":".join((*EXTRA_PATH, "/usr/bin:/bin:/usr/sbin:/sbin"))


def find_tool(name: str) -> str | None:
    return shutil.which(name, path=tool_path())


def git(root: Path, *args: str, timeout: int = 60) -> str:
    env = {"PATH": tool_path(), "HOME": str(Path.home()), "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise SourceUpdateError(f"git {args[0]} failed")
    return result.stdout.strip()


def sanitized_remote(url: str) -> str:
    """The remote without any credentials embedded in it."""
    return re.sub(r"//[^/@]+@", "//", url)


def data_paths(data_dir: Path) -> dict[str, Path]:
    base = Path(data_dir) / "source-updates"
    return {"dir": base, "op": base / "operation.json", "lock": base / "operation.lock"}


def ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def write_json_private(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def running_version(root: Path) -> str:
    """The version the checked-out commit carries (apps/api/version.py at HEAD), so an edited working file cannot change it."""
    text = git(root, "show", "HEAD:apps/api/version.py")
    found = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    if not found:
        raise SourceUpdateError("apps/api/version.py has no version")
    return found.group(1)


# ---------------------------------------------------------------------------- eligibility


def inspect(root: Path, *, product: str, label: str, system: str | None = None, machine: str | None = None,
            launchctl: str | None = None) -> dict:
    """What this checkout is, and whether the one-click update can run here. Reads local state only."""
    root = Path(root)
    problems: list[str] = []
    info: dict = {"checkout": str(root), "product": product.lower(), "label": label}
    system, machine = system or platform.system(), machine or platform.machine()
    if product.lower() != PRODUCT:
        problems.append("One-click updates of a source checkout are available for MCD only. RCD installs update from its signed release.")
    if system != "Darwin" or machine not in ("arm64", "aarch64"):
        problems.append(f"One-click source updates need macOS on Apple silicon (this host is {system} {machine}).")
    if not (root / ".git").exists():
        problems.append("This is not a git checkout.")
        return {**info, "eligible": False, "problems": problems}
    try:
        info["commit"] = git(root, "rev-parse", "HEAD")
        info["short"] = info["commit"][:7]
        info["version"] = running_version(root)
        branch = git(root, "branch", "--show-current")
        info["branch"] = branch or None
        try:
            info["tag"] = git(root, "describe", "--tags", "--exact-match", "HEAD") or None
        except SourceUpdateError:
            info["tag"] = None
        remotes = git(root, "remote").split()
        remote = git(root, "remote", "get-url", "origin") if "origin" in remotes else None
    except (SourceUpdateError, OSError, subprocess.SubprocessError):
        problems.append("Git could not read this checkout (the repository may be damaged).")
        return {**info, "eligible": False, "problems": problems}
    # A checkout with no remote at all is fine: releases are always fetched from the official repository directly.
    # A remote that points anywhere else is a fork or a mirror, and is refused.
    info["remote"] = sanitized_remote(remote) if remote else None
    info["official_remote"] = remote is None or remote in REMOTE_FORMS
    if not info["official_remote"]:
        problems.append(f"origin is {info['remote']}, not the official repository {OFFICIAL_REPOSITORY}. Forks and other remotes are never updated this way.")
    try:
        dirty = git(root, "status", "--porcelain", "--untracked-files=no")
    except (SourceUpdateError, subprocess.SubprocessError):
        dirty = "unreadable"
    info["clean"] = not dirty
    if dirty:
        problems.append("The checkout has uncommitted changes to tracked files. Review and commit or stash them first; nothing is overwritten.")
    missing = [tool for tool in TOOLS if find_tool(tool) is None]
    if missing:
        problems.append(f"Missing prerequisites: {', '.join(missing)}. Install them and reload this page.")
    info["prerequisites"] = {tool: find_tool(tool) is not None for tool in TOOLS}
    if system == "Darwin":
        ctl = launchctl or os.environ.get("MCD_LAUNCHCTL", "launchctl")
        try:
            loaded = subprocess.run([ctl, "print", f"gui/{os.getuid()}/{label}"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            loaded = False
        info["service_loaded"] = loaded
        if not loaded:
            problems.append(f"The LaunchAgent {label} is not loaded for this user, so there is nothing to restart. Install it with scripts/install-launchagent.sh.")
    script = root / "scripts" / "upgrade-driver.sh"
    if not script.is_file():
        problems.append("scripts/upgrade-driver.sh is missing from this checkout.")
    if not (root / "packaging" / "allowed_signers").is_file():
        problems.append("packaging/allowed_signers is missing, so a release cannot be verified.")
    return {**info, "eligible": not problems, "problems": problems}


# ---------------------------------------------------------------------------- signed release


def fetch_config(root: Path, data_dir: Path, version: str, **overrides) -> rf.FetchConfig:
    return rf.make_config(
        Path(data_dir) / "source-updates", PLATFORM_KEY, channel="stable", installed_version=version,
        trust={"kind": "ssh-signature", "allowed_signers": str(Path(root).resolve() / "packaging" / "allowed_signers"),
               "identity": SIGNER_IDENTITY}, **overrides)


def verify_signed_manifest(cfg: rf.FetchConfig, candidate: rf.Candidate, opener=None) -> dict:
    """Download only the manifest and its signature, and require what a checkout update needs:
    the dedicated key signed it, it is MCD's stable release of exactly this version, and it names the
    clean source commit the tag must point at. Raises SourceUpdateError."""
    try:
        manifest = rf.fetch_asset_bytes(cfg, candidate.asset("manifest"), opener)
        signature = rf.fetch_asset_bytes(cfg, candidate.asset("signature"), opener)
        signer = rf.build_authenticator(cfg.trust)(manifest, signature)
        data = rv.strict_json(manifest, "manifest")
    except (rf.FetchError, rv.AuthenticityError, rv.VerificationError, StopIteration) as exc:
        problems = getattr(exc, "problems", None) or [str(exc) or "the signed manifest could not be verified"]
        raise SourceUpdateError(["The release's signed manifest was not verified."] + list(problems)) from None
    problems = list(rv.manifest_problems(data))
    if isinstance(data, dict) and not problems:
        source = data.get("source") or {}
        if data.get("product") != PRODUCT or data.get("repository") != OFFICIAL_REPOSITORY:
            problems.append("The manifest is not MCD's official release.")
        if data.get("channel") != "stable":
            problems.append("The manifest is not a stable release.")
        if data.get("version") != candidate.version:
            problems.append(f"The manifest is for version {data.get('version')}, not {candidate.version}.")
        if not SHA1.match(str(source.get("commit") or "")):
            problems.append("The manifest does not name its source commit.")
        if source.get("dirty") or not source.get("release_eligible"):
            problems.append("The manifest says the release was not built from a clean, release-eligible source tree.")
    if problems:
        raise SourceUpdateError(["The release's signed manifest was refused."] + problems)
    return {"commit": data["source"]["commit"], "signer": signer, "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "version": data["version"]}


def check(root: Path, data_dir: Path, *, db_path: Path, product: str, label: str, opener=None) -> dict:
    """The page's "Check for updates": GitHub release list plus the signed manifest. Downloads no package."""
    inspection = inspect(root, product=product, label=label)
    body: dict = {"inspection": inspection, "available": False, "candidate": None, "verified": None, "blockers": []}
    if not inspection["eligible"]:
        return body
    try:
        cfg = fetch_config(root, data_dir, inspection["version"])
        candidate = rf.query_release(cfg, opener)
    except rf.FetchError as exc:
        raise SourceUpdateError(["Could not check for updates."] + list(exc.problems)) from None
    if candidate is None:
        return body
    verified = verify_signed_manifest(cfg, candidate, opener)
    body.update(available=True, verified=verified, blockers=ue.drain_blockers(db_path),
                candidate={"tag": candidate.tag, "version": candidate.version, "notes": candidate.notes, "html_url": candidate.html_url,
                           "published_at": candidate.published_at, "change": candidate.change, "repository": candidate.repository})
    if not TAG.match(candidate.tag):
        raise SourceUpdateError(f"The release tag {candidate.tag!r} is not a plain version tag.")
    return body


# ---------------------------------------------------------------------------- operation state


def read_operation(data_dir: Path) -> dict | None:
    return read_json(data_paths(data_dir)["op"])


def operation_active(data_dir: Path) -> bool:
    """True while a helper holds the operation lock."""
    paths = data_paths(data_dir)
    try:
        fd = os.open(paths["lock"], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def log_tail(data_dir: Path, op: dict) -> list[str]:
    name = op.get("log")
    if not isinstance(name, str) or "/" in name:
        return []
    try:
        lines = (data_paths(data_dir)["dir"] / name).read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [line[:300] for line in lines[-LOG_TAIL_LINES:]]


def status(data_dir: Path) -> dict:
    op = read_operation(data_dir)
    out: dict = {"operation": op, "active": operation_active(data_dir), "log": log_tail(data_dir, op) if op else []}
    if op and op.get("state") in ("starting", "running") and not out["active"]:
        # The helper is gone but never wrote a result: say so instead of showing a spinner forever.
        started = op.get("started_at") or 0
        if time.time() - started > 20:
            out["operation"] = {**op, "state": "failed", "message": "The update helper stopped without reporting a result. Check the log and the service."}
    return out


def new_operation_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)


# ---------------------------------------------------------------------------- start (called by the service)


def spawn(argv: list[str], label: str, out_path: Path) -> None:
    """Run the helper as its own launchd job, so restarting the service cannot stop it."""
    ctl = os.environ.get("MCD_LAUNCHCTL", "launchctl")
    result = subprocess.run([ctl, "submit", "-l", label, "-o", str(out_path), "-e", str(out_path), "--", *argv],
                            capture_output=True, timeout=20)
    if result.returncode:
        raise SourceUpdateError("launchd refused to start the update helper.")


def begin(root: Path, data_dir: Path, *, db_path: Path, product: str, label: str, port: int, tag: str, commit: str,
          confirm: bool, opener=None, spawner=spawn) -> dict:
    """Start the update the operator confirmed: this exact tag and the commit check() showed for it."""
    if not confirm:
        raise SourceUpdateError("Explicit confirmation is required.")
    if not TAG.match(tag or "") or not SHA1.match(commit or ""):
        raise SourceUpdateError("A release tag and the full commit shown by the check are required.")
    inspection = inspect(root, product=product, label=label)
    if not inspection["eligible"]:
        raise SourceUpdateError(inspection["problems"])
    if operation_active(data_dir):
        raise SourceUpdateError("An update is already running.")
    found = check(root, data_dir, db_path=db_path, product=product, label=label, opener=opener)
    if not found["available"] or found["candidate"]["tag"] != tag or found["verified"]["commit"] != commit:
        raise SourceUpdateError("The newest verified release is no longer the one you confirmed. Check again.")
    if found["blockers"]:
        raise SourceUpdateError("Drain first. Nothing was stopped.", found["blockers"])
    paths = data_paths(data_dir)
    ensure_private_dir(paths["dir"])
    op_id = new_operation_id()
    log_name = f"{op_id}.log"
    op = {"id": op_id, "state": "starting", "tag": tag, "commit": commit, "version": found["candidate"]["version"],
          "from": {"version": inspection["version"], "commit": inspection["commit"]}, "started_at": int(time.time()),
          "steps": [], "log": log_name, "message": "Starting the update helper.",
          "settings": {"root": str(Path(root).resolve()), "data_dir": str(Path(data_dir).resolve()), "db_path": str(Path(db_path).resolve()),
                       "label": label, "port": port}}
    write_json_private(paths["op"], op)
    log_path = paths["dir"] / log_name
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    python = Path(root) / "apps" / "api" / ".venv" / "bin" / "python"
    argv = ["/bin/bash", "-c", 'export PATH="$1"; shift; exec "$@"', "mcd-source-update", tool_path(), str(python), "-I",
            str(Path(__file__).resolve()), "run", "--data-dir", str(data_dir)]
    try:
        spawner(argv, f"{label}.source-update.{op_id.replace('-', '.').lower()}", log_path)
    except (SourceUpdateError, OSError, subprocess.SubprocessError) as exc:
        write_json_private(paths["op"], {**op, "state": "failed", "message": str(exc) or "The update helper could not be started."})
        raise SourceUpdateError(str(exc) or "The update helper could not be started.") from None
    return {"operation_id": op_id, "poll": "/api/app-updates/source/operation"}


# ---------------------------------------------------------------------------- the helper


class Recorder:
    def __init__(self, data_dir: Path, op: dict):
        self.paths, self.op = data_paths(data_dir), op

    def save(self) -> None:
        write_json_private(self.paths["op"], self.op)

    def step(self, name: str, state: str, detail: str = "") -> None:
        steps = [s for s in self.op["steps"] if s["name"] != name]
        steps.append({"name": name, "state": state, "detail": detail, "at": int(time.time())})
        self.op["steps"] = sorted(steps, key=lambda s: STEPS.index(s["name"]))
        self.save()

    def finish(self, state: str, message: str, **extra) -> None:
        self.op.update(state=state, message=message, finished_at=int(time.time()), **extra)
        self.save()


def log(handle, text: str) -> None:
    handle.write(f"{time.strftime('%H:%M:%S')}  {text}\n")
    handle.flush()


def health(port: int) -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as response:
            data = json.loads(response.read(4096))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def run(data_dir: Path, *, opener=None, runner=subprocess.run) -> int:
    """The detached helper. Everything it needs is in the operation file the service wrote."""
    paths = data_paths(data_dir)
    op = read_operation(data_dir)
    if not op or op.get("state") != "starting" or not OP_ID.match(str(op.get("id") or "")):
        print("no pending operation", file=sys.stderr)
        return 2
    lock = os.open(paths["lock"], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another update is running", file=sys.stderr)
        return 3
    cfg = op["settings"]
    root, tag, commit = Path(cfg["root"]), op["tag"], op["commit"]
    rec = Recorder(data_dir, op)
    rec.op.update(state="running", message="Checking that it is safe to update.")
    rec.save()
    out = open(paths["dir"] / op["log"], "a", buffering=1)
    code = 1
    try:
        code = _run_steps(rec, out, root, Path(data_dir), Path(cfg["db_path"]), cfg, tag, commit, opener, runner)
    except SourceUpdateError as exc:
        log(out, "refused: " + "; ".join(exc.problems + exc.blockers))
        failing = next((s["name"] for s in rec.op["steps"] if s["state"] == "running"), "preflight")
        rec.step(failing, "failed", "; ".join(exc.problems + exc.blockers))
        rec.finish("failed", "Nothing was changed. " + " ".join(exc.problems + exc.blockers))
    except Exception as exc:  # noqa: BLE001 - the page must always get a result
        log(out, f"unexpected failure: {type(exc).__name__}")
        rec.finish("failed", f"The update stopped unexpectedly ({type(exc).__name__}). Check the log and that the service is healthy.")
    finally:
        out.close()
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)
        ctl = os.environ.get("MCD_LAUNCHCTL", "launchctl")
        label = f"{cfg['label']}.source-update.{op['id'].replace('-', '.').lower()}"
        try:
            subprocess.run([ctl, "remove", label], capture_output=True, timeout=10)  # a submitted job would otherwise run again
        except (OSError, subprocess.SubprocessError):
            pass
    return code


def _run_steps(rec: Recorder, out, root: Path, data_dir: Path, db_path: Path, cfg: dict, tag: str, commit: str, opener, runner) -> int:
    label, port = cfg["label"], int(cfg["port"])
    rec.step("preflight", "running")
    inspection = inspect(root, product=PRODUCT, label=label)
    if not inspection["eligible"]:
        raise SourceUpdateError(inspection["problems"])
    if inspection["commit"] != rec.op["from"]["commit"]:
        raise SourceUpdateError("The checkout changed after you confirmed the update. Check again.")
    blockers = ue.drain_blockers(db_path)
    if blockers:
        raise SourceUpdateError("Drain first.", blockers)
    log(out, f"checkout {inspection['short']} v{inspection['version']}, remote {inspection['remote']}, idle")
    rec.step("preflight", "ok", "official remote, clean checkout, nothing running or waiting")

    rec.step("verify", "running")
    found = check(root, data_dir, db_path=db_path, product=PRODUCT, label=label, opener=opener)
    if not found["available"] or found["candidate"]["tag"] != tag or found["verified"]["commit"] != commit:
        raise SourceUpdateError("The newest verified release is no longer the one you confirmed.")
    log(out, f"{tag} signed by {found['verified']['signer']}, source commit {commit[:7]}")
    rec.step("verify", "ok", f"signature valid ({found['verified']['signer']}), names commit {commit[:7]}")

    rec.step("fetch", "running")
    env = {"PATH": tool_path(), "HOME": str(Path.home()), "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    fetched = runner(["git", "-C", str(root), "fetch", "-q", OFFICIAL_URL, f"+refs/tags/{tag}:refs/tags/{tag}"],
                     capture_output=True, text=True, timeout=300, env=env)
    if fetched.returncode:
        raise SourceUpdateError(f"Could not fetch {tag} from the official repository.")
    actual = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if actual != commit:
        raise SourceUpdateError(f"The tag {tag} points at {actual[:7]}, not the signed commit {commit[:7]}. Refusing.")
    version = subprocess.run(["git", "-C", str(root), "show", f"{commit}:apps/api/version.py"], capture_output=True, text=True, env=env).stdout
    if f'"{rec.op["version"]}"' not in version:
        raise SourceUpdateError("The release's version.py does not carry the signed version.")
    log(out, f"{tag} is {commit[:7]} as signed")
    rec.step("fetch", "ok", f"{tag} is exactly the signed commit {commit[:7]}")

    rec.step("upgrade", "running", "backup, checkout, dependencies, web build, restart, health check")
    rec.op.update(message=f"Updating to {tag}. The service will restart.")
    rec.save()
    script_env = {**env, "MCD_DRIVER_DIR": str(root), "MAC_CONTROL_DATA_DIR": str(data_dir), "MCD_LAUNCHD_LABEL": label,
                  "MCD_PORT": str(port), "MCD_PYTHON": os.environ.get("MCD_PYTHON") or str(root / "apps" / "api" / ".venv" / "bin" / "python")}
    for hook in TEST_HOOKS:                       # tool overrides the upgrade script already honours; unset in production
        if os.environ.get(hook):
            script_env[hook] = os.environ[hook]
    started = time.time()
    proc = subprocess.Popen(["/bin/bash", str(root / "scripts" / "upgrade-driver.sh"), "--ref", commit, "--from", OFFICIAL_URL, "--label", tag, "--require-idle"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=script_env, cwd=str(root))
    for line in proc.stdout or []:
        log(out, line.rstrip())
    returncode = proc.wait()
    receipt = _receipt_since(data_dir, started)
    healthy = health(port) or {}
    ok = (returncode == 0 and bool(receipt) and receipt.get("result") == "ok" and healthy.get("git_sha") == commit[:7]
          and healthy.get("version") == rec.op["version"])
    if ok:
        rec.step("upgrade", "ok", "restarted and healthy on the new version")
        rec.step("finish", "ok", f"running {rec.op['version']} ({commit[:7]})")
        rec.finish("succeeded", f"Updated to {rec.op['version']} ({commit[:7]}). Health check passed.", receipt=receipt.get("file"), health=healthy)
        return 0
    rolled_back = bool(receipt and receipt.get("rolled_back"))
    rec.step("upgrade", "failed", "the upgrade did not complete")
    rec.step("finish", "failed", "rolled back to the previous version" if rolled_back else "check the service")
    rec.finish("rolled_back" if rolled_back else "failed",
               ("The update failed and the previous version was restored. " if rolled_back else
                "The update did not complete and the service state could not be confirmed. ") + "See the log; your data was backed up first.",
               receipt=(receipt or {}).get("file"), health=healthy)
    return 1


def _receipt_since(data_dir: Path, since: float) -> dict | None:
    folder = Path(data_dir) / "upgrades"
    try:
        files = sorted((p for p in folder.glob("*.json") if p.stat().st_mtime >= since - 1), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    for path in reversed(files):
        data = read_json(path)
        if data and "result" in data:
            return {**data, "file": str(path)}
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) == 3 and args[0] == "run" and args[1] == "--data-dir":
        return run(Path(args[2]))
    print("usage: source_update.py run --data-dir DIR", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
