"""Update helpers left registered with launchd: found, reaped automatically, shown as housekeeping, and cleaned after hours when allowed."""
from __future__ import annotations

import calendar
import json
import time

import pytest

import maintenance as mt
import service_control as sc
import source_update as su
from tests.test_auth import secured  # noqa: F401
from tests.test_profiles import signed

BASE = "com.operator.mac-control"
NOW = calendar.timegm(time.strptime("2026-10-16 03:00:00", "%Y-%m-%d %H:%M:%S"))        # 03:00 UTC; local hour depends on the machine, so tests set the window explicitly


def helper_label(minutes_ago, h="9e3df7"):
    ts = time.strftime("%Y%m%dt%H%M%Sz", time.gmtime(NOW - minutes_ago * 60))
    return f"{BASE}.source-update.{ts}.{h}"


class Launchd:
    """A stand-in for launchctl: `list` shows the labels it was given; `remove` forgets them."""

    def __init__(self, labels, remove_code=0):
        self.labels, self.calls, self.remove_code = list(labels), [], remove_code

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        if argv[:2] == ["launchctl", "list"]:
            return 0, "PID\tStatus\tLabel\n" + "\n".join(f"{62092 + i}\t-\t{l}" for i, l in enumerate(self.labels)) + f"\n-\t0\t{BASE}\n"
        if argv[:2] == ["launchctl", "remove"]:
            if self.remove_code == 0:
                self.labels = [l for l in self.labels if l != argv[2]]
            return self.remove_code, "" if self.remove_code == 0 else "Boot-out failed: 3: No such process"
        if argv[:2] == ["launchctl", "bootout"] and self.remove_code != 0:
            return self.remove_code, "Boot-out failed: 3: No such process"
        return 0, ""


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(su, "operation_active", lambda d: False)


# ------------------------------------------------------------------------------------------------ finding stale helpers
def test_only_old_helpers_of_this_installation_with_no_update_running_are_stale(tmp_path, monkeypatch):
    run = Launchd([helper_label(60), helper_label(5, "aaaaaa"), "com.operator.other.source-update.20261016t020000z.9e3df7", "com.operator.backup"])
    found = su.stale_helpers(tmp_path, BASE, NOW, run)
    assert [h["label"] for h in found] == [helper_label(60)] and found[0]["age_hours"] == 1.0 and found[0]["pid"] == 62092
    monkeypatch.setattr(su, "operation_active", lambda d: True)
    assert su.stale_helpers(tmp_path, BASE, NOW, run) == []                          # an update is running: touch nothing
    monkeypatch.setattr(su, "operation_active", lambda d: False)
    assert su.stale_helpers(tmp_path, BASE, NOW, lambda a, t=30: (1, "")) == []        # launchctl failed: nothing is guessed


def test_reaping_removes_stale_helpers_with_the_command_that_works_and_leaves_the_rest(tmp_path):
    run = Launchd([helper_label(120), helper_label(180, "bbbbbb"), helper_label(3, "cccccc")])
    removed = su.reap_helpers(tmp_path, BASE, NOW, run)
    assert sorted(removed) == sorted([helper_label(120), helper_label(180, "bbbbbb")])
    assert run.labels == [helper_label(3, "cccccc")]
    assert ["launchctl", "remove", helper_label(120)] in run.calls and not any(c[1] == "bootout" for c in run.calls)


def test_a_helper_launchd_will_not_unload_is_reported_not_counted(tmp_path):
    run = Launchd([helper_label(120)], remove_code=3)
    assert su.reap_helpers(tmp_path, BASE, NOW, run) == []


