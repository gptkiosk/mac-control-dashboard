"""scripts/install/bootstrap-mcd.sh: every refusal, run with --dry-run on synthetic packages.

Nothing here installs anything, loads a LaunchAgent or touches ~/.mac-control: HOME is a temp folder,
launchctl and curl are shims on PATH, and the real success path (staging, activate, launchd, health)
is covered by the isolated preview described in docs/install/updates-rollback-recovery.md.
The script uses BSD tools (shasum, grep, sed, tar), so these run on macOS only.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import platform
import re
import socket
import subprocess
import tarfile
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO / "scripts" / "install" / "bootstrap-mcd.sh"
BASE = "mcd-0.1.0-darwin-arm64"

pytestmark = pytest.mark.skipif(platform.system() != "Darwin" or platform.machine() != "arm64",
                                reason="the installer targets macOS arm64")


def free_port() -> int:
    """A port nothing listens on; the operator's own dashboard may be running on 8800 while these tests run."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_archive(path: Path, members) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for m in members:
            if isinstance(m, tuple):
                info = tarfile.TarInfo(m[0])
                info.size = len(m[1])
                tf.addfile(info, io.BytesIO(m[1]))
            else:
                tf.addfile(m)


def good_members():
    return [(f"{BASE}/apps/api/{name}", b"# module\n") for name in
            ("update_helper.py", "update_engine.py", "release_verify.py", "release_fetch.py", "update_recovery.py")]


class Package:
    """A synthetic release: archive plus a manifest that describes it, as release.py would."""

    def __init__(self, directory: Path, members=None, **overrides):
        self.dir = directory
        self.archive = directory / f"{BASE}.tar.gz"
        make_archive(self.archive, members if members is not None else good_members())
        data = self.archive.read_bytes()
        manifest = {
            "schema": "dashboard-release-manifest/v1", "product": "mcd", "version": "0.1.0", "channel": "stable",
            "platform": {"key": "darwin-arm64", "os": "darwin", "arch": "arm64"},
            "source": {"commit": "0" * 40, "dirty": False, "release_eligible": True},
            "artifact": {"name": f"{BASE}.tar.gz", "root": BASE, "format": "tar+gzip",
                         "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)},
        }
        manifest.update(overrides)
        self.manifest = directory / f"{BASE}.manifest.json"
        self.manifest.write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.home = directory / "home"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)
        self.shims = directory / "shims"
        self.shims.mkdir(exist_ok=True)
        self.extra_env: dict = {}
        self.shim("launchctl", "exit 113")   # nothing is loaded; never ask the real launchd (the dashboard may be running)

    def shim(self, name: str, body: str) -> None:
        path = self.shims / name
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    def run(self, *extra: str, digest: str | None = None, dry: bool = True, base_args: list | None = None):
        args = base_args if base_args is not None else [
            "--archive", str(self.archive), "--manifest", str(self.manifest), "--manifest-sha256", digest or self.digest]
        port = [] if "--port" in extra else ["--port", str(free_port())]
        argv = ["/bin/bash", str(BOOTSTRAP), *args, *port, *(["--dry-run"] if dry else []), *extra]
        env = {**os.environ, "HOME": str(self.home), "MCD_INSTALL_ROOT": str(self.dir / "root"),
               "MAC_CONTROL_DATA_DIR": str(self.dir / "data"), "PATH": f"{self.shims}:{os.environ['PATH']}",
               **self.extra_env}
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)


@pytest.fixture
def pkg(tmp_path):
    return Package(tmp_path)


def refused(result, *fragments):
    assert result.returncode != 0, result.stdout
    for fragment in fragments:
        assert fragment in result.stderr, result.stderr
    assert "dry run: nothing was changed" not in result.stdout


# --- the package -------------------------------------------------------------------------


