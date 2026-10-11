"""Queue worker that runs agent cards.

- At most `max_concurrent_runs` runs at a time; queued cards run in board order.
- A card runs only from the "queued" column, and only if it needs no approval or has been
  approved (checked here as well as in the API).
- Each run is its own process group (start_new_session) with stdin closed (Codex otherwise
  waits on stdin). Timeout and cancel signal the whole group: SIGTERM, then SIGKILL after 5 s.
- Output lines can be large (Claude stream-json carries tool results), so the reader limit is 16 MB.
- On startup and shutdown, runs still marked running are recorded as "interrupted" and their
  cards moved to Failed; queued cards stay queued and resume. Nothing is lost silently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
import signal
import time
from dataclasses import dataclass
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from sqlalchemy import and_, exists, or_, select, text
from sqlalchemy.orm import aliased
from sqlalchemy.orm import sessionmaker

from agents import REGISTRY, AgentSpec, redact
import projects
from models import Card, CardDependency, ChatMessage, ChatThread, Run, RunEvent

logger = logging.getLogger("mac_control.dispatcher")

LINE_LIMIT = 16 * 1024 * 1024
MAX_CHAT_TURNS = 2  # chat turns run beside board cards so a long card never blocks a conversation
CHAT_TIMEOUT_S = 900
KILL_GRACE_S = 5.0
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))


@dataclass
class _Handle:
    proc: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False


def _now() -> int:
    return int(time.time())


def remove_run_logs(log_paths) -> None:
    """Delete a run's readable and raw logs. Used wherever runs are deleted by cascade."""
    for log_path in log_paths:
        if not log_path:
            continue
        for path in (Path(log_path), Path(log_path).with_suffix(".raw.log")):
            path.unlink(missing_ok=True)


