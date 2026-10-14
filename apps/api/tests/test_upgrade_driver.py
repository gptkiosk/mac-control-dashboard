"""scripts/upgrade-driver.sh: preflight, backup, apply, verify exact commit and version, roll back, receipt."""
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "upgrade-driver.sh"
STATUS = Path(__file__).resolve().parents[3] / "scripts" / "driver-status.sh"


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


def commit_version(repo, version, lock="a==1\n", changelog=True, tag=None):
    (repo / "apps/api").mkdir(parents=True, exist_ok=True)
    (repo / "apps/web").mkdir(parents=True, exist_ok=True)
    (repo / "apps/web/package-lock.json").write_text("{}\n")
    (repo / "apps/api/version.py").write_text(f'__version__ = "{version}"\n')
    (repo / "apps/api/requirements.lock.txt").write_text(lock)
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{version}] - 2026-10-13\n\n### Added\n- thing\n" if changelog else "# Changelog\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", f"chore: {version}")
    if tag:
        git(repo, "tag", tag)


@pytest.fixture
def world(tmp_path):
    src = tmp_path / "source"; src.mkdir(); git(src, "init", "-q", "-b", "main")
    commit_version(src, "0.1.0", tag="v0.1.0")
    driver = tmp_path / "driver"
    subprocess.run(["git", "clone", "-q", str(src), str(driver)], check=True)
    git(driver, "remote", "remove", "origin"); git(driver, "checkout", "-q", "v0.1.0")
    data = tmp_path / "data"; data.mkdir()
    db = sqlite3.connect(data / "data.db"); db.execute("create table run (id integer, stage text)"); db.commit(); db.close()
    (data / ".env").write_text("A=1\n")
    shims = tmp_path / "shims"; shims.mkdir()
    # a pretend service: "restart" records the checkout it would run; curl answers /healthz for that checkout
    (shims / "launchctl").write_text(f'#!/bin/bash\ngit -C "{driver}" rev-parse --short HEAD > "{tmp_path}/running"\nexit 0\n')
    (shims / "curl").write_text(f'#!/bin/bash\n[ -f "{tmp_path}/running" ] || exit 0\nsha=$(cat "{tmp_path}/running"); [ -f "{tmp_path}/lie" ] && sha=deadbee\n'
                                f'v=$(sed -n \'s/^__version__ *= *"\\(.*\\)".*/\\1/p\' "{driver}/apps/api/version.py")\n'
                                'echo "{\\"status\\":\\"ok\\",\\"version\\":\\"$v\\",\\"git_sha\\":\\"$sha\\"}"\n')
    for name in ("npm", "uv"):
        (shims / name).write_text(f'#!/bin/bash\necho "$0 $*" >> "{tmp_path}/calls"\nexit 0\n')
    for f in shims.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "MCD_LAUNCHCTL": str(shims / "launchctl"), "MCD_CURL": str(shims / "curl"), "MCD_NPM": str(shims / "npm"),
           "MCD_UV": str(shims / "uv"), "MCD_HEALTH_WAIT_S": "2", "MAC_CONTROL_DATA_DIR": str(data), "GIT_CONFIG_GLOBAL": "/dev/null"}
    return SimpleWorld(tmp_path, src, driver, data, env)


class SimpleWorld:
    def __init__(self, tmp, src, driver, data, env):
        self.tmp, self.src, self.driver, self.data, self.env = tmp, src, driver, data, env

    def run(self, *args):
        return subprocess.run(["bash", str(SCRIPT), "--driver", str(self.driver), "--from", str(self.src), *args],
                              capture_output=True, text=True, env=self.env)

    def head(self):
        return git(self.driver, "rev-parse", "--short", "HEAD")


