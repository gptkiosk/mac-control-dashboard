"""Operator-approved update of a source checkout (source_update.py and /api/app-updates/source/*).

Real git repositories, a real ssh-keygen signature over a real manifest, and a fake GitHub (the opener) stand in
for the network; launchctl, curl, npm and uv are shims, so the real scripts/upgrade-driver.sh runs end to end.
Nothing here touches a running service or the real ~/.mac-control.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import release_fetch as rf
import release_verify as rv
import source_update as su
from routes import updates as routes
from tests.test_release_verify import PLATFORM, PRODUCT, SSH_KEYGEN, make_release, sha

REPO_ROOT = Path(__file__).resolve().parents[3]
API = REPO_ROOT / "apps" / "api"
REPOSITORY = rv.OFFICIAL_REPOSITORIES[PRODUCT]
pytestmark = pytest.mark.skipif(SSH_KEYGEN is None, reason="system ssh-keygen is not installed")


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, url: str):
        self._io, self._url = io.BytesIO(body), url
        self.headers = {"Content-Length": str(len(body))}

    def read(self, n=-1):
        return self._io.read(n)

    def close(self):
        pass

    def geturl(self):
        return self._url


class FakeGitHub:
    """The release list and the three assets of each published release, served to rf through its opener."""

    def __init__(self):
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.requests: list[str] = []

    def publish(self, tag: str, version: str, manifest: bytes, signature: bytes, notes: str = "Notes", archive: bytes = b"x" * 40,
                prerelease: bool = False) -> None:
        names = rf.asset_names(PRODUCT, version, PLATFORM)
        bodies = {"manifest": manifest, "signature": signature, "archive": archive}
        assets = []
        for kind, name in names.items():
            url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
            self.files[url] = bodies[kind]
            assets.append({"name": name, "size": len(bodies[kind]), "state": "uploaded", "digest": f"sha256:{sha(bodies[kind])}",
                           "browser_download_url": url})
        self.releases.append({"tag_name": tag, "draft": False, "prerelease": prerelease, "body": notes, "assets": assets,
                              "html_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}"})

    def __call__(self, req, timeout):
        url = req.full_url
        self.requests.append(url)
        if url.startswith(f"https://api.github.com/repos/{REPOSITORY}/releases"):
            return FakeResponse(json.dumps(self.releases).encode(), url)
        if url in self.files:
            return FakeResponse(self.files[url], url)
        raise rf.FetchError("unexpected URL in test: " + url)


def sign(key: Path, path: Path, namespace: str = "dashboard-release") -> bytes:
    sig = path.with_name(path.name + ".sig")
    sig.unlink(missing_ok=True)
    subprocess.run([SSH_KEYGEN, "-Y", "sign", "-f", str(key), "-n", namespace, str(path)], check=True, capture_output=True, timeout=30)
    return sig.read_bytes()


def keypair(tmp_path: Path, name: str) -> tuple[Path, str]:
    key = tmp_path / name
    subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "synthetic", "-f", str(key)], check=True, capture_output=True, timeout=30)
    kind, data = (tmp_path / f"{name}.pub").read_text().split()[:2]
    return key, f"{kind} {data}"


def commit_version(repo: Path, version: str, signers: str, tag: str | None = None, lock: str = "a==1\n") -> str:
    """A tiny but real checkout tree: the real upgrade script, update engine and verifier, a version and a changelog."""
    for rel in ("apps/api", "apps/web", "scripts", "packaging"):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "scripts" / "upgrade-driver.sh", repo / "scripts" / "upgrade-driver.sh")
    for name in ("update_engine.py", "release_verify.py"):
        shutil.copy(API / name, repo / "apps" / "api" / name)
    (repo / "packaging" / "allowed_signers").write_text(signers)
    (repo / "apps/web/package-lock.json").write_text("{}\n")
    (repo / "apps/api/version.py").write_text(f'__version__ = "{version}"\n')
    (repo / "apps/api/requirements.lock.txt").write_text(lock)
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{version}] - 2026-10-14\n\n### Added\n- thing\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"chore: {version}")
    if tag:
        git(repo, "tag", tag)
    return git(repo, "rev-parse", "HEAD")


class World:
    pass


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World()
    w.tmp = tmp_path
    w.key, public = keypair(tmp_path, "release_key")
    w.signers = f"dashboard-release {public}\n"
    # "GitHub" as a bare repository, and the driver cloned from it at the old release
    work = tmp_path / "work"; work.mkdir(); git(work, "init", "-q", "-b", "main")
    w.old = commit_version(work, "0.1.0", w.signers, "v0.1.0")
    w.work = work
    w.bare = tmp_path / "official.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(w.bare)], check=True)
    w.driver = tmp_path / "driver"
    subprocess.run(["git", "clone", "-q", str(w.bare), str(w.driver)], check=True)
    git(w.driver, "checkout", "-q", "v0.1.0")
    w.data = tmp_path / "data"; w.data.mkdir()
    w.db = w.data / "data.db"
    con = sqlite3.connect(w.db)
    con.executescript('create table run (id integer, card_id integer, stage text, ended_at integer); create table card (id integer, "column" text, approved_at integer, approval_grant text);'
                      "create table project (id integer, state text); create table project_task (card_id integer, project_id integer);")
    con.commit(); con.close()
    (w.data / ".env").write_text("A=1\n")
    # shims: the "service" records the commit it restarted on and answers /healthz for it
    shims = tmp_path / "shims"; shims.mkdir()
    (shims / "launchctl").write_text(f'#!/bin/bash\ncase "$1" in kickstart) git -C "{w.driver}" rev-parse --short HEAD > "{tmp_path}/running";; esac\nexit 0\n')
    (shims / "curl").write_text(f'#!/bin/bash\n[ -f "{tmp_path}/running" ] || exit 0\nsha=$(cat "{tmp_path}/running"); [ -f "{tmp_path}/lie" ] && sha=deadbee\n'
                                f'v=$(sed -n \'s/^__version__ *= *"\\(.*\\)".*/\\1/p\' "{w.driver}/apps/api/version.py")\n'
                                'echo "{\\"status\\":\\"ok\\",\\"version\\":\\"$v\\",\\"git_sha\\":\\"$sha\\"}"\n')
    for name in ("npm", "uv"):
        (shims / name).write_text(f'#!/bin/bash\necho "$0 $*" >> "{tmp_path}/calls"\nexit 0\n')
    for f in shims.iterdir():
        f.chmod(0o755)
    (tmp_path / "running").write_text(git(w.driver, "rev-parse", "--short", "HEAD"))
    for key, value in {"MCD_LAUNCHCTL": shims / "launchctl", "MCD_CURL": shims / "curl", "MCD_NPM": shims / "npm", "MCD_UV": shims / "uv",
                       "MCD_PYTHON": sys.executable}.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("MCD_HEALTH_WAIT_S", "3")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    # a Mac on Apple silicon with the tools installed, and this bare repository as the official remote
    monkeypatch.setattr(su.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(su.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(rv, "host_platform", lambda: PLATFORM)
    monkeypatch.setattr(su, "find_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(su, "REMOTE_FORMS", (str(w.bare),))
    monkeypatch.setattr(su, "OFFICIAL_URL", str(w.bare))
    monkeypatch.setattr(su, "health", lambda port: json.loads(subprocess.run([os.environ["MCD_CURL"]], capture_output=True, text=True).stdout or "null"))
    w.github = FakeGitHub()
    return w


def release_new(w, version="0.2.0", tag=None, lock="a==1\n", signer_key=None, namespace="dashboard-release", commit_override=None, **hooks):
    """Publish a new signed release: a commit and tag in the official repository, and its signed manifest on 'GitHub'."""
    tag = tag or f"v{version}"
    commit = commit_version(w.work, version, w.signers, tag, lock=lock)
    git(w.work, "push", "-q", str(w.bare), "main", f"refs/tags/{tag}")
    rel = make_release(w.tmp, version=version, name=f"rel-{version}-{len(w.github.releases)}",
                       manifest_hook=lambda m: (m["source"].update(commit=commit_override or commit), hooks.get("manifest_hook", lambda m: None)(m)))
    signature = sign(signer_key or w.key, rel.manifest_path, namespace)
    w.github.publish(tag, version, rel.manifest_bytes, signature)
    w.commit, w.tag = commit, tag
    return commit


def checked(w):
    return su.check(w.driver, w.data, db_path=w.db, product="mcd", label="com.test.mcd", opener=w.github)


def begin(w, **kw):
    spawned = []
    args = dict(db_path=w.db, product="mcd", label="com.test.mcd", port=8899, tag=w.tag, commit=w.commit, confirm=True,
                opener=w.github, spawner=lambda argv, label, out: spawned.append((argv, label, out)))
    args.update(kw)
    return su.begin(w.driver, w.data, **args), spawned


def refusal(call, *a, **kw) -> su.SourceUpdateError:
    with pytest.raises(su.SourceUpdateError) as exc:
        call(*a, **kw)
    return exc.value


# ------------------------------------------------------------------------------------ eligibility


def test_a_clean_official_checkout_is_eligible(world):
    info = su.inspect(world.driver, product="mcd", label="com.test.mcd")
    assert info["eligible"] and info["problems"] == [] and info["version"] == "0.1.0" and info["tag"] == "v0.1.0"
    assert info["official_remote"] and info["clean"] and info["commit"] == world.old


def test_a_checkout_with_no_remote_is_eligible_and_updates_from_the_official_repository(world):
    git(world.driver, "remote", "remove", "origin")                     # how a frozen production driver is kept
    info = su.inspect(world.driver, product="mcd", label="com.test.mcd")
    assert info["eligible"] and info["remote"] is None and info["official_remote"]
    release_new(world)
    operation_after_begin(world)
    assert run_helper(world) == 0
    assert su.read_operation(world.data)["state"] == "succeeded" and git(world.driver, "rev-parse", "HEAD") == world.commit
    assert git(world.driver, "remote") == ""                             # nothing was left behind in the repository config


def test_forks_and_other_remotes_are_never_updated_this_way(world):
    git(world.driver, "remote", "set-url", "origin", "https://github.com/someone/mac-control-dashboard.git")
    info = su.inspect(world.driver, product="mcd", label="com.test.mcd")
    assert not info["eligible"] and any("not the official repository" in p for p in info["problems"])
    # and an official URL that smuggles credentials is shown without them
    git(world.driver, "remote", "set-url", "origin", f"https://token123@github.com/{REPOSITORY}.git")
    assert "token123" not in json.dumps(su.inspect(world.driver, product="mcd", label="com.test.mcd"))


def test_a_modified_checkout_is_refused_and_untracked_files_are_not_modifications(world):
    (world.driver / "scratch.txt").write_text("not tracked")
    assert su.inspect(world.driver, product="mcd", label="com.test.mcd")["eligible"]
    (world.driver / "apps/api/version.py").write_text("# edited\n")
    info = su.inspect(world.driver, product="mcd", label="com.test.mcd")
    assert not info["eligible"] and any("uncommitted changes" in p for p in info["problems"])


def test_unsupported_platforms_products_and_missing_prerequisites_are_refused(world, monkeypatch):
    assert any("MCD only" in p for p in su.inspect(world.driver, product="rcd", label="x")["problems"])
    monkeypatch.setattr(su.platform, "system", lambda: "Linux")
    assert any("macOS on Apple silicon" in p for p in su.inspect(world.driver, product="mcd", label="x", system="Linux", machine="aarch64")["problems"])
    monkeypatch.setattr(su, "find_tool", lambda name: None if name == "uv" else "/usr/bin/" + name)
    info = su.inspect(world.driver, product="mcd", label="x", system="Darwin", machine="arm64")
    assert any("Missing prerequisites: uv" in p for p in info["problems"]) and info["prerequisites"]["uv"] is False


def test_a_service_that_is_not_loaded_is_refused(world, monkeypatch, tmp_path):
    off = tmp_path / "off"; off.write_text("#!/bin/bash\nexit 113\n"); off.chmod(0o755)
    monkeypatch.setenv("MCD_LAUNCHCTL", str(off))
    info = su.inspect(world.driver, product="mcd", label="com.test.mcd")
    assert not info["eligible"] and any("not loaded" in p for p in info["problems"])


def test_not_a_git_checkout_is_refused(tmp_path):
    info = su.inspect(tmp_path, product="mcd", label="x", system="Darwin", machine="arm64")
    assert not info["eligible"] and "This is not a git checkout." in info["problems"]


# ------------------------------------------------------------------------------------ the check


def test_check_shows_the_exact_tag_notes_and_signed_commit_and_downloads_no_package(world):
    release_new(world)
    found = checked(world)
    assert found["available"] and found["candidate"]["tag"] == "v0.2.0" and found["candidate"]["notes"] == "Notes"
    assert found["verified"]["commit"] == world.commit and found["verified"]["signer"].startswith("ssh-signature")
    assert found["blockers"] == []
    assert not any(url.endswith(".tar.gz") for url in world.github.requests)       # manifest + signature only


def test_check_with_nothing_newer_offers_nothing(world):
    assert checked(world)["available"] is False
    assert checked(world)["candidate"] is None


def test_an_ineligible_checkout_is_never_checked_against_the_network(world):
    git(world.driver, "remote", "set-url", "origin", "https://github.com/someone/fork.git")
    release_new(world)
    world.github.requests.clear()
    assert checked(world)["available"] is False and world.github.requests == []


def test_a_release_signed_by_another_key_or_namespace_is_refused(world, tmp_path):
    other, _ = keypair(tmp_path, "other_key")
    release_new(world, signer_key=other)
    assert "signed manifest was not verified" in refusal(checked, world).problems[0]
    world.github.releases.clear()
    release_new(world, "0.3.0", namespace="file")
    assert "signed manifest was not verified" in refusal(checked, world).problems[0]


def test_a_manifest_changed_after_signing_is_refused(world):
    release_new(world)
    url = next(u for u in world.github.files if u.endswith(".manifest.json"))
    tampered = json.loads(world.github.files[url]); tampered["source"]["commit"] = "b" * 40
    body = (json.dumps(tampered, indent=2, sort_keys=True) + "\n").encode()
    world.github.files[url] = body
    asset = next(a for a in world.github.releases[0]["assets"] if a["browser_download_url"] == url)
    asset["size"], asset["digest"] = len(body), f"sha256:{sha(body)}"   # even GitHub's own digest matches: the signature must still fail
    assert "signed manifest was not verified" in refusal(checked, world).problems[0]


@pytest.mark.parametrize("change", [{"dirty": True}, {"release_eligible": False}])
def test_a_manifest_for_a_dirty_or_ineligible_source_is_refused(world, change):
    release_new(world, manifest_hook=lambda m: m["source"].update(change))
    assert "signed manifest was refused" in refusal(checked, world).problems[0]


def test_the_manifest_must_be_mcd_stable_and_this_version(world):
    release_new(world, manifest_hook=lambda m: m.update(version="9.9.9"))
    assert any("not 0.2.0" in p or "version" in p for p in refusal(checked, world).problems)


def test_blockers_are_reported_by_the_check_but_do_not_hide_the_release(world):
    release_new(world)
    con = sqlite3.connect(world.db)
    con.execute("insert into run (id, stage, ended_at) values (1, 'running', NULL)")
    con.execute("insert into run (id, stage, ended_at) values (2, 'awaiting_approval', NULL)")
    con.execute("insert into card (id, \"column\") values (1, 'queued')")
    con.execute("insert into project values (1, 'active')")
    con.commit(); con.close()
    found = checked(world)
    assert found["available"] and len(found["blockers"]) >= 3
    assert any("waiting on a human decision" in b for b in found["blockers"])


def test_an_approved_task_that_has_not_started_blocks_the_update(world):
    release_new(world)
    grant = json.dumps({"nonce": "n", "run_id": None, "expires_at": int(time.time()) + 600})
    con = sqlite3.connect(world.db)
    con.execute("insert into card (id, \"column\", approved_at, approval_grant) values (1, 'ready', 1, ?)", (grant,))
    con.commit(); con.close()
    assert any("approved task" in b for b in checked(world)["blockers"])


# ------------------------------------------------------------------------------------ begin


def test_begin_needs_explicit_confirmation_and_exact_identifiers(world):
    release_new(world)
    assert "confirmation" in refusal(begin, world, confirm=False).problems[0]
    assert "full commit" in refusal(begin, world, commit="abc").problems[0]
    assert "full commit" in refusal(begin, world, tag="main").problems[0]


def test_begin_refuses_when_the_release_moved_on_since_the_page_checked(world):
    release_new(world)
    stale = (world.tag, world.commit)
    release_new(world, "0.3.0")
    assert "no longer the one you confirmed" in refusal(begin, world, tag=stale[0], commit=stale[1]).problems[0]


def test_begin_refuses_a_commit_the_signature_does_not_name(world):
    release_new(world)
    assert "no longer the one you confirmed" in refusal(begin, world, commit="b" * 40).problems[0]


def test_begin_never_stops_work_it_says_what_to_drain(world):
    release_new(world)
    con = sqlite3.connect(world.db); con.execute("insert into run (id, stage, ended_at) values (1, 'running', NULL)"); con.commit(); con.close()
    err = refusal(begin, world)
    assert err.blockers and "Drain first" in err.problems[0] and not su.data_paths(world.data)["op"].exists()


def test_begin_writes_a_private_operation_and_hands_the_helper_to_launchd_only(world):
    release_new(world)
    started, spawned = begin(world)
    assert len(spawned) == 1 and started["poll"].endswith("/source/operation")
    argv, label, out = spawned[0]
    assert label.startswith("com.test.mcd.source-update.") and "run" in argv and str(world.data) in argv
    paths = su.data_paths(world.data)
    assert oct(paths["dir"].stat().st_mode & 0o777) == "0o700" and oct(paths["op"].stat().st_mode & 0o777) == "0o600"
    op = su.read_operation(world.data)
    assert op["state"] == "starting" and op["tag"] == "v0.2.0" and op["commit"] == world.commit and op["from"]["commit"] == world.old
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_a_helper_that_cannot_be_started_is_reported_and_leaves_no_pending_operation(world):
    release_new(world)

    def refuse(argv, label, out):
        raise su.SourceUpdateError("launchd refused to start the update helper.")
    assert "launchd refused" in refusal(begin, world, spawner=refuse).problems[0]
    assert su.read_operation(world.data)["state"] == "failed"
    assert su.run(world.data) == 2                                       # a failed operation can never be picked up and run


def test_a_second_update_cannot_start_while_one_is_running(world):
    release_new(world)
    begin(world)
    lock = os.open(su.data_paths(world.data)["lock"], os.O_RDWR | os.O_CREAT)
    import fcntl
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        assert su.operation_active(world.data)
        assert "already running" in refusal(begin, world).problems[0]
    finally:
        os.close(lock)
    assert not su.operation_active(world.data)


def test_status_says_so_when_the_helper_died_without_a_result(world):
    release_new(world)
    begin(world)
    assert su.status(world.data)["operation"]["state"] == "starting"
    op = su.read_operation(world.data); op["started_at"] = int(time.time()) - 120
    su.write_json_private(su.data_paths(world.data)["op"], op)
    shown = su.status(world.data)["operation"]
    assert shown["state"] == "failed" and "stopped without reporting" in shown["message"]


# ------------------------------------------------------------------------------------ the helper, end to end


def run_helper(w, **kw):
    return su.run(w.data, opener=w.github, **kw)


def operation_after_begin(w):
    begin(w)
    return su.read_operation(w.data)


def test_the_helper_updates_the_checkout_verifies_health_and_reports_success(world):
    release_new(world, lock="a==2\n")
    operation_after_begin(world)
    assert run_helper(world) == 0
    op = su.read_operation(world.data)
    assert op["state"] == "succeeded" and "0.2.0" in op["message"] and op["health"]["git_sha"] == world.commit[:7]
    assert [s["name"] for s in op["steps"]] == list(su.STEPS) and all(s["state"] == "ok" for s in op["steps"])
    assert git(world.driver, "rev-parse", "HEAD") == world.commit
    receipt = json.loads(next((world.data / "upgrades").glob("*.json")).read_text())
    assert receipt["result"] == "ok" and receipt["to"]["ref"] == "v0.2.0" and receipt["to"]["commit"] == world.commit
    assert (Path(receipt["backup"]) / "data.db").is_file() and (Path(receipt["backup"]) / "env").read_text() == "A=1\n"
    calls = (world.tmp / "calls").read_text()
    assert "pip sync" in calls and "run build" in calls
    log = "\n".join(su.status(world.data)["log"])
    assert "signed by" in log and "as signed" in log
    assert oct((su.data_paths(world.data)["dir"] / op["log"]).stat().st_mode & 0o777) == "0o600"


def test_the_helper_rolls_back_and_says_so_when_the_new_version_is_not_healthy(world):
    release_new(world)
    previous = git(world.driver, "rev-parse", "--short", "HEAD")
    operation_after_begin(world)
    (world.tmp / "lie").write_text("1")                                  # the restarted service reports the wrong commit
    assert run_helper(world) == 1
    op = su.read_operation(world.data)
    assert op["state"] == "rolled_back" and "previous version was restored" in op["message"]
    assert git(world.driver, "rev-parse", "--short", "HEAD") == previous
    assert next(s for s in op["steps"] if s["name"] == "upgrade")["state"] == "failed"


def test_the_helper_refuses_a_tag_that_moved_to_another_commit_and_changes_nothing(world):
    release_new(world)
    operation_after_begin(world)
    rogue = commit_version(world.work, "0.2.0", world.signers + "# rogue\n")      # a different commit, same version
    git(world.work, "tag", "-f", "v0.2.0"); git(world.work, "push", "-q", "-f", str(world.bare), "refs/tags/v0.2.0")
    assert rogue != world.commit
    assert run_helper(world) == 1
    op = su.read_operation(world.data)
    assert op["state"] == "failed" and "not the signed commit" in op["message"] and "Nothing was changed" in op["message"]
    assert git(world.driver, "rev-parse", "HEAD") == world.old and not (world.data / "upgrades").exists()


def test_the_helper_refuses_if_work_started_after_the_confirmation(world):
    release_new(world)
    operation_after_begin(world)
    con = sqlite3.connect(world.db); con.execute("insert into card (id, \"column\") values (1, 'queued')"); con.commit(); con.close()
    assert run_helper(world) == 1
    op = su.read_operation(world.data)
    assert op["state"] == "failed" and "Drain first" in op["message"] and git(world.driver, "rev-parse", "HEAD") == world.old


def test_the_helper_refuses_if_the_checkout_changed_after_the_confirmation(world):
    release_new(world)
    operation_after_begin(world)
    git(world.driver, "checkout", "-q", "--detach", "HEAD")
    commit_version(world.driver, "0.1.1", world.signers)
    assert run_helper(world) == 1
    assert "checkout changed after you confirmed" in su.read_operation(world.data)["message"]


def test_the_upgrade_script_itself_refuses_a_busy_service_even_if_called_directly(world):
    release_new(world)
    con = sqlite3.connect(world.db); con.execute("insert into project values (1, 'dispatching')"); con.commit(); con.close()
    result = subprocess.run(["bash", str(REPO_ROOT / "scripts/upgrade-driver.sh"), "--driver", str(world.driver), "--ref", world.commit,
                             "--label", "v0.2.0", "--require-idle"],
                            capture_output=True, text=True, env={**os.environ, "MAC_CONTROL_DATA_DIR": str(world.data)})
    assert result.returncode == 1 and "not idle" in result.stderr and "in progress" in result.stderr
    assert git(world.driver, "rev-parse", "HEAD") == world.old


def test_a_pending_operation_is_required_to_run_and_runs_only_once(world):
    assert su.run(world.data) == 2                                       # nothing pending
    release_new(world)
    operation_after_begin(world)
    assert run_helper(world) == 0
    assert su.run(world.data, opener=world.github) == 2                   # the finished operation is not run again


def test_the_helper_passes_only_known_variables_to_the_script(world, monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "hunter2")
    release_new(world)
    operation_after_begin(world)
    seen = {}
    real_popen = subprocess.Popen

    def spy(cmd, **kw):
        if any("upgrade-driver.sh" in str(part) for part in cmd):
            seen.update(kw["env"])
        return real_popen(cmd, **kw)
    monkeypatch.setattr(su.subprocess, "Popen", spy)
    assert run_helper(world) == 0
    assert "SOME_SECRET" not in seen and seen["MCD_LAUNCHD_LABEL"] == "com.test.mcd" and seen["MCD_PORT"] == "8899"


# ------------------------------------------------------------------------------------ routes


@pytest.fixture
def client(make_client, monkeypatch):
    c = make_client()
    state = {"signed_in": True, "agent": False}

    @c.app.middleware("http")
    async def session(request, call_next):
        if state["signed_in"]:
            request.state.user = {"email": "operator@example.invalid"}
        if state["agent"]:
            request.state.agent_grant = {"id": "test"}
        return await call_next(request)

    c.state = state
    return c


START = {"tag": "v0.2.0", "commit": "a" * 40, "confirm": True}


def test_the_source_routes_are_operator_only(client):
    client.state["signed_in"] = False
    for path in ("/api/app-updates/source", "/api/app-updates/source/check", "/api/app-updates/source/operation"):
        assert client.get(path).status_code in (401, 403)
    assert client.post("/api/app-updates/source/start", json=START).status_code in (401, 403)
    client.state.update(signed_in=True, agent=True)
    for path in ("/api/app-updates/source", "/api/app-updates/source/check", "/api/app-updates/source/operation"):
        assert client.get(path).status_code == 403
    assert client.post("/api/app-updates/source/start", json=START).status_code == 403


def test_start_validates_its_body(client):
    for body in ({"tag": "v0.2.0", "commit": "a" * 40}, {"tag": "main", "commit": "a" * 40, "confirm": True},
                 {"tag": "v0.2.0", "commit": "abc", "confirm": True}, {**START, "extra": 1}):
        assert client.post("/api/app-updates/source/start", json=body).status_code == 422


def test_start_hands_exactly_the_confirmed_tag_and_commit_to_the_updater(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(routes.su, "begin", lambda root, data_dir, **kw: seen.update(kw, root=root, data_dir=data_dir) or {"operation_id": "x", "poll": "p"})
    response = client.post("/api/app-updates/source/start", json=START)
    assert response.status_code == 202 and response.json()["operation_id"] == "x"
    assert seen["tag"] == "v0.2.0" and seen["commit"] == "a" * 40 and seen["confirm"] is True and seen["root"] == routes.REPO_ROOT


def test_refusals_reach_the_page_as_a_message_with_problems_and_blockers(client, monkeypatch):
    def refuse(*a, **kw):
        raise su.SourceUpdateError(["Drain first. Nothing was stopped."], ["1 run still running"])
    monkeypatch.setattr(routes.su, "begin", refuse)
    response = client.post("/api/app-updates/source/start", json=START)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"].startswith("Drain first") and detail["blockers"] == ["1 run still running"]
    monkeypatch.setattr(routes.su, "check", lambda *a, **kw: (_ for _ in ()).throw(su.SourceUpdateError(["Could not check for updates.", "network error"])))
    assert client.get("/api/app-updates/source/check").status_code == 502


def test_the_updates_status_offers_the_source_update_only_on_a_checkout(client, monkeypatch):
    monkeypatch.setattr(routes.ue, "install_kind", lambda app_root, root: ("dev", "git checkout"))
    monkeypatch.setattr(routes, "_source_inspection", lambda: {"eligible": True, "problems": []})
    assert client.get("/api/app-updates").json()["source"] == {"eligible": True, "problems": []}
    monkeypatch.setattr(routes.ue, "install_kind", lambda app_root, root: ("release", "packaged"))
    assert "source" not in client.get("/api/app-updates").json()
