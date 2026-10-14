"""launchd service control for the managed updater (N4).

A stateful fake `launchctl` stands in for the real one, so these run anywhere and never touch the
operator's LaunchAgents. The real launchd is exercised separately by the isolated preview
(docs/install/updates-rollback-recovery.md). What is pinned here: unload before load, a job left
loaded and crash-looping by a bad release, a disabled override, a transient bootstrap error, a
plist without RunAtLoad, and that the engine's rollback goes through this same path.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

import update_engine as ue
from tests.test_update_engine import cfg, fake_builder, installed, marker, no_blockers, set_marker, this_host  # noqa: F401

FAKE = '''#!{python}
import json, sys
state_path = {state!r}
st = json.load(open(state_path))
args = sys.argv[1:]
st["log"].append(args)
def save():
    json.dump(st, open(state_path, "w"))
verb = args[0]
if verb == "print":
    if st["loaded"] and st["teardown_prints"] > 0 and st["tearing_down"]:
        st["teardown_prints"] -= 1
        if st["teardown_prints"] == 0:
            st["loaded"] = st["tearing_down"] = False
        save(); sys.exit(0)
    save(); sys.exit(0 if st["loaded"] else 113)
if verb == "bootout":
    if st["loaded"]:
        if st["teardown_prints"]:
            st["tearing_down"] = True
        else:
            st["loaded"] = False
        st["running"] = False
    save(); sys.exit(0)
if verb == "enable":
    st["disabled"] = False
    save(); sys.exit(0)
if verb == "bootstrap":
    if st["disabled"]:
        sys.stderr.write("Bootstrap failed: 119: Service is disabled\\n"); save(); sys.exit(119)
    if st["loaded"]:
        sys.stderr.write("Bootstrap failed: 5: Input/output error\\n"); save(); sys.exit(5)
    if st["bootstrap_failures"] > 0:
        st["bootstrap_failures"] -= 1
        sys.stderr.write("Bootstrap failed: 5: Input/output error\\n"); save(); sys.exit(5)
    st["loaded"] = True
    st["running"] = st["run_at_load"]
    save(); sys.exit(0)
if verb == "kickstart":
    if not st["loaded"]:
        sys.stderr.write("Could not find service\\n"); save(); sys.exit(113)
    st["running"] = True
    save(); sys.exit(0)
sys.exit(64)
'''


class FakeLaunchctl:
    def __init__(self, tmp_path: Path, monkeypatch, **initial):
        self.state = tmp_path / "launchctl-state.json"
        self.path = tmp_path / "launchctl"
        self.path.write_text(FAKE.format(python=sys.executable, state=str(self.state)))
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)
        self.write({"loaded": False, "running": False, "disabled": False, "run_at_load": True,
                    "bootstrap_failures": 0, "teardown_prints": 0, "tearing_down": False, "log": [], **initial})
        monkeypatch.setattr(ue.LaunchdService, "LAUNCHCTL", str(self.path))
        monkeypatch.setattr(ue.LaunchdService, "BOOTSTRAP_PAUSE", 0.0)

    def write(self, state: dict) -> None:
        self.state.write_text(json.dumps(state))

    def read(self) -> dict:
        return json.loads(self.state.read_text())

    def verbs(self) -> list[str]:
        return [call[0] for call in self.read()["log"] if call[0] != "print"]


def service() -> ue.LaunchdService:
    return ue.LaunchdService("test.dashboard", "/nonexistent.plist")


def test_start_loads_the_job_and_leaves_it_running(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch)
    service().start()
    state = fake.read()
    assert state["loaded"] and state["running"]
    assert fake.verbs() == ["enable", "bootstrap", "kickstart"]


def test_start_runs_a_job_whose_plist_has_no_run_at_load(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch, run_at_load=False)
    service().start()
    assert fake.read()["running"] is True


def test_start_clears_a_disabled_override_before_bootstrapping(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch, disabled=True)
    service().start()
    assert fake.read()["loaded"] is True
    assert fake.verbs()[:2] == ["enable", "bootstrap"]


def test_a_transient_bootstrap_error_is_retried(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch, bootstrap_failures=2)
    service().start()
    assert fake.read()["running"] is True
    assert fake.verbs().count("bootstrap") == 3


def test_a_bootstrap_launchd_keeps_refusing_is_reported_not_hidden(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch, bootstrap_failures=99)
    with pytest.raises(ue.UpdateError, match="bootstrap refused 5 times"):
        service().start()
    assert fake.verbs().count("bootstrap") == 5
    assert "kickstart" not in fake.verbs()


def test_stop_waits_until_launchd_has_finished_tearing_the_job_down(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch, loaded=True, running=True, teardown_prints=4)
    service().stop()
    assert fake.read()["loaded"] is False


def test_stop_of_a_job_that_is_not_loaded_does_nothing(tmp_path, monkeypatch):
    fake = FakeLaunchctl(tmp_path, monkeypatch)
    service().stop()
    assert fake.verbs() == []


def test_a_crash_looping_job_is_unloaded_and_loaded_clean_by_stop_then_start(tmp_path, monkeypatch):
    """A bad release leaves a KeepAlive job loaded and throttled. A bootstrap onto it fails with
    'Input/output error' (the fake refuses a second load), so the rollback only works because it stops first."""
    fake = FakeLaunchctl(tmp_path, monkeypatch, loaded=True, running=False)
    svc = service()
    svc.stop()
    svc.start()
    state = fake.read()
    assert state["loaded"] and state["running"]
    assert fake.verbs() == ["bootout", "enable", "bootstrap", "kickstart"]


def test_a_launchctl_that_cannot_run_is_an_update_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ue.LaunchdService, "LAUNCHCTL", str(tmp_path / "missing"))
    with pytest.raises(ue.UpdateError, match="launchctl could not run"):
        service().start()
    with pytest.raises(ue.UpdateError, match="launchctl could not run"):
        service().stop()


# --- the engine's switch and rollback through the real LaunchdService ---------------------------


def bad_then_good(versions):
    """Readiness that fails for the new version and answers for the old one."""
    def readiness(cfg, version, started):
        return (version == versions["good"], f"version {version} " + ("healthy" if version == versions["good"] else "crash-looping"))
    return readiness


def test_a_release_that_crash_loops_under_launchd_is_rolled_back_and_the_old_version_runs(tmp_path, monkeypatch, cfg):
    fake = FakeLaunchctl(tmp_path, monkeypatch, loaded=True, running=True)
    old, new = installed(cfg, tmp_path)
    set_marker(cfg, "written by 1.1.0")

    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service=service(), readiness=bad_then_good({"good": "1.1.0"}), blockers=no_blockers)

    state = fake.read()
    assert state["loaded"] and state["running"]  # the old version is up
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert marker(cfg) == [("written by 1.1.0",)]
    last = ue.load_state(cfg)["last"]
    assert last["outcome"] == "rolled_back" and "crash-looping" in last["detail"]
    assert ue.load_state(cfg)["tx"] is None
    # stop (bootout) came before every load, so launchd never saw a bootstrap onto a loaded job
    verbs = fake.verbs()
    assert verbs.count("bootout") == 2 and verbs.count("bootstrap") == 2


def test_the_rollback_still_starts_the_old_version_when_the_new_one_left_the_job_throttled(tmp_path, monkeypatch, cfg):
    """The new version's job exists but is not running (launchd throttling a crash loop). apply() stops it
    (bootout) and the rollback loads the old version cleanly rather than kickstarting a poisoned job."""
    fake = FakeLaunchctl(tmp_path, monkeypatch, loaded=True, running=True, teardown_prints=3)
    old, new = installed(cfg, tmp_path)
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service=service(), readiness=bad_then_good({"good": "1.1.0"}), blockers=no_blockers)
    assert fake.read()["running"] is True
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