# --------------------------------------------------------------------------------------------------------- housekeeping
def test_a_stale_helper_is_a_finding_and_applying_it_unloads_only_that_job(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    run = Launchd([helper_label(240)])
    monkeypatch.setattr(sc, "default_run", run)
    with sessions() as s:
        findings = mt.scan(s, tmp_path, NOW)
        helper = next(f for f in findings if f["kind"] == "stale_update_helper")
        assert helper["id"] == f"stale_update_helper:{helper_label(240)}" and helper["evidence"]["age_hours"] == 4.0 and "no update is running" in helper["reason"]
        out = mt.apply(s, tmp_path, [helper["id"]], "op", NOW)
    assert out == [{"id": helper["id"], "status": "applied"}] and run.labels == []
    with sessions() as s:
        assert [f for f in mt.scan(s, tmp_path, NOW) if f["kind"] == "stale_update_helper"] == []
        assert mt.apply(s, tmp_path, [helper["id"]], "op", NOW)[0]["status"] == "skipped"          # already gone: skipped, never forced


def test_no_helper_findings_off_a_mac(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "linux")
    monkeypatch.setattr(sc, "default_run", lambda a, t=30: (_ for _ in ()).throw(AssertionError("must not run launchctl")))
    with sessions() as s:
        assert [f for f in mt.scan(s, tmp_path, NOW) if f["kind"] == "stale_update_helper"] == []


def test_the_finding_id_pattern_accepts_helper_ids_and_nothing_loose():
    assert mt.FINDING_ID.match(f"stale_update_helper:{helper_label(60)}")
    for bad in ("stale_update_helper:", "stale_update_helper:x", "stale_update_helper:a b", "stale_update_helper:../../etc/passwd" + "x" * 20 + " ;"):
        assert not mt.FINDING_ID.match(bad)


# ------------------------------------------------------------------------------------------------------------ after hours
def settings_for(tmp_path, **kw):
    from settings import get_settings
    return get_settings().model_copy(update={"data_dir": tmp_path, "housekeeping_window_start_hour": 0, "housekeeping_window_end_hour": 23, **kw})


def test_after_hours_cleanup_is_off_by_default_and_only_runs_what_was_allowed(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    run = Launchd([helper_label(240)])
    monkeypatch.setattr(sc, "default_run", run)
    assert mt.auto_status(settings_for(tmp_path), NOW)["enabled"] is False
    assert mt.auto_tick(sessions, settings_for(tmp_path), NOW) is None and run.labels == [helper_label(240)]
    out = mt.auto_tick(sessions, settings_for(tmp_path, housekeeping_auto="stale_update_helper"), NOW)
    assert out["applied"] == 1 and run.labels == []
    audit = [json.loads(l) for l in (tmp_path / "maintenance" / "audit.jsonl").read_text().splitlines()] if (tmp_path / "maintenance" / "audit.jsonl").exists() else []
    assert audit == [] or audit[-1]["actor"] == "after-hours"


def test_it_runs_once_a_day_inside_the_window_and_records_what_it_did(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    run = Launchd([helper_label(240)])
    monkeypatch.setattr(sc, "default_run", run)
    s = settings_for(tmp_path, housekeeping_auto="stale_update_helper,not_a_kind")
    assert mt.auto_classes(s) == ["stale_update_helper"]                              # unknown kinds are ignored
    first = mt.auto_tick(sessions, s, NOW)
    assert first["applied"] == 1 and first["summary"] == "1 cleaned up, 0 skipped"
    assert mt.auto_tick(sessions, s, NOW + 3600) is None                              # already ran today
    status = mt.auto_status(s, NOW + 3600)
    assert status["enabled"] and status["last_run"] == NOW and status["last_applied"] == 1 and status["last_summary"] == "1 cleaned up, 0 skipped"
    assert (tmp_path / "maintenance" / "auto.json").stat().st_mode & 0o777 == 0o600
    again = mt.auto_tick(sessions, s, NOW + 86400 + 60)                                # the next day, nothing left to do
    assert again["summary"] == "nothing to clean up"


def test_outside_the_window_nothing_runs(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    monkeypatch.setattr(sc, "default_run", Launchd([helper_label(240)]))
    local_hour = time.localtime(NOW).tm_hour
    s = settings_for(tmp_path, housekeeping_auto="stale_update_helper", housekeeping_window_start_hour=(local_hour + 2) % 24, housekeeping_window_end_hour=(local_hour + 3) % 24)
    assert mt.auto_status(s, NOW)["in_window"] is False and mt.auto_tick(sessions, s, NOW) is None


def test_a_window_that_crosses_midnight_works():
    class S:
        housekeeping_window_start_hour, housekeeping_window_end_hour = 22, 5
    at = lambda h: calendar.timegm((2026, 10, 16, h, 0, 0)) - time.timezone + (3600 if time.daylight and time.localtime().tm_isdst else 0)
    hours = {h: mt._in_window(S, int(time.mktime((2026, 10, 16, h, 30, 0, 0, 0, -1)))) for h in range(24)}
    assert hours[23] and hours[0] and hours[4] and not hours[5] and not hours[12] and hours[22]


def test_the_housekeeping_route_shows_the_after_hours_status(secured):  # noqa: F811
    signed(secured)
    auto = secured.get("/api/maintenance").json()["auto"]
    assert auto["enabled"] is False and auto["classes"] == [] and "to" in auto["window"]


def test_the_collector_runs_the_housekeeping_loop():
    import collector
    assert hasattr(collector.Collector, "_housekeeping_loop")
