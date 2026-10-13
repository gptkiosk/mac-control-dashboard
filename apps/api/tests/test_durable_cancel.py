"""An operator cancel survives a server crash: the runner stops, nothing respawns, and the run's
partial output is quarantined rather than accepted or deleted."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import select

from dispatcher import CANCEL_ERROR, LATE_CANCEL_ERROR, Dispatcher
from models import Card, Run, RunEvent
from routes.tasks import _run_dict
from agents import RunMeta
from .test_dispatcher import _card, _registry, _settings

HOST = Path(__file__).with_name("crash_host.py")


def _runner(marker, partial):
    # Records each spawn, leaves partial work in the workspace and output in the log, then waits.
    return (f"import os,time;open({str(marker)!r},'a').write(str(os.getpid())+chr(10));"
            f"open({str(partial)!r},'w').write('half done');"
            "print('partial-output',flush=True);time.sleep(60)")


def _alive(pid):
    # A killed child that nobody has reaped yet is a zombie: it is gone for every purpose here.
    import psutil
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _assert_cancelled_and_quarantined(sessions, tmp_path, cid):
    with sessions() as s:
        runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
        assert len(runs) == 1
        run = runs[0]
        assert run.stage == "cancelled" and run.error.startswith(CANCEL_ERROR)
        assert s.get(Card, cid).column == "failed"
        cp = json.loads(run.checkpoint)
        assert cp["cancel_requested"] is True and cp["publishable"] is False
        record = json.loads(Path(cp["quarantine"]).read_text())
        assert record["run_id"] == run.id and record["publishable"] is False
        assert Path(cp["quarantine"]).parent == tmp_path / "runs" / "quarantine"
        assert oct(Path(cp["quarantine"]).stat().st_mode & 0o777) == "0o600"
        events = [e.text for e in s.scalars(select(RunEvent).where(RunEvent.run_id == run.id))]
        assert "operator cancellation requested" in events
        assert any("quarantined" in text for text in events)
        assert _run_dict(run)["quarantined"] is True and _run_dict(run)["cancel_requested"] is True
        return run, record


def test_cancel_then_server_sigkill_then_restart(sessions, tmp_path):
    marker, partial = tmp_path / "spawns", tmp_path / "partial.txt"
    cid = _card(sessions, tmp_path, _runner(marker, partial), model="pinned-model")
    host = subprocess.Popen([sys.executable, "-I", str(HOST), str(tmp_path / "test.db"), str(tmp_path)])
    runner = None
    try:
        deadline = time.time() + 20
        run_id = None
        while time.time() < deadline:
            with sessions() as s:
                run = s.scalar(select(Run).where(Run.card_id == cid))
                if run and run.pid and Path(run.log_path).is_file() and "partial-output" in Path(run.log_path).read_text():
                    run_id = run.id
                    break
            time.sleep(0.05)
        assert run_id is not None
        runner = int(marker.read_text().split()[0])
        # The cancel is committed, then the server dies before it can signal the runner.
        assert asyncio.run(Dispatcher(sessions, _settings(tmp_path), registry=_registry()).cancel(run_id))
        host.kill()  # SIGKILL: only the Popen created by this test
        host.wait()
        assert _alive(runner)
        restarted = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
        assert restarted.recover("service started; the run was cut off by a restart") == 1
        for _ in range(100):
            if not _alive(runner):
                break
            time.sleep(0.05)
        assert not _alive(runner)
        assert asyncio.run(restarted.tick()) == 0  # nothing respawned
        assert len(marker.read_text().splitlines()) == 1
        run, record = _assert_cancelled_and_quarantined(sessions, tmp_path, cid)
        assert run.model_requested == "pinned-model"
        assert run.log_path in [e["path"] for e in record["evidence"]]
        assert "partial-output" in Path(run.log_path).read_text()  # kept, not deleted
        assert partial.read_text() == "half done"  # workspace untouched
    finally:
        if host.poll() is None:
            host.kill()
            host.wait()
        if runner and _alive(runner):
            os.killpg(runner, 9)


def test_cancel_recorded_runner_already_gone_restart_is_cancelled(sessions, tmp_path):
    cid = _card(sessions, tmp_path, "x", column="running")
    log = tmp_path / "runs" / "run-partial.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("partial-output\n")
    with sessions.begin() as s:
        s.add(Run(card_id=cid, agent="fake", stage="running", started_at=int(time.time()) - 5,
                  working_dir=str(tmp_path), command="[]", log_path=str(log),
                  checkpoint=json.dumps({"cancel_requested": True})))
        s.flush()
        s.add(RunEvent(run_id=s.scalar(select(Run.id)), ts=int(time.time()), kind="note",
                       text="operator cancellation requested"))
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert d.recover("restart") == 1
    assert asyncio.run(d.tick()) == 0
    _, record = _assert_cancelled_and_quarantined(sessions, tmp_path, cid)
    assert record["evidence"] == [{"path": str(log), "bytes": len("partial-output\n")}]


def test_result_after_cancel_is_quarantined_not_accepted(sessions, tmp_path):
    cid = _card(sessions, tmp_path, "x", column="running")
    with sessions.begin() as s:
        run = Run(card_id=cid, agent="fake", stage="running", started_at=int(time.time()),
                  working_dir=str(tmp_path), command="[]", log_path="")
        s.add(run)
        s.flush()
        run_id = run.id
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert d._record_cancel(run_id)
    d._finish(run_id, cid, "succeeded", 0, None, RunMeta(result_text="late result"), 1.0)
    with sessions() as s:
        run = s.get(Run, run_id)
        assert run.stage == "cancelled" and run.error == LATE_CANCEL_ERROR
        assert run.result_text == "late result"  # evidence kept
        assert s.get(Card, cid).column == "failed"
        assert json.loads(run.checkpoint)["publishable"] is False


def test_cancel_between_claim_and_spawn_never_spawns(sessions, tmp_path):
    marker, partial = tmp_path / "spawns", tmp_path / "partial.txt"
    cid = _card(sessions, tmp_path, _runner(marker, partial))
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())

    async def scenario():
        card, run_id = (await asyncio.to_thread(d._claim, 1))[0]
        assert await d.cancel(run_id)  # no handle yet: only the committed request
        from dispatcher import _Handle
        d._handles[run_id] = _Handle()
        await d._execute(card, run_id)

    asyncio.run(scenario())
    assert not marker.exists()
    _assert_cancelled_and_quarantined(sessions, tmp_path, cid)


def test_cancel_of_finished_run_is_refused(sessions, tmp_path):
    cid = _card(sessions, tmp_path, "x", column="done")
    with sessions.begin() as s:
        run = Run(card_id=cid, agent="fake", stage="succeeded", started_at=int(time.time()),
                  working_dir=str(tmp_path), command="[]", log_path="")
        s.add(run)
        s.flush()
        run_id = run.id
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert asyncio.run(d.cancel(run_id)) is False
    with sessions() as s:
        assert s.get(Run, run_id).checkpoint is None