def test_upgrades_to_a_tag_backs_up_verifies_and_writes_a_receipt(world):
    commit_version(world.src, "0.2.0", lock="a==2\n", tag="v0.2.0")
    target = git(world.src, "rev-parse", "--short", "v0.2.0")
    r = world.run("--ref", "v0.2.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "v0.1.0" in r.stdout and "v0.2.0" in r.stdout and "upgraded: v0.2.0" in r.stdout
    assert world.head() == target
    receipts = list((world.data / "upgrades").glob("*.json"))
    rec = json.loads(receipts[0].read_text())
    assert rec["result"] == "ok" and rec["rolled_back"] is False and rec["to"]["version"] == "0.2.0"
    backup = Path(rec["backup"]); assert (backup / "data.db").is_file() and (backup / "env").read_text() == "A=1\n"
    calls = (world.tmp / "calls").read_text()
    assert "pip sync" in calls and "run build" in calls and "npm ci" not in calls          # the lock changed, package-lock did not


def test_dependencies_are_synced_only_when_a_lock_changed(world):
    commit_version(world.src, "0.2.0", lock="a==1\n", tag="v0.2.0")
    assert world.run("--ref", "v0.2.0").returncode == 0
    calls = (world.tmp / "calls").read_text()
    assert "pip sync" not in calls and "run build" in calls


def test_dry_run_changes_nothing(world):
    commit_version(world.src, "0.2.0", tag="v0.2.0")
    before = world.head()
    r = world.run("--ref", "v0.2.0", "--dry-run")
    assert r.returncode == 0 and "dry run" in r.stdout and "plan:" in r.stdout
    assert world.head() == before and not (world.data / "upgrades").exists() and not (world.tmp / "running").exists()


def test_refuses_while_runs_are_in_progress_and_a_dirty_checkout(world):
    commit_version(world.src, "0.2.0", tag="v0.2.0")
    db = sqlite3.connect(world.data / "data.db"); db.execute("insert into run values (1, 'running')"); db.commit(); db.close()
    r = world.run("--ref", "v0.2.0")
    assert r.returncode == 1 and "in progress" in r.stderr and world.head() != git(world.src, "rev-parse", "--short", "v0.2.0")
    db = sqlite3.connect(world.data / "data.db"); db.execute("delete from run"); db.commit(); db.close()
    (world.driver / "apps/api/version.py").write_text("# local edit\n")
    r = world.run("--ref", "v0.2.0")
    assert r.returncode == 1 and "uncommitted" in r.stderr


def test_same_ref_is_a_no_op_and_unknown_or_unsafe_refs_are_refused(world):
    assert "already on" in world.run("--ref", "v0.1.0").stdout
    r = world.run("--ref", "v9.9.9"); assert r.returncode == 1
    assert world.run("--ref", "v1; rm -rf /").returncode == 2


def test_a_failed_health_check_rolls_back_to_the_previous_commit(world):
    commit_version(world.src, "0.2.0", lock="a==2\n", tag="v0.2.0")
    previous = world.head()
    (world.tmp / "lie").write_text("1")                                  # the "service" reports the wrong commit
    r = world.run("--ref", "v0.2.0")
    assert r.returncode == 1 and "upgrade FAILED" in r.stdout and "health check" in r.stdout
    assert world.head() == previous
    rec = json.loads(next((world.data / "upgrades").glob("*.json")).read_text())
    assert rec["result"] == "failed" and rec["rolled_back"] is True


def test_status_reports_current_and_behind(world):
    shims = world.tmp / "shims"
    (world.tmp / "running").write_text(world.head())
    ok = subprocess.run(["bash", str(STATUS), "--driver", str(world.driver), "--from", str(world.src)], capture_output=True, text=True, env=world.env)
    assert "v0.1.0" in ok.stdout and "up to date" in ok.stdout
    commit_version(world.src, "0.2.0", tag="v0.2.0")
    behind = subprocess.run(["bash", str(STATUS), "--driver", str(world.driver), "--from", str(world.src)], capture_output=True, text=True, env=world.env)
    assert "NOT the newest tag" in behind.stdout and "--ref v0.2.0" in behind.stdout


# ------------------------------------------------------------------ publishing the GitHub release

PUBLISH = Path(__file__).resolve().parents[3] / "scripts" / "release" / "publish-release.sh"
CHANGELOG = Path(__file__).resolve().parents[3] / "scripts" / "release" / "changelog.py"


@pytest.fixture
def release_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); git(repo, "init", "-q", "-b", "main")
    (repo / "scripts/release").mkdir(parents=True)
    (repo / "scripts/release/changelog.py").write_text(CHANGELOG.read_text())
    (repo / "scripts/release/publish-release.sh").write_text(PUBLISH.read_text())
    (repo / "packaging").mkdir(); (repo / "packaging/product.json").write_text('{"repository": "owner/product"}')
    commit_version(repo, "1.1.0")
    commit_version(repo, "1.2.0")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.0] - 2026-10-13\n\n### Added\n- thing two\n\n## [1.1.0] - 2026-10-01\n\n### Added\n- thing one\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "docs: changelog")
    calls = tmp_path / "gh-calls"; state = tmp_path / "gh-state"
    gh = tmp_path / "gh"
    gh.write_text(f'''#!/bin/bash
echo "$@" >> "{calls}"
case "$1 $2" in
  "api repos/owner/product/commits/"*) [ -f "{state}/not-pushed" ] && exit 1; echo "${{3##*/}}"; exit 0;;
  "api repos/owner/product/git/ref/tags/"*) [ -f "{state}/tag-exists" ] && exit 0; exit 1;;
  "secret list") [ -f "{state}/has-secret" ] && printf 'RELEASE_SSH_PRIVATE_KEY\\t2026-10-13\\n'; exit 0;;
  "release view") exit 1;;
  "release create") echo "created"; exit 0;;
esac
exit 0
''')
    gh.chmod(0o755); state.mkdir()
    leaks = tmp_path / "gitleaks"                      # stands in for gitleaks so the test needs no install
    leaks.write_text(f'#!/bin/bash\necho "$@" >> "{tmp_path}/leak-calls"\n[ -f "{state}/leak" ] && exit 1\nexit 0\n'); leaks.chmod(0o755)
    env = {**os.environ, "MCD_GH": str(gh), "MCD_GITLEAKS": str(leaks)}
    def run(*args):
        return subprocess.run(["bash", str(repo / "scripts/release/publish-release.sh"), *args], capture_output=True, text=True, cwd=repo, env=env)
    return SimpleNamespace(repo=repo, run=run, calls=calls, state=state, head=lambda: git(repo, "rev-parse", "HEAD"))


