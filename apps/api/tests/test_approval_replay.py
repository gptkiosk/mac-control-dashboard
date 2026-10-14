"""A task approval is single-use and bound to its card, route pin, nonce and expiry.

Each scenario uses the real API and dispatcher with a synthetic short-lived runner process.
No provider, credential or live service is involved.
"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

import approval
from dispatcher import Dispatcher
from models import Card, Run, RunEvent
from .test_dispatcher import SUCCESS, _drain, _registry, _settings

# A runnable synthetic program whose text trips the "deploys or releases" approval rule.
BODY = SUCCESS + "  # deploy the release"


def _setup(make_client, tmp_path):
    client = make_client()
    card = client.post("/api/cards", json={"title": "Release", "body": BODY, "agent": "claude",
                                           "working_dir": str(tmp_path / "ws" / "proj")}).json()
    assert card["needs_approval"] and card["approval_challenge"] and card["approval_pin"]
    sessions = client.app.state.sessions
    with sessions.begin() as s:
        s.get(Card, card["id"]).agent = "fake"  # route the synthetic runner; reviewed below
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    return client, sessions, d, card["id"]


def _shown(client, cid):
    view = client.get(f"/api/cards/{cid}").json()
    return {"challenge": view["approval_challenge"], "pin": view["approval_pin"]}


def _runs(sessions, cid):
    with sessions() as s:
        return list(s.scalars(select(Run).where(Run.card_id == cid)))


def _audit(sessions, cid):
    with sessions() as s:
        return approval.load_grant(s.get(Card, cid)).get("audit", [])


def test_single_legitimate_approval_dispatches_once(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    approved = client.post(f"/api/cards/{cid}/approve", json=shown)
    assert approved.status_code == 200 and approved.json()["column"] == "queued"
    assert approved.json()["approval_challenge"] is None
    asyncio.run(_drain(d))
    runs = _runs(sessions, cid)
    assert [r.stage for r in runs] == ["succeeded"]
    with sessions() as s:
        notes = [e.text for e in s.scalars(select(RunEvent).where(RunEvent.run_id == runs[0].id))]
        card = s.get(Card, cid)
        assert card.column == "done" and card.approved_at is None  # the grant is spent
        assert approval.load_grant(card)["last"]["run_id"] == runs[0].id
    assert any("bound to this run" in n and shown["pin"][:12] in n for n in notes)


def test_replayed_approval_request_is_refused_and_audited(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 200
    # Replay before the run: the nonce is already spent.
    replay = client.post(f"/api/cards/{cid}/approve", json=shown)
    assert replay.status_code == 409 and "already used" in replay.json()["detail"]
    asyncio.run(_drain(d))
    # Replay after the run, then try to rerun the card on the old approval.
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 409
    moved = client.patch(f"/api/cards/{cid}", json={"column": "queued"}).json()
    assert moved["column"] == "review" and moved["approved_at"] is None
    asyncio.run(_drain(d))
    assert len(_runs(sessions, cid)) == 1
    events = [a["event"] for a in _audit(sessions, cid)]
    assert events.count("refused") == 2 and events.count("used") == 1
    # Missing nonce or pin is refused too.
    assert client.post(f"/api/cards/{cid}/approve").status_code == 409
    assert client.post(f"/api/cards/{cid}/approve", json={"pin": shown["pin"]}).status_code == 409


def test_used_grant_forced_back_to_queued_is_refused_at_claim(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid))
    assert d._claim(1)  # the claim binds the grant to its run
    with sessions() as s:
        card = s.get(Card, cid)
        used_grant, used_at = card.approval_grant, card.approved_at
        assert approval.load_grant(card)["run_id"] is not None
    # The server dies before spawning; the used grant is forced back to Queued, bypassing the API.
    with sessions.begin() as s:
        card = s.get(Card, cid)
        card.approval_grant, card.approved_at, card.column = used_grant, used_at, "queued"
    assert asyncio.run(d.tick()) == 0
    with sessions() as s:
        assert s.get(Card, cid).column == "review"
    assert len(_runs(sessions, cid)) == 1
    assert "already used by run" in _audit(sessions, cid)[-1]["reason"]


def test_route_swap_before_approval_is_refused(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    # The route changes after the operator looked, through a path that is not a card edit.
    with sessions.begin() as s:
        s.get(Card, cid).model = "swapped-model"
    refused = client.post(f"/api/cards/{cid}/approve", json=shown)
    assert refused.status_code == 409 and "changed" in refused.json()["detail"]
    assert _audit(sessions, cid)[-1]["reason"] == "route or content changed since it was shown"
    with sessions() as s:
        assert s.get(Card, cid).approved_at is None
    # An edit through the API rotates the nonce, so the earlier view cannot approve either.
    client.patch(f"/api/cards/{cid}", json={"model": "other-model"})
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 409


def test_route_swap_after_approval_never_dispatches(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    assert client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid)).status_code == 200
    with sessions.begin() as s:
        s.get(Card, cid).model = "swapped-model"  # e.g. a direct DB or non-edit route change
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, cid) == []
    with sessions() as s:
        card = s.get(Card, cid)
        assert (card.column, card.approved_at) == ("review", None)
    last = _audit(sessions, cid)[-1]
    assert (last["event"], last["reason"]) == ("dispatch_refused", "route or content changed since approval")
    # The operator approves the new route explicitly; it then runs once on that route.
    assert client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid)).status_code == 200
    asyncio.run(_drain(d))
    runs = _runs(sessions, cid)
    assert [(r.stage, r.model_requested) for r in runs] == [("succeeded", "swapped-model")]


def test_approval_cannot_be_moved_to_another_card(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    other = client.post("/api/cards", json={"title": "Other", "body": BODY, "agent": "claude",
                                            "working_dir": str(tmp_path / "ws" / "proj")}).json()
    refused = client.post(f"/api/cards/{other['id']}/approve", json=_shown(client, cid))
    assert refused.status_code == 409
    # Copying an approved grant onto another card does not authorize it either.
    client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid))
    with sessions.begin() as s:
        a, b = s.get(Card, cid), s.get(Card, other["id"])
        b.agent, b.approval_grant, b.approved_at, b.column = "fake", a.approval_grant, a.approved_at, "queued"
        a.column = "backlog"
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, other["id"]) == []
    assert _audit(sessions, other["id"])[-1]["event"] == "dispatch_refused"


def test_expired_approval_is_refused_at_claim(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    with sessions.begin() as s:
        card = s.get(Card, cid)
        approval.grant(card, approval.challenge(card), approval.route_pin(card), int(time.time()) - 120, 60)
        card.column = "queued"
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, cid) == []
    assert _audit(sessions, cid)[-1]["reason"] == "approval expired before dispatch"


def test_legacy_approval_without_grant_needs_a_fresh_review(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    with sessions.begin() as s:  # a card approved before grants existed
        card = s.get(Card, cid)
        card.approval_grant, card.approved_at, card.column = None, int(time.time()), "queued"
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, cid) == []
    with sessions.begin() as s:  # and one waiting in Review with no challenge yet
        card = s.get(Card, cid)
        card.approval_grant, card.approved_at = None, None
    assert client.post(f"/api/cards/{cid}/approve", json={"challenge": "x", "pin": "y"}).status_code == 409
    assert client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid)).status_code == 200