class Dispatcher:
    def __init__(self, sessions: sessionmaker, settings, registry: dict[str, AgentSpec] | None = None,
                 poll_s: float = 2.0) -> None:
        self.sessions = sessions
        self.settings = settings
        self.registry = registry if registry is not None else REGISTRY
        self.poll_s = poll_s
        self.runs_dir: Path = settings.runs_dir
        self.runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._handles: dict[int, _Handle] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._chat_tasks: dict[int, asyncio.Task] = {}
        self._chat_slots = asyncio.Semaphore(MAX_CHAT_TURNS)
        self._loop_task: asyncio.Task | None = None
        self._last_prune = 0.0

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.recover("service started; the run was cut off by a restart")
        self._loop_task = asyncio.create_task(self._loop(), name="dispatcher")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        for handle in list(self._handles.values()):
            await self._kill(handle)
        tasks = [*self._tasks.values(), *self._chat_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.recover("service stopped while the run was in progress")

    def recover(self, note: str) -> int:
        """Mark runs left in 'running' as interrupted and fail their cards."""
        now = _now()
        with self.sessions.begin() as s:
            stuck = s.execute(select(Run).where(Run.stage == "running")).scalars().all()
            for run in stuck:
                run.stage = "interrupted"
                run.ended_at = now
                run.duration_s = float(now - run.started_at)
                run.error = note
                s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text=f"interrupted: {note}"))
                if run.card_id is not None:
                    card = s.get(Card, run.card_id)
                    if card and card.column == "running":
                        card.column = "failed"
                        card.updated_at = now
            for msg in s.execute(select(ChatMessage).where(ChatMessage.status == "running")).scalars():
                msg.status = "failed"
                s.add(ChatMessage(thread_id=msg.thread_id, role="assistant", status="failed",
                                  text=f"(turn interrupted: {note})", created_at=now))
            return len(stuck)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
                if time.time() - self._last_prune > 3600:
                    self._last_prune = time.time()
                    await asyncio.to_thread(self.prune, _now())
            except Exception:
                logger.exception("dispatcher tick failed")
            await asyncio.sleep(self.poll_s)

    # ------------------------------------------------------------------ queue

    def _claim(self, limit: int) -> list[tuple[dict[str, Any], int]]:
        """Move up to `limit` runnable queued cards to running and create their Run rows."""
        claimed: list[tuple[dict[str, Any], int]] = []
        now = _now()
        blocker = aliased(Card)
        unfinished_dependency = exists().where(and_(
            CardDependency.card_id == Card.id,
            CardDependency.depends_on_id == blocker.id,
            blocker.column != "done",
        ))
        with self.sessions.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            projects.advance(s, self.settings)
            active_runs = list(s.scalars(select(Run).where(Run.stage == "running")))
            cards = s.execute(
                select(Card)
                .where(Card.column == "queued")
                .where(Card.assignee_type == "agent")
                .where(~unfinished_dependency)
                .where(or_(Card.needs_approval.is_(False), Card.approved_at.is_not(None)))
                .order_by(Card.position, Card.id)
            ).scalars().all()
            for card in cards:
                if len(claimed) >= limit: break
                link = projects.binding(s, card.id)
                if any((link or (r.card_id and projects.binding(s, r.card_id))) and projects.overlap(card.working_dir, r.working_dir) for r in active_runs):
                    continue
                # A named OpenClaw target has its own configured gateway workspace.
                # Keep its project conversations distinct and serialize work on that target.
                if card.agent=='openclaw' and any(r.agent=='openclaw' and
                    (link or (r.card_id and projects.binding(s,r.card_id))) and
                    ((s.get(Card,r.card_id) if r.card_id else s.get(ChatThread,r.thread_id)).agent_target or 'mm-main')==(card.agent_target or 'mm-main') for r in active_runs): continue
                prompt = projects.claim_context(s, card)
                if prompt is None: continue
                spec = self.registry.get(card.agent)
                if spec is None:
                    card.column, card.updated_at = "failed", now
                    continue
                model_requested = card.model or spec.default_model()
                card.subscription_billing=bool(link) and projects.subscription(s,card.agent)
                args=(card,prompt,card.model,card.budget_usd or self.settings.default_budget_usd,spec.binary(self.settings))
                resume=getattr(card,'resume_session',None)
                argv=spec.build(*args, session_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'mcd:story:{card.id}'))) if link and spec.preassigned_session else spec.build(*args,session_id=resume) if resume else spec.build(*args)
                run = Run(
                    card_id=card.id, agent=card.agent, model_requested=model_requested,
                    stage="running", started_at=now, working_dir=card.working_dir,
                    command=json.dumps(redact(argv, prompt)), log_path="",
                )
                s.add(run)
                s.flush()
                projects.bind_output_run(s,card,run.id)
                active_runs.append(run)
                if link and link.role == "story":
                    projects.memory(s, projects.get(s, link.project_id), "context", prompt, "mcd", card.id, run.id)
                run.log_path = str(self.runs_dir / f"run-{run.id}.log")
                s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text="running"))
                card.column, card.updated_at = "running", now
                claimed.append(({"id": card.id, "agent": card.agent, "working_dir": card.working_dir,
                                 "timeout_s": card.timeout_s, "argv": argv}, run.id))
        return claimed

    async def tick(self) -> int:
        free = self.settings.max_concurrent_runs - len(self._tasks)
        if free <= 0:
            return 0
        claimed = await asyncio.to_thread(self._claim, free)
        for card, run_id in claimed:
            self._handles[run_id] = _Handle()
            task = asyncio.create_task(self._execute(card, run_id), name=f"run-{run_id}")
            self._tasks[run_id] = task
            task.add_done_callback(lambda _t, rid=run_id: self._forget(rid))
        return len(claimed)

    def _forget(self, run_id: int) -> None:
        self._tasks.pop(run_id, None)
        self._handles.pop(run_id, None)

    # ------------------------------------------------------------------ execution

    @staticmethod
    def _env() -> dict[str, str]:
        env = dict(os.environ)
        env["PATH"] = ":".join((*EXTRA_PATH, env.get("PATH", "/usr/bin:/bin")))
        env.setdefault("HOME", str(Path.home()))
        return env

    async def _run_process(self, run_id: int, agent: str, argv: list[str], cwd: str,
                           timeout_s: int) -> tuple[str, int | None, str | None, Any, float]:
        """Spawn one agent process, stream its output to the run log, and classify the result.

        Shared by board cards and chat turns. Returns (stage, exit_code, error, meta, seconds).
        """
        spec = self.registry[agent]
        parser = spec.parser()
        handle = self._handles[run_id]
        log_path = self.runs_dir / f"run-{run_id}.log"
        raw_path = self.runs_dir / f"run-{run_id}.raw.log"
        started = time.monotonic()
        stage, exit_code, error = "failed", None, None
        quota_reported = False

        with open(log_path, "a", encoding="utf-8") as log, open(raw_path, "a", encoding="utf-8") as raw:
            def write(text: str) -> None:
                stamp = time.strftime("%H:%M:%S")
                for part in (text.splitlines() or [""]):
                    log.write(f"{stamp}  {part}\n")
                log.flush()

            async def pump(stream: asyncio.StreamReader, is_stderr: bool) -> None:
                nonlocal quota_reported
                while True:
                    line_b = await stream.readline()
                    if not line_b:
                        return
                    line = line_b.decode("utf-8", "replace").rstrip("\n")
                    raw.write(("! " if is_stderr else "") + line + "\n")
                    if is_stderr:
                        parser.feed_stderr(line)
                        quota_reported |= bool(re.search(r"usage limit|rate.?limit|quota exceeded|quota exhausted|too many requests|limit reached|HTTP.?429",line,re.I))
                        if line.strip():
                            write(f"! {line}")
                    else:
                        for out in parser.feed(line):
                            write(out)

            try:
                if agent == 'hermes':
                    from hermes_runtime import command
                    argv = command(argv)
                proc = await asyncio.create_subprocess_exec(
                    *argv, cwd=cwd, env=self._env(),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=LINE_LIMIT,
                )
            except (FileNotFoundError, PermissionError) as exc:
                error = f"could not start {spec.name}: {exc}"
                write(f"error: {error}")
                proc = None

            if proc is not None:
                handle.proc = proc
                assert proc.stdout is not None and proc.stderr is not None
                readers = asyncio.gather(pump(proc.stdout, False), pump(proc.stderr, True))
                try:
                    await asyncio.wait_for(asyncio.gather(readers, proc.wait()), timeout=timeout_s)
                    exit_code = proc.returncode
                    for out in parser.finish():
                        write(out)
                    with self.sessions() as db:
                        requested = db.get(Run, run_id).model_requested
                    if agent in {'hermes','openclaw'} and requested and parser.meta.model_reported and requested.removeprefix('openrouter/') != parser.meta.model_reported.removeprefix('openrouter/'):
                        parser.meta.error = 'Agent reported a different model than the MCD assignment. Review this run; no automatic reassignment was authorized.'
                        parser.meta.timed_out = False
                    if handle.cancel_requested:
                        stage, error = "cancelled", "cancelled by operator"
                    elif exit_code == 0 and parser.meta.error is None:
                        stage = "succeeded"
                    else:
                        stage = "timeout" if parser.meta.timed_out else "failed"
                        error = parser.meta.error or f"exit code {exit_code}"
                        if quota_reported: error += " (CLI reported a quota or rate limit)"
                except asyncio.TimeoutError:
                    await self._kill(handle)
                    readers.cancel()
                    exit_code = proc.returncode
                    stage, error = "timeout", f"MCD stopped the run after its {timeout_s} s time limit. Review any partial work before retrying."
                    write(f"error: {error}")
                except asyncio.CancelledError:
                    await self._kill(handle)
                    raise

        return stage, exit_code, error, parser.meta, time.monotonic() - started

    async def _execute(self, card: dict[str, Any], run_id: int) -> None:
        stage, exit_code, error, meta, seconds = await self._run_process(
            run_id, card["agent"], card["argv"], card["working_dir"], card["timeout_s"])
        await asyncio.to_thread(self._finish, run_id, card["id"], stage, exit_code, error, meta, seconds)

    @staticmethod
    def _record_run(s, run_id, stage, exit_code, error, meta, duration, now) -> Run | None:
        run = s.get(Run, run_id)
        if run is None:
            return None
        run.stage, run.exit_code, run.error = stage, exit_code, error
        run.ended_at, run.duration_s = now, round(duration, 2)
        for f in ("model_reported", "provider", "session_id", "input_tokens", "output_tokens",
                  "cost_usd", "cached_input_tokens", "cache_write_tokens", "result_text"):
            setattr(run, f, getattr(meta, f))
        s.add(RunEvent(run_id=run_id, ts=now, kind="stage", text=stage))
        return run

    def _finish(self, run_id, card_id, stage, exit_code, error, meta, duration) -> None:
        now = _now()
        with self.sessions.begin() as s:
            if self._record_run(s, run_id, stage, exit_code, error, meta, duration, now) is None:
                return
            card = s.get(Card, card_id)
            if card and card.column == "running":
                card.column = "done" if stage == "succeeded" else "failed"
                card.updated_at = now
                projects.on_finish(s, card, s.get(Run, run_id), stage)

    # ------------------------------------------------------------------ chat turns

    def thread_busy(self, thread_id: int) -> bool:
        return thread_id in self._chat_tasks

    def _claim_turn(self, message_id: int) -> tuple[dict[str, Any], int] | None:
        """Create the Run for an approved user message and mark it running."""
        now = _now()
        with self.sessions.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            msg = s.get(ChatMessage, message_id)
            if msg is None or msg.role != "user" or msg.status not in ("pending_approval", "running"):
                return None
            if msg.approval_reasons and msg.approved_at is None:
                return None  # second line of defence: never run an unapproved turn
            thread = s.get(ChatThread, msg.thread_id)
            spec = self.registry.get(thread.agent) if thread else None
            if thread is None or spec is None:
                return None
            active = list(s.scalars(select(Run).where(Run.stage == "running")))
            if any(r.card_id and projects.binding(s, r.card_id) and (projects.overlap(thread.working_dir, r.working_dir) or (thread.agent==r.agent=="openclaw" and (s.get(Card,r.card_id).agent_target or "mm-main")==(thread.agent_target or "mm-main"))) for r in active):
                return None
            ctx = SimpleNamespace(mode=thread.mode, working_dir=thread.working_dir,
                                  agent_target=thread.agent_target, timeout_s=CHAT_TIMEOUT_S)
            argv = spec.build(ctx, msg.text, thread.model, self.settings.default_budget_usd,
                              spec.binary(self.settings), session_id=thread.session_id)
            run = Run(thread_id=thread.id, agent=thread.agent,
                      model_requested=thread.model or spec.default_model(), stage="running",
                      started_at=now, working_dir=thread.working_dir,
                      command=json.dumps(redact(argv, msg.text)), log_path="")
            s.add(run)
            s.flush()
            run.log_path = str(self.runs_dir / f"run-{run.id}.log")
            s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text="running"))
            msg.status, msg.run_id = "running", run.id
            thread.last_activity_at = now
            return ({"thread_id": thread.id, "message_id": msg.id, "agent": thread.agent,
                     "working_dir": thread.working_dir, "argv": argv}, run.id)

    async def start_turn(self, message_id: int) -> int | None:
        """Run an approved user message. Returns the run id, or None if it may not run."""
        claimed = await asyncio.to_thread(self._claim_turn, message_id)
        if claimed is None:
            return None
        turn, run_id = claimed
        self._handles[run_id] = _Handle()
        task = asyncio.create_task(self._execute_turn(turn, run_id), name=f"turn-{run_id}")
        self._chat_tasks[turn["thread_id"]] = task
        task.add_done_callback(lambda _t, tid=turn["thread_id"], rid=run_id: self._forget_turn(tid, rid))
        return run_id

    def _forget_turn(self, thread_id: int, run_id: int) -> None:
        self._chat_tasks.pop(thread_id, None)
        self._handles.pop(run_id, None)

    async def _execute_turn(self, turn: dict[str, Any], run_id: int) -> None:
        async with self._chat_slots:
            stage, exit_code, error, meta, seconds = await self._run_process(
                run_id, turn["agent"], turn["argv"], turn["working_dir"], CHAT_TIMEOUT_S)
        await asyncio.to_thread(self._finish_turn, run_id, turn, stage, exit_code, error, meta, seconds)

    def _finish_turn(self, run_id, turn, stage, exit_code, error, meta, duration) -> None:
        now = _now()
        with self.sessions.begin() as s:
            self._record_run(s, run_id, stage, exit_code, error, meta, duration, now)
            msg = s.get(ChatMessage, turn["message_id"])
            thread = s.get(ChatThread, turn["thread_id"])
            if msg is None or thread is None:
                return
            msg.status = {"succeeded": "done", "cancelled": "cancelled"}.get(stage, "failed")
            reply = meta.result_text if stage == "succeeded" else f"({stage}: {error})"
            s.add(ChatMessage(
                thread_id=thread.id, role="assistant", text=reply or "(no reply)",
                status="done" if stage == "succeeded" else "failed", run_id=run_id,
                model=meta.model_reported or s.get(Run, run_id).model_requested,
                input_tokens=meta.input_tokens, output_tokens=meta.output_tokens,
                cost_usd=meta.cost_usd, duration_s=round(duration, 2), created_at=now,
            ))
            spec = self.registry.get(thread.agent)
            if thread.session_id is None and meta.session_id and spec and not spec.preassigned_session:
                thread.session_id = meta.session_id
            thread.last_activity_at = now

    # ------------------------------------------------------------------ control

    async def _kill(self, handle: _Handle) -> None:
        proc = handle.proc
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_S)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()

    async def cancel(self, run_id: int) -> bool:
        handle = self._handles.get(run_id)
        if handle is None:
            return False
        handle.cancel_requested = True
        await self._kill(handle)
        return True

    def is_running(self, run_id: int) -> bool:
        return run_id in self._tasks

    # ------------------------------------------------------------------ retention

    def prune(self, now: int) -> int:
        """Delete runs (and their log files) and idle chat threads past the retention window.

        Cards stay. Returns the number of runs removed.
        """
        cutoff = now - self.settings.run_retention_days * 86400
        with self.sessions.begin() as s:
            for thread in s.execute(select(ChatThread).where(ChatThread.last_activity_at < cutoff)).scalars():
                if thread.id not in self._chat_tasks:
                    remove_run_logs(s.execute(select(Run.log_path).where(Run.thread_id == thread.id)).scalars())
                    s.delete(thread)
            old = s.execute(select(Run).where(Run.started_at < cutoff, Run.stage != "running")).scalars().all()
            for run in old:
                remove_run_logs([run.log_path])
                s.delete(run)
            return len(old)