def test_a_valid_package_dry_run_prints_the_plan_and_changes_nothing(pkg):
    result = pkg.run()
    assert result.returncode == 0, result.stderr
    assert "dry run: nothing was changed" in result.stdout and "healthz" in result.stdout
    assert not (pkg.dir / "root").exists() and not (pkg.dir / "data").exists()
    assert list((pkg.home / "Library" / "LaunchAgents").iterdir()) == []


def test_wrong_manifest_digest_is_refused(pkg):
    refused(pkg.run(digest="0" * 64), "not the pinned")


def test_missing_or_malformed_manifest_digest_is_refused(pkg):
    refused(pkg.run(base_args=["--archive", str(pkg.archive), "--manifest", str(pkg.manifest)]), "--manifest-sha256")
    refused(pkg.run(digest="abc"), "64-hex")


def test_cross_product_package_is_refused(tmp_path):
    refused(Package(tmp_path, product="rcd").run(), "cross-product")


def test_wrong_platform_is_refused(tmp_path):
    p = Package(tmp_path, platform={"key": "linux-arm64", "os": "linux", "arch": "arm64"})
    refused(p.run(), "not for darwin-arm64")


def test_dev_channel_unclean_source_and_prerelease_are_refused(tmp_path):
    refused(Package(tmp_path, channel="dev").run(), "only stable or prerelease")
    refused(Package(tmp_path, source={"commit": None, "dirty": True, "release_eligible": False}).run(), "clean committed tree")
    refused(Package(tmp_path, channel="prerelease").run(), "--allow-prerelease")
    assert Package(tmp_path, channel="prerelease").run("--allow-prerelease").returncode == 0


def test_size_mismatch_is_refused(pkg):
    manifest = json.loads(pkg.manifest.read_text())
    manifest["artifact"]["size"] += 1
    pkg.manifest.write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    refused(pkg.run(digest=hashlib.sha256(pkg.manifest.read_bytes()).hexdigest()), "archive is")