from types import SimpleNamespace   # noqa: E402


def test_dry_run_shows_the_notes_the_release_will_carry(release_repo):
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "owner/product v1.2.0" in r.stdout and "- thing two" in r.stdout and "- thing one" not in r.stdout
    assert "compare/v1.1.0...v1.2.0" in r.stdout and "nothing published" in r.stdout
    assert "release create" not in (release_repo.calls.read_text() if release_repo.calls.exists() else "")


def test_publishes_the_tag_on_the_commit_with_notes_and_marks_it_latest(release_repo):
    sha = release_repo.head()
    r = release_repo.run("--version", "1.2.0", "--target", sha)
    assert r.returncode == 0, r.stderr
    create = next(l for l in release_repo.calls.read_text().splitlines() if l.startswith("release create"))
    assert "v1.2.0" in create and f"--target {sha}" in create and "--notes-file" in create and "--latest" in create and "--prerelease" not in create
    assert "published: https://github.com/owner/product/releases/tag/v1.2.0" in r.stdout
    pre = release_repo.run("--version", "1.2.0", "--target", sha, "--prerelease")
    assert "--prerelease" in [l for l in release_repo.calls.read_text().splitlines() if l.startswith("release create")][-1]


def calls_of(release_repo):
    return release_repo.calls.read_text().splitlines() if release_repo.calls.exists() else []


def test_package_mode_creates_only_the_tag_so_the_workflow_can_draft_the_release(release_repo):
    (release_repo.state / "has-secret").write_text("")
    sha = release_repo.head()
    r = release_repo.run("--version", "1.2.0", "--target", sha, "--package")
    assert r.returncode == 0, r.stderr
    calls = calls_of(release_repo)
    tag_call = next(c for c in calls if c.startswith("api -X POST repos/owner/product/git/refs"))
    assert "ref=refs/tags/v1.2.0" in tag_call and f"sha={sha}" in tag_call
    assert not any(c.startswith("release create") for c in calls)      # the workflow creates the draft, not this script
    assert "tagged: v1.2.0" in r.stdout and "review it and publish it" in r.stdout


def test_package_mode_refuses_without_the_signing_secret_and_creates_nothing(release_repo):
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--package")
    assert r.returncode != 0 and "RELEASE_SSH_PRIVATE_KEY" in r.stderr and "no tag was created" in r.stderr
    calls = calls_of(release_repo)
    assert not any(c.startswith("release create") or "git/refs" in c and "POST" in c for c in calls)


def test_package_dry_run_says_what_it_would_do_and_publishes_nothing(release_repo):
    (release_repo.state / "has-secret").write_text("")
    r = release_repo.run("--version", "1.2.0", "--target", release_repo.head(), "--package", "--dry-run")
    assert r.returncode == 0 and "tag only" in r.stdout and "nothing published" in r.stdout
    assert not any("POST" in c or c.startswith("release create") for c in calls_of(release_repo))


@pytest.mark.parametrize("setup,args,message", [
    (None, ["--version", "1.1.0"], "carries version"),                           # target carries 1.2.0
    (None, ["--version", "9.9.9"], "carries version"),
    ("not-pushed", ["--version", "1.2.0"], "not on GitHub"),
    ("tag-exists", ["--version", "1.2.0"], "already exists"),
])
def test_refuses_when_the_commit_version_notes_push_or_tag_are_wrong(release_repo, setup, args, message):
    if setup:
        (release_repo.state / setup).write_text("1")
    r = release_repo.run(*args, "--target", release_repo.head())
    assert r.returncode == 1 and message in r.stderr
    assert "release create" not in (release_repo.calls.read_text() if release_repo.calls.exists() else "")


def test_refuses_a_version_without_a_dated_changelog_section(release_repo):
    commit_version(release_repo.repo, "1.3.0", changelog=False)
    r = release_repo.run("--version", "1.3.0", "--target", release_repo.head())
    assert r.returncode == 1 and "changelog is not ready" in r.stderr


def test_publishing_scans_what_is_released_and_refuses_on_a_finding(release_repo):
    sha = release_repo.head()
    ok = release_repo.run("--version", "1.2.0", "--target", sha, "--dry-run")
    assert ok.returncode == 0
    scan = (release_repo.calls.parent / "leak-calls").read_text()
    assert "git" in scan and "--log-opts=" in scan and sha in scan and "--redact" in scan
    (release_repo.state / "leak").write_text("1")
    bad = release_repo.run("--version", "1.2.0", "--target", sha)
    assert bad.returncode == 1 and "possible secret" in bad.stderr
    assert "release create" not in (release_repo.calls.read_text() if release_repo.calls.exists() else "")
