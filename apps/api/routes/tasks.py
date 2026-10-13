"""Task board API: agents, working directories, cards, runs and run logs."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

import approval
import cards as card_rules
import projects
import run_liveness
from agents import REGISTRY
from deps import get_session
from dispatcher import remove_run_logs
from models import Card, CardDependency, ChatThread, Run, RunEvent
from settings import get_settings

router = APIRouter(prefix="/api")


class CardIn(BaseModel):
    title: str = Field(max_length=200)
    body: str = Field(default="", max_length=100_000)
    assignee_type: str = "agent"
    agent: str | None = None
    working_dir: str | None = None
    mode: str = "read"
    priority: str = "normal"
    due_date: str | None = None
    estimate_minutes: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    acceptance: str | None = Field(default=None, max_length=20_000)
    depends_on: list[int] = Field(default_factory=list, max_length=50)
    model: str | None = None
    agent_target: str | None = None
    timeout_s: int | None = Field(default=None, ge=30, le=6 * 3600)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_backoff_s: int | None = Field(default=None, ge=0, le=3600)
    budget_usd: float | None = Field(default=None, ge=0.01, le=50.0)


class CardPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=100_000)
    assignee_type: str | None = None
    priority: str | None = None
    due_date: str | None = None
    estimate_minutes: int | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    acceptance: str | None = Field(default=None, max_length=20_000)
    agent: str | None = None
    working_dir: str | None = None
    mode: str | None = None
    model: str | None = None
    agent_target: str | None = None
    timeout_s: int | None = Field(default=None, ge=30, le=6 * 3600)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_backoff_s: int | None = Field(default=None, ge=0, le=3600)
    budget_usd: float | None = Field(default=None, ge=0.01, le=50.0)
    column: str | None = None
    position: float | None = None


def _run_dict(r: Run) -> dict:
    return {
        "id": r.id, "card_id": r.card_id, "agent": r.agent, "stage": r.stage,
        "model_requested": r.model_requested, "model_reported": r.model_reported,
        "provider": r.provider, "started_at": r.started_at, "ended_at": r.ended_at,
        "duration_s": r.duration_s, "exit_code": r.exit_code, "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens, "cost_usd": r.cost_usd, "session_id": r.session_id,
        "working_dir": r.working_dir, "command": json.loads(r.command), "error": r.error,
        "result_text": r.result_text,
        "cancel_requested": bool(json.loads(r.checkpoint or "{}").get("cancel_requested")),
        "quarantined": bool(json.loads(r.checkpoint or "{}").get("quarantine")),
    }


class DependencyIn(BaseModel):
    depends_on_id: int


def _dependency_maps(s: Session, card_ids: list[int]) -> tuple[dict, dict, dict]:
    """depends_on, blocked_by (dependencies not Done) and dependents, keyed by card id."""
    if not card_ids:
        return {}, {}, {}
    rows = s.execute(select(CardDependency.card_id, CardDependency.depends_on_id, Card.column)
                     .join(Card, Card.id == CardDependency.depends_on_id)
                     .where(or_(CardDependency.card_id.in_(card_ids),
                                CardDependency.depends_on_id.in_(card_ids)))).all()
    depends_on: dict[int, list[int]] = {}
    blocked_by: dict[int, list[int]] = {}
    dependents: dict[int, list[int]] = {}
    for card_id, dep_id, dep_column in rows:
        depends_on.setdefault(card_id, []).append(dep_id)
        if dep_column != "done":
            blocked_by.setdefault(card_id, []).append(dep_id)
        dependents.setdefault(dep_id, []).append(card_id)
    return depends_on, blocked_by, dependents


def _card_dict(c: Card, last_run: Run | None = None, deps: tuple[dict, dict, dict] | None = None, project=None, superseded_by: int | None = None) -> dict:
    depends_on, blocked_by, dependents = deps or ({}, {}, {})
    return {
        "project": {"id":project.project_id,"node_key":project.node_key,"role":project.role} if project else None,
        "superseded_by": superseded_by,
        "id": c.id, "title": c.title, "body": c.body, "agent": c.agent,
        "assignee_type": c.assignee_type, "priority": c.priority, "due_date": c.due_date,
        "estimate_minutes": c.estimate_minutes, "tags": json.loads(c.tags) if c.tags else [],
        "acceptance": c.acceptance,
        "depends_on": sorted(depends_on.get(c.id, [])), "blocked_by": sorted(blocked_by.get(c.id, [])),
        "dependents": sorted(dependents.get(c.id, [])),
        "agent_target": c.agent_target, "model": c.model, "mode": c.mode,
        "working_dir": c.working_dir, "column": c.column, "position": c.position,
        "timeout_s": c.timeout_s, "max_attempts": c.max_attempts,
        "retry_backoff_s": c.retry_backoff_s, "retry_after": c.retry_after,
        "retry_attempts": c.retry_attempts, "budget_usd": c.budget_usd,
        "needs_approval": c.needs_approval,
        "approval_reasons": json.loads(c.approval_reasons) if c.approval_reasons else [],
        "approved_at": c.approved_at, "created_by": c.created_by,
        # Echoed back by the approve request so it applies only to this exact version, once.
        "approval_challenge": approval.challenge(c),
        "approval_pin": approval.route_pin(c) if c.needs_approval else None,
        "approval_audit": approval.load_grant(c).get("audit", [])[-5:],
        "created_at": c.created_at, "updated_at": c.updated_at,
        "last_run": _run_dict(last_run) if last_run else None,
    }


def _get_card(s: Session, card_id: int) -> Card:
    card = s.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _last_runs(s: Session, card_ids: list[int]) -> dict[int, Run]:
    if not card_ids:
        return {}
    sub = (select(Run.card_id, func.max(Run.id).label("rid"))
           .where(Run.card_id.in_(card_ids)).group_by(Run.card_id).subquery())
    rows = s.execute(select(Run).join(sub, Run.id == sub.c.rid)).scalars().all()
    return {r.card_id: r for r in rows}


# ----------------------------------------------------------------------------- agents


@router.get("/agents")
def list_agents(request: Request, s: Session = Depends(get_session)):
    settings = get_settings()
    import native_routes
    native = native_routes.read(settings)
    collector = request.app.state.collector
    sub = (collector.subagents if collector else None) or {}
    now = int(time.time())
    out = []
    for spec in REGISTRY.values():
        runs = s.execute(select(Run).where(Run.agent == spec.id, or_(Run.started_at >= now - 86400, Run.stage == "running")).order_by(Run.id.desc())).scalars().all()
        day = [r for r in runs if r.started_at >= now - 86400]
        running = [r for r in runs if r.stage == "running"]
        current = []
        unresponsive = []
        for r in running:
            live = run_liveness.check(r, settings.run_quiet_after_s, now)
            if not live.running:  # the row says running but the runner is gone: never show it as running
                unresponsive.append({"run_id": r.id, "card_id": r.card_id, "thread_id": r.thread_id,
                                     "since_s": now - r.started_at, "liveness": live.as_dict()})
                continue
            card = s.get(Card, r.card_id) if r.card_id else None
            thread = s.get(ChatThread, r.thread_id) if r.thread_id else None
            current.append({"run_id": r.id, "card_id": r.card_id, "title": card.title if card else thread.title if thread else None, "thread_id": r.thread_id,
                            "model": r.model_reported or r.model_requested,
                            "running_s": now - r.started_at, "liveness": live.as_dict()})
        last = s.scalar(select(Run).where(Run.agent == spec.id).order_by(Run.id.desc()).limit(1))

        def total(attr: str, rows=day):
            vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
            return round(sum(vals), 4) if vals else None

        out.append({
            "id": spec.id, "name": spec.name, "role": spec.role,
            "available": spec.available(settings), "binary": spec.binary(settings),
            "default_model": native.get(spec.id, {}).get('default') or spec.default_model(),
            "suggested_models": list(dict.fromkeys([*spec.suggested_models, *native.get(spec.id, {}).get('models', [])])),
            "enforces_mode": spec.enforces_mode, "notes": spec.notes,
            "current": current,
            "unresponsive": unresponsive,
            "last_run": _run_dict(last) if last else None,
            "runs_24h": len(day),
            "failed_24h": sum(1 for r in day if r.stage in ("failed", "timeout", "interrupted")),
            "input_tokens_24h": total("input_tokens"),
            "output_tokens_24h": total("output_tokens"),
            "cost_usd_24h": total("cost_usd"),
            "busy_s_24h": total("duration_s"),
            "subagents": sub.get(spec.id),
        })
    return {"agents": out, "subagents_checked_at": sub.get("checked_at"), "checked_at": now}


@router.get("/workdirs")
def workdirs():
    """Allowed roots and their immediate subfolders, with the current git branch."""
    settings = get_settings()
    out = []
    for root in settings.workdir_roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for path in [root, *sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))]:
            out.append({"path": str(path), "branch": approval.current_branch(path), "root": str(root)})
    return {"workdirs": out}


# ----------------------------------------------------------------------------- cards


def _actor(request: Request) -> str:
    """Attribution only (not authorization): the MCD tool server marks Hermes-made tasks."""
    return "hermes" if request.headers.get("x-mcd-actor", "").lower() == "hermes" else "operator"


def _one(s: Session, card: Card) -> dict:
    last = _last_runs(s, [card.id]).get(card.id)
    return _card_dict(card, last, _dependency_maps(s, [card.id]), projects.binding(s,card.id), projects.superseded_by(s, card))


@router.get("/cards")
def list_cards(s: Session = Depends(get_session)):
    cards = s.execute(select(Card).order_by(Card.column, Card.position, Card.id)).scalars().all()
    ids = [c.id for c in cards]
    last = _last_runs(s, ids)
    deps = _dependency_maps(s, ids)
    return {"cards": [_card_dict(c, last.get(c.id), deps, (link := projects.binding(s,c.id)), projects.superseded_by(s, c, link)) for c in cards]}


@router.get("/tags")
def list_tags(s: Session = Depends(get_session)):
    counts: dict[str, int] = {}
    for raw in s.execute(select(Card.tags).where(Card.tags.is_not(None))).scalars():
        for tag in json.loads(raw):
            counts[tag] = counts.get(tag, 0) + 1
    return {"tags": [{"tag": t, "count": n} for t, n in sorted(counts.items())]}


@router.post("/cards", status_code=201)
def create_card(body: CardIn, request: Request, s: Session = Depends(get_session)):
    card = card_rules.create(s, body.model_dump(), get_settings(), created_by=_actor(request))
    s.commit()
    return _one(s, card)


@router.post("/cards/{card_id}/dependencies", status_code=201)
def add_dependency(card_id: int, body: DependencyIn, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    projects.protect(s, card)
    card_rules.add_dependency(s, card, body.depends_on_id)
    s.commit()
    return _one(s, card)


@router.delete("/cards/{card_id}/dependencies/{depends_on_id}")
def remove_dependency(card_id: int, depends_on_id: int, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    projects.protect(s, card)
    card_rules.remove_dependency(s, card, depends_on_id)
    s.commit()
    return _one(s, card)


@router.get("/cards/{card_id}")
def get_card(card_id: int, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    runs = s.execute(select(Run).where(Run.card_id == card_id).order_by(Run.id.desc())).scalars().all()
    data = _card_dict(card, runs[0] if runs else None, _dependency_maps(s, [card_id]), projects.binding(s,card.id), projects.superseded_by(s, card))
    data["runs"] = [_run_dict(r) for r in runs]
    return data


@router.patch("/cards/{card_id}")
def patch_card(card_id: int, body: CardPatch, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    data = body.model_dump(exclude_unset=True)
    column, position = data.pop("column", None), data.pop("position", None)
    if data:
        card_rules.edit(s, card, data, get_settings())
    if column is not None:
        card_rules.move(s, card, column, position)
    elif position is not None and card.column != "running":
        card.position = position
    s.commit()
    return _one(s, card)


class ApproveIn(BaseModel):
    model_config = {"extra": "forbid"}
    challenge: str | None = Field(default=None, max_length=64)
    pin: str | None = Field(default=None, max_length=64)


@router.post("/cards/{card_id}/approve")
def approve_card(card_id: int, body: ApproveIn | None = None, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    projects.protect(s, card)
    body = body or ApproveIn()
    try:
        card = card_rules.approve(card, body.challenge, body.pin, get_settings().approval_ttl_s)
    except approval.ApprovalRefused as exc:
        s.commit()  # keep the audit entry for the refused request
        raise HTTPException(status_code=409, detail=exc.detail) from None
    s.commit()
    return _one(s, card)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, s: Session = Depends(get_session)):
    card = _get_card(s, card_id)
    if card.column == "running":
        raise HTTPException(status_code=409, detail="Cancel the run before deleting the card.")
    sibling = projects.superseded_by(s, card)
    if sibling is None:
        projects.protect(s, card)
    else:
        projects.forget_duplicate(s, card, sibling)
    # Runs go with the card (ON DELETE CASCADE); remove their log files too, or they would
    # never be pruned (retention walks runs, and these runs no longer exist).
    log_paths = s.execute(select(Run.log_path).where(Run.card_id == card_id)).scalars().all()
    s.delete(card)
    s.commit()
    remove_run_logs(log_paths)


# ----------------------------------------------------------------------------- runs


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request):
    dispatcher = request.app.state.dispatcher
    if dispatcher is None or not await dispatcher.cancel(run_id):
        raise HTTPException(status_code=409, detail="That run is not running.")
    return {"cancelled": run_id}


@router.get("/runs/{run_id}/events")
def run_events(run_id: int, s: Session = Depends(get_session)):
    events = s.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)).scalars().all()
    return {"events": [{"ts": e.ts, "kind": e.kind, "text": e.text} for e in events]}


@router.get("/runs/{run_id}/log")
def run_log(run_id: int, offset: int = Query(0, ge=0), s: Session = Depends(get_session)):
    """Tail the readable log from a byte offset. Poll with next_offset until done is true."""
    run = s.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    path = Path(run.log_path)
    text, next_offset = "", offset
    if path.is_file():
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(256 * 1024)
        text, next_offset = chunk.decode("utf-8", "replace"), offset + len(chunk)
    return {"text": text, "next_offset": next_offset, "done": run.stage != "running",
            "stage": run.stage}