def test_tampered_and_truncated_archives_are_refused(pkg):
    data = bytearray(pkg.archive.read_bytes())
    data[len(data) // 2] ^= 0xFF                      # one flipped byte in the middle
    pkg.archive.write_bytes(bytes(data))
    refused(pkg.run(), "archive sha256 differs")
    pkg.archive.write_bytes(bytes(data)[:100])        # a download that stopped early
    refused(pkg.run(), "archive is 100 bytes")


def link_member(target: str, kind=tarfile.SYMTYPE):
    link = tarfile.TarInfo(f"{BASE}/apps/api/link.py")
    link.type, link.linkname = kind, target
    return link


@pytest.mark.parametrize("extra", [
    (f"{BASE}/../escape.py", b"x"),
    ("/etc/evil", b"x"),
    ("mcd-0.1.0-darwin-arm64-evil/x.py", b"x"),
    link_member("/etc/passwd"),
    link_member("/etc/passwd", tarfile.LNKTYPE),
])
def test_unsafe_archive_members_are_refused(tmp_path, extra):
    refused(Package(tmp_path, members=good_members() + [extra]).run(), "member refused")


def test_setuid_members_are_refused(tmp_path):
    suid = tarfile.TarInfo(f"{BASE}/apps/api/evil.py")
    suid.mode = 0o4755
    refused(Package(tmp_path, members=good_members() + [suid]).run(), "member refused")


# --- arguments -----------------------------------------------------------------------------


def test_version_and_archive_together_are_refused(pkg):
    result = pkg.run(base_args=["--version", "0.1.0", "--archive", str(pkg.archive), "--manifest", str(pkg.manifest),
                                "--manifest-sha256", pkg.digest])
    refused(result, "not both")


@pytest.mark.parametrize("args,fragment", [
    (["--port", "80"], "--port"),
    (["--port", "99999"], "--port"),
    (["--port", "abc"], "--port"),
    (["--label", "bad label"], "--label"),
    (["--label", "../x"], "--label"),
    (["--root", "relative/path"], "absolute"),
    (["--root", "/tmp/a;b"], "--root"),
    (["--root", "/tmp/../etc"], "--root"),
    (["--data-dir", "/tmp/$(id)"], "--data-dir"),
    (["--env", "PATH=/evil"], "--env accepts"),
    (["--env", "MAC_CONTROL_DATA_DIR=/x"], "own option"),
    (["--env", "MAC_CONTROL_PORT=1"], "own option"),
    (["--env", "MAC_CONTROL_UPDATE_ROOT=/x"], "own option"),
    (["--env", "lowercase=1"], "--env accepts"),
    (["--nope"], "unknown argument"),
])
def test_bad_arguments_are_refused(pkg, args, fragment):
    refused(pkg.run(*args), fragment)


def test_explicit_python_path_is_not_silently_replaced(pkg):
    refused(pkg.run("--python", str(pkg.dir / "no-such-python")), "Python 3.12 is required")


# --- the host -------------------------------------------------------------------------------


def test_a_loaded_launch_agent_is_never_replaced(pkg):
    pkg.shim("launchctl", 'exit 0')   # `launchctl print` succeeds: the label is loaded
    refused(pkg.run(), "already loaded", "never replaces")


def test_an_existing_plist_is_never_replaced(pkg):
    pkg.shim("launchctl", 'exit 113')
    (pkg.home / "Library" / "LaunchAgents" / "com.operator.mac-control.plist").write_text("<plist/>")
    refused(pkg.run(), "refusing to replace")


def test_an_existing_install_is_not_installed_over(pkg):
    pkg.shim("launchctl", 'exit 113')
    (pkg.dir / "root").mkdir()
    (pkg.dir / "root" / "current").symlink_to("versions/x")
    refused(pkg.run(), "in-app updater")


def test_something_already_on_the_port_is_refused(pkg):
    class Healthz(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Healthz)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        pkg.shim("launchctl", 'exit 113')
        refused(pkg.run("--port", str(server.server_address[1])), "already answers")
    finally:
        server.shutdown()


def test_existing_data_is_not_taken_over_without_the_adopt_flag(pkg):
    pkg.shim("launchctl", 'exit 113')
    (pkg.dir / "data").mkdir()
    (pkg.dir / "data" / "data.db").write_text("live")
    refused(pkg.run(), "--adopt-existing-data")
    adopted = pkg.run("--adopt-existing-data")
    assert adopted.returncode == 0, adopted.stderr
    assert "existing data adopted" in adopted.stdout
    assert (pkg.dir / "data" / "data.db").read_text() == "live" and not (pkg.dir / "root").exists()


# --- downloads (curl is a shim; BSD grep/sed parse the redirect) -----------------------------


CURL = r'''
python3 - "$@" <<'PY'
import json, os, shutil, sys
args = sys.argv[1:]
url = args[-1]
out = args[args.index("--output") + 1]
hdr = args[args.index("--dump-header") + 1]
plan = json.load(open(os.environ["CURL_PLAN"]))
log = open(os.environ["CURL_LOG"], "a"); log.write(url + "\n"); log.close()
step = plan.get(url)
if step is None:
    open(hdr, "w").write("HTTP/2 404\r\n\r\n"); open(out, "wb").close(); print("404", end=""); sys.exit(0)
if "location" in step:
    open(hdr, "w").write("HTTP/2 302\r\nserver: x\r\nlocation: %s\r\n\r\n" % step["location"]); open(out, "wb").close(); print("302", end=""); sys.exit(0)
open(hdr, "w").write("HTTP/2 200\r\n\r\n"); shutil.copyfile(step["file"], out); print("200", end="")
PY
'''


def download_world(pkg, tmp_path, plan_for):
    base = "https://github.com/gptkiosk/mac-control-dashboard/releases/download/v0.1.0/" + BASE
    plan = plan_for(base)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    pkg.shim("curl", CURL.strip())
    pkg.shim("launchctl", "exit 113")
    pkg.extra_env = {"CURL_PLAN": str(tmp_path / "plan.json"), "CURL_LOG": str(tmp_path / "curl.log")}
    return base


def download_args(pkg):
    return ["--version", "0.1.0", "--manifest-sha256", pkg.digest]


def test_download_follows_a_github_redirect_with_a_lowercase_location_header(pkg, tmp_path):
    download_world(pkg, tmp_path, lambda base: {
        base + ".manifest.json": {"file": str(pkg.manifest)},
        base + ".tar.gz": {"location": "https://release-assets.githubusercontent.com/a/b?token=1"},
        "https://release-assets.githubusercontent.com/a/b?token=1": {"file": str(pkg.archive)}})
    result = pkg.run(base_args=download_args(pkg))
    assert result.returncode == 0, result.stderr
    assert "release-assets.githubusercontent.com" in (tmp_path / "curl.log").read_text()


@pytest.mark.parametrize("target,fragment", [
    ("https://evil.example/x", "unexpected host"),
    ("http://objects.githubusercontent.com/x", "absolute HTTPS URL"),
    ("//objects.githubusercontent.com/x", "absolute HTTPS URL"),
    ("https://github.com.evil.example/x", "unexpected host"),
])
def test_a_redirect_off_the_allowlist_or_off_https_is_refused(pkg, tmp_path, target, fragment):
    download_world(pkg, tmp_path, lambda base: {
        base + ".manifest.json": {"file": str(pkg.manifest)}, base + ".tar.gz": {"location": target}})
    refused(pkg.run(base_args=download_args(pkg)), fragment)
    assert "evil.example" not in (tmp_path / "curl.log").read_text()  # never even requested


def test_a_redirect_loop_is_cut_off(pkg, tmp_path):
    loop = "https://objects.githubusercontent.com/loop"
    download_world(pkg, tmp_path, lambda base: {
        base + ".manifest.json": {"file": str(pkg.manifest)}, base + ".tar.gz": {"location": loop}, loop: {"location": loop}})
    refused(pkg.run(base_args=download_args(pkg)), "too many download redirects")


def test_a_missing_release_asset_is_refused(pkg, tmp_path):
    download_world(pkg, tmp_path, lambda base: {})
    refused(pkg.run(base_args=download_args(pkg)), "HTTP 404")


def test_a_version_that_is_not_semver_is_refused(pkg):
    refused(pkg.run(base_args=["--version", "0.1", "--manifest-sha256", pkg.digest]), "--version")
    refused(pkg.run(base_args=["--version", "../../x", "--manifest-sha256", pkg.digest]), "--version")


# --- the helper copy list --------------------------------------------------------------------


API = REPO / "apps" / "api"


def copied_helper_files() -> set[str]:
    for line in BOOTSTRAP.read_text().splitlines():
        if line.startswith("for f in ") and "update_helper.py" in line:
            return set(line[len("for f in "):].split(";")[0].split())
    raise AssertionError("no helper copy loop found in bootstrap-mcd.sh")


def test_the_copy_loop_covers_every_module_the_helper_imports():
    seen, pending = set(), ["update_helper.py", "update_recovery.py"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for module in re.findall(r"^import (\w+)\b", (API / name).read_text(), re.MULTILINE):
            if (API / f"{module}.py").is_file():
                pending.append(f"{module}.py")
    assert seen - copied_helper_files() == set(), "bootstrap-mcd.sh does not copy a module the helper imports"
    assert all((API / name).is_file() for name in copied_helper_files())


def test_the_packaged_launchd_templates_are_in_the_package_list():
    product = json.loads((REPO / "packaging" / "product.json").read_text())
    assert "ops/launchd/*.template" in product["include"]
    for name in ("com.operator.mac-control.plist.template", "com.operator.mac-control.update-recover.plist.template"):
        assert (REPO / "ops" / "launchd" / name).is_file()
