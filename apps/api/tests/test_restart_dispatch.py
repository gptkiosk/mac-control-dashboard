"""A human approval dispatches exactly once, whatever instant the server dies."""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select

import approval
import cards
from dispatcher import Dispatcher
from models import Card, Run
from .test_dispatcher import SUCCESS, _card, _drain, _registry, _settings

HOST = Path(__file__).with_name("crash_host.py")


def _marker_body(marker, sleep):
    return (f"import os,time;open({str(marker)!r},'a').write(str(os.getpid())+chr(10));"
            f"time.sleep({sleep})")


def _approved(sessions, tmp_path, body, **kw):
    cid = _card(sessions, tmp_path, body, column="review", **kw)
    with sessions.begin() as s:
        card = s.get(Card, cid)
        card.needs_approval = True
        approval.issue_challenge(card)
        # The human decision, committed before any dispatch, for the version that was shown.
        cards.approve(card, approval.challenge(card), approval.route_pin(card), 3600)
        assert card.column == "queued"
    return cid


def _alive(pid):
    # A killed child that nobody has reaped yet is a zombie: it is gone for every purpose here.
    import psutil
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_crash_after_decision_before_claim_dispatches_once(sessions, tmp_path):
    marker = tmp_path / "dispatches"
    cid = _approved(sessions, tmp_path, _marker_body(marker, 0), model="pinned-model")
    # The first server died right after the decision commit; two replacements start together.
    workers = [Dispatcher(sessions, _settings(tmp_path), registry=_registry()) for _ in range(2)]
    for w in workers:
        w.recover("restart")
    for w in workers:
        asyncio.run(_drain(w))
    with sessions() as s:
        runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
    assert len(runs) == 1 and runs[0].model_requested == "pinned-model"
    assert len(marker.read_text().splitlines()) == 1


def test_crash_after_claim_before_spawn_never_spawns(sessions, tmp_path):
    marker = tmp_path / "dispatches"
    cid = _approved(sessions, tmp_path, _marker_body(marker, 0), model="pinned-model")
    claimed = Dispatcher(sessions, _settings(tmp_path), registry=_registry())._claim(1)
    assert len(claimed) == 1  # committed Run row; the process died before create_subprocess_exec
    restarted = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert restarted.recover("restart") == 1
    assert asyncio.run(restarted.tick()) == 0
    with sessions() as s:
        runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
        assert [r.stage for r in runs] == ["interrupted"] and runs[0].model_requested == "pinned-model"
        assert s.get(Card, cid).column == "failed"
    assert not marker.exists()


def test_sigkilled_server_leaves_no_runner_to_duplicate(sessions, tmp_path):
    marker = tmp_path / "dispatches"
    cid = _approved(sessions, tmp_path, _marker_body(marker, 60), model="pinned-model")
    host = subprocess.Popen([sys.executable, "-I", str(HOST), str(tmp_path / "test.db"), str(tmp_path)])
    runner = None
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if marker.exists() and marker.read_text().strip():
                with sessions() as s:
                    if s.scalar(select(Run.pid).where(Run.card_id == cid)):
                        break
            time.sleep(0.05)
        runner = int(marker.read_text().split()[0])
        host.kill()  # SIGKILL: no shutdown handler runs
        host.wait()
        assert _alive(runner)  # the runner outlives its server, as in production
        with sessions() as s:
            assert s.scalar(select(Run.pid).where(Run.card_id == cid)) == runner
        restarted = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
        assert restarted.recover("service started; the run was cut off by a restart") == 1
        for _ in range(100):
            if not _alive(runner):
                break
            time.sleep(0.05)
        assert not _alive(runner)
        assert asyncio.run(restarted.tick()) == 0
        with sessions() as s:
            runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
            assert len(runs) == 1 and runs[0].stage == "interrupted"
            assert runs[0].model_requested == "pinned-model"
            assert s.get(Card, cid).column == "failed"
        assert len(marker.read_text().splitlines()) == 1
    finally:
        if host.poll() is None:
            host.kill()
        if runner and _alive(runner):
            os.killpg(runner, 9)


def test_recovery_ignores_a_reused_pid(sessions, tmp_path):
    bystander = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
    try:
        cid = _card(sessions, tmp_path, SUCCESS, column="running")
        with sessions.begin() as s:
            s.add(Run(card_id=cid, agent="fake", stage="running", started_at=int(time.time()),
                      working_dir=str(tmp_path), command='["/bin/not-the-bystander"]', log_path="",
                      pid=bystander.pid))
        assert Dispatcher(sessions, _settings(tmp_path), registry=_registry()).recover("restart") == 1
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()
