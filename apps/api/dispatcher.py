"""Queue worker that runs agent cards.

- At most `max_concurrent_runs` runs at a time; queued cards run in board order.
- A card runs only from the "queued" column, and only if it needs no approval or has been
  approved (checked here as well as in the API).
- Each run is its own process group (start_new_session) with stdin closed (Codex otherwise
  waits on stdin). Timeout and cancel signal the whole group: SIGTERM, then SIGKILL after 5 s.
- Output lines can be large (Claude stream-json carries tool results), so the reader limit is 16 MB.
- On startup and shutdown, runs still marked running are recorded as "interrupted" and their
  cards moved to Failed; queued cards stay queued and resume. Nothing is lost silently.
- The runner's pid is committed right after spawn. Runners outlive a crashed server (own session),
  so recovery first stops a surviving runner it can positively identify; a failed card is never
  left with live work behind it that a retry would duplicate.
- Cancellation is durable. The request is committed to the run's checkpoint before any signal,
  so a restart that finds it stops the runner and records the run as cancelled, never
  interrupted or requeued. A result that arrives after the request is recorded as cancelled too.
  A cancelled run's partial output is quarantined: kept for review, never published or deleted.
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

import psutil
from sqlalchemy import and_, exists, or_, select, text
from sqlalchemy.orm import aliased
from sqlalchemy.orm import sessionmaker

from agents import REGISTRY, AgentSpec, redact
import agent_git
import approval
import provider_limits
from dispatch_gate import (DispatchDenied, admit as admit_dispatch, resolve_free_alias,
                           snapshot as dispatch_snapshot, reviewed_route_class as _reviewed_route_class)
import projects
from idempotency import refuse_timeout_retry
from models import Card, CardDependency, ChatMessage, ChatThread, Run, RunEvent
from profiles import SAVED_KEY_AGENTS, saved_openrouter_key
from operator_boundary import runner_env

logger = logging.getLogger("mac_control.dispatcher")

LINE_LIMIT = 16 * 1024 * 1024
MAX_CHAT_TURNS = 2  # chat turns run beside board cards so a long card never blocks a conversation
CHAT_TIMEOUT_S = 900
KILL_GRACE_S = 5.0
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))
CANCEL_ERROR = "cancelled by operator"
LATE_CANCEL_ERROR = ("cancelled by operator; the runner returned a result after the cancel was "
                     "recorded, so it was quarantined rather than accepted")

# Deliberately narrow: only clear transport/provider-transient failures get automatic retries.
# Everything else remains an operator decision, even if a task has spare attempts.
TRANSIENT_ERROR = re.compile(r"(?:rate.?limit|too many requests|quota|temporar(?:y|ily)|"
                             r"service unavailable|connection (?:reset|timed out)|gateway timeout)", re.I)


@dataclass
class _Handle:
    proc: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False


SECRET_KEY = re.compile(r"sk-or-[A-Za-z0-9_\-]{12,}")


def scrub(text: str, key: str | None = None) -> str:
    """Remove OpenRouter keys from anything an agent printed before it is stored or shown."""
    if key:
        text = text.replace(key, "[redacted OpenRouter key]")
    return SECRET_KEY.sub("[redacted OpenRouter key]", text)


def _now() -> int:
    return int(time.time())


def _checkpoint(run: Run) -> dict[str, Any]:
    return json.loads(run.checkpoint or "{}")



def _runner_matches(expected: str, cmdline: list[str]) -> bool:
    """Does this process look like the executable recorded for the run? Launchers rewrite the first word:
    a symlink resolves, a macOS virtualenv Python re-launches as Python.app, and a script runs as
    `node <script>`. The group-leader and start-time checks in the caller keep this safe."""
    first = cmdline[0]
    if first == expected or expected in cmdline[1:3]:
        return True
    try:
        if os.path.realpath(first) == os.path.realpath(expected):
            return True
    except OSError:
        pass
    return os.path.basename(first).lower() == os.path.basename(expected).lower()


def _stop_orphan(run: Run) -> str | None:
    """Stop a runner left alive by a crashed server. Returns a note, or None if nothing ran.

    The process must still lead its own group, run the recorded executable and have started
    after the run did; a reused pid fails those checks and is left alone.
    """
    if not run.pid:
        return None
    try:
        expected = json.loads(run.command or "[]")[0]
        proc = psutil.Process(run.pid)
        cmdline = proc.cmdline()
        if (not cmdline or not _runner_matches(expected, cmdline) or os.getpgid(run.pid) != run.pid
                or proc.create_time() < run.started_at - 2):
            return None
    except (IndexError, TypeError, ValueError, OSError, psutil.Error):
        return None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(run.pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + KILL_GRACE_S
        while time.monotonic() < deadline and proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            time.sleep(0.05)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            break
    return f"stopped orphaned runner pid {run.pid} left by the previous service"


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
        """Mark runs left in 'running' as interrupted (cancelled if the operator asked) and fail
        their cards."""
        now = _now()
        with self.sessions.begin() as s:
            stuck = s.execute(select(Run).where(Run.stage == "running")).scalars().all()
            for run in stuck:
                orphan = _stop_orphan(run)
                if orphan:
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note", text=orphan))
                cancelled = bool(_checkpoint(run).get("cancel_requested"))
                run.stage = "cancelled" if cancelled else "interrupted"
                run.ended_at = now
                run.duration_s = float(now - run.started_at)
                run.error = f"{CANCEL_ERROR}; {note}" if cancelled else note
                s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text=f"{run.stage}: {note}"))
                if cancelled:
                    self._quarantine(s, run, now)
                if run.card_id is not None:
                    card = s.get(Card, run.card_id)
                    if card and card.column == "running":
                        card.column = "failed"
                        card.updated_at = now
                        if card.needs_approval and not projects.binding(s, card.id):
                            approval.issue_challenge(card)
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
                .where(or_(Card.retry_after.is_(None), Card.retry_after <= now))
                .where(Card.assignee_type == "agent")
                .where(~unfinished_dependency)
                .where(or_(Card.needs_approval.is_(False), Card.approved_at.is_not(None)))
                .order_by(Card.position, Card.id)
            ).scalars().all()
            for card in cards:
                if len(claimed) >= limit: break
                if refuse_timeout_retry(s, card, now):
                    continue
                link = projects.binding(s, card.id)
                # Second line of defence for standalone cards: only an unused, unexpired grant
                # for this exact route pin may start a run. Anything else needs a new approval.
                problem = approval.grant_problem(card, now) if card.needs_approval and not link else None
                if problem:
                    approval.revoke(card, now, problem)
                    continue
                if any((link or (r.card_id and projects.binding(s, r.card_id))) and projects.overlap(card.working_dir, r.working_dir) for r in active_runs):
                    continue
                # A named OpenClaw target has its own configured gateway workspace.
                # Keep its project conversations distinct and serialize work on that target.
                if card.agent=='openclaw' and any(r.agent=='openclaw' and
                    (link or (r.card_id and projects.binding(s,r.card_id))) and
                    ((s.get(Card,r.card_id) if r.card_id else s.get(ChatThread,r.thread_id)).agent_target or 'mm-main')==(card.agent_target or 'mm-main') for r in active_runs): continue
                prompt = projects.claim_context(s, card)
                if prompt is None: continue
                # While a subscription limit lasts and the operator chose to reroute, a story that
                # has not started goes straight to an approved alternate route of the same grade.
                rerouted_from = None
                if link and link.role == 'story' and card.agent in provider_limits.PROVIDERS and not getattr(card, 'output_only', False) and not projects.card_model_locked(s, card):
                    limit_row = provider_limits.rerouting_row(s, card.agent, now)
                    if limit_row:
                        alt = provider_limits.alternate(projects.approved_story_routes(projects.get(s, link.project_id), link),
                                                        card.agent, card.model, provider_limits.limited_providers(s, now))
                        if alt:
                            rerouted_from = {'agent': card.agent, 'model': card.model, 'limit_id': limit_row.id}
                            card.agent, card.model, card.agent_target = alt['agent'], alt['model'] or None, None
                            limit_row.rerouted += 1
                spec = self.registry.get(card.agent)
                if spec is None:
                    card.column, card.updated_at = "failed", now
                    continue
                model_requested = card.model or spec.default_model()
                resolved = resolve_free_alias(s, self.settings, card.agent, card.agent_target, model_requested)
                if resolved != model_requested:   # a task saved with the generic free default before it was resolved: run it on the agent's own free model
                    card.model = model_requested = resolved
                # Branch-scoped git access is an operator grant per approved project, never plan output.
                grant = agent_git.grant_for(self.settings, link.project_id, card) if link and link.role == 'story' else None
                card.agent_git_grant = grant
                if grant:
                    prompt = agent_git.apply_context(prompt, grant, card.id, card.agent, model_requested)
                card.subscription_billing=_reviewed_route_class(s, self.settings, card, model_requested) == "subscription"
                args=(card,prompt,model_requested,card.budget_usd if card.budget_usd is not None else self.settings.default_budget_usd,spec.binary(self.settings))
                resume=getattr(card,'resume_session',None)
                argv=spec.build(*args, session_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'mcd:story:{card.id}'))) if link and spec.preassigned_session else spec.build(*args,session_id=resume) if resume else spec.build(*args)
                run = Run(
                    card_id=card.id, agent=card.agent, model_requested=model_requested,
                    stage="running", started_at=now, working_dir=card.working_dir,
                    command=json.dumps(redact(argv, prompt)), log_path="",
                    attempt=card.retry_attempts + 1,
                    checkpoint=json.dumps({"dispatch_policy": dispatch_snapshot(
                        card, args[3], _reviewed_route_class(
                            s, self.settings, card, model_requested)),
                        **({"agent_git": [{"dir": c.dir, "repo": c.repo, "branch": c.branch} for c in grant.clones]}
                           if grant else {}),
                        **({"rerouted_from": rerouted_from} if rerouted_from else {}),
                        "context_bytes": len(prompt.encode())}),
                )
                s.add(run)
                s.flush()
                projects.bind_output_run(s,card,run.id)
                active_runs.append(run)
                if link and link.role == "story":
                    projects.memory(s, projects.get(s, link.project_id), "context", prompt, "mcd", card.id, run.id)
                run.log_path = str(self.runs_dir / f"run-{run.id}.log")
                s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text="running"))
                if card.needs_approval and not link:
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note", text=approval.consume(card, run.id, now)))
                card.column, card.updated_at = "running", now
                card.retry_attempts = run.attempt
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
    def _env(agent: str | None = None) -> dict[str, str]:
        # No MAC_CONTROL_* settings: operator credentials and paths never reach an agent.
        env = runner_env()
        spec = REGISTRY.get(agent) if agent else None
        if spec is not None:
            env.update(spec.env)   # for example Grok's telemetry and trace upload switches, always off
        env["PATH"] = ":".join((*EXTRA_PATH, env.get("PATH", "/usr/bin:/bin")))
        env.setdefault("HOME", str(Path.home()))
        return env

    def _dispatch_admission(self, run_id, argv):
        with self.sessions.begin() as db:
            row = db.get(Run, run_id)
            if row is None:
                raise DispatchDenied("PRICE_UNKNOWN: run missing")
            try:
                source = db.get(Card, row.card_id) if row.card_id else db.get(ChatThread, row.thread_id)
                current_class = _reviewed_route_class(db, self.settings, source, row.model_requested) if source else None
                evidence = admit_dispatch(self.settings, row, argv, default_free_only=False, current_price_class=current_class)
            except DispatchDenied as exc:
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="note", text=f"dispatch denied: {exc}"))
                problem = str(exc)
            else:
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="note",
                                text="dispatch admitted: " + json.dumps(evidence, sort_keys=True)))
                problem = None
        if problem:
            raise DispatchDenied(problem)

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
        supplied_key: str | None = None  # the saved OpenRouter key this run was given, if any: scrubbed from everything it prints

        with open(log_path, "a", encoding="utf-8") as log, open(raw_path, "a", encoding="utf-8") as raw:
            def write(text: str) -> None:
                text = scrub(text, supplied_key)
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
                    line = scrub(line_b.decode("utf-8", "replace").rstrip("\n"), supplied_key)
                    raw.write(("! " if is_stderr else "") + line + "\n")
                    if is_stderr:
                        parser.feed_stderr(line)
                        quota_reported |= bool(re.search(r"usage limit|session limit|rate.?limit|quota exceeded|quota exhausted|too many requests|limit reached|HTTP.?429",line,re.I))
                        if line.strip():
                            write(f"! {line}")
                    else:
                        for out in parser.feed(line):
                            write(out)

            # A cancel committed between the claim and this point must not launch a runner.
            if handle.cancel_requested or await asyncio.to_thread(self._cancel_recorded, run_id):
                handle.cancel_requested = True
                write(f"{CANCEL_ERROR} before the runner started")
                return "cancelled", None, CANCEL_ERROR, parser.meta, 0.0
            try:
                await asyncio.to_thread(self._dispatch_admission, run_id, argv)
            except DispatchDenied as exc:
                write(f"dispatch denied: {exc}")
                return "failed", None, str(exc), parser.meta, 0.0
            try:
                if agent == 'hermes':
                    from hermes_runtime import command
                    argv = command(argv, getattr(self.settings, "agent_tools_path", None))
                env = self._env(agent)
                if agent in SAVED_KEY_AGENTS:
                    with self.sessions() as db:
                        supplied_key = saved_openrouter_key(db, self.settings)
                if supplied_key:
                    # The only operator credential an agent ever receives, and only after the operator opted in.
                    env["OPENROUTER_API_KEY"] = supplied_key
                    write("The saved OpenRouter key was supplied to this run (its value is never logged).")
                proc = await asyncio.create_subprocess_exec(
                    *argv, cwd=cwd, env=env,
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=LINE_LIMIT,
                )
            except (FileNotFoundError, PermissionError) as exc:
                error = f"could not start {spec.name}: {exc}"
                write(f"error: {error}")
                proc = None

            if proc is not None:
                handle.proc = proc
                await asyncio.to_thread(self._record_pid, run_id, proc.pid)
                if handle.cancel_requested:  # the cancel arrived while the runner was starting
                    await self._kill(handle)
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
                        stage, error = "cancelled", CANCEL_ERROR
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

    def _record_pid(self, run_id: int, pid: int) -> None:
        with self.sessions.begin() as s:
            run = s.get(Run, run_id)
            if run is not None and run.stage == "running":
                run.pid = pid

    def _record_cancel(self, run_id: int) -> bool:
        """Commit the operator's cancel before any signal. False if the run is not running."""
        with self.sessions.begin() as s:
            run = s.get(Run, run_id)
            if run is None or run.stage != "running":
                return False
            cp = _checkpoint(run)
            if not cp.get("cancel_requested"):
                run.checkpoint = json.dumps({**cp, "cancel_requested": True, "cancel_requested_at": _now()})
                s.add(RunEvent(run_id=run_id, ts=_now(), kind="note", text="operator cancellation requested"))
            return True

    def _cancel_recorded(self, run_id: int) -> bool:
        with self.sessions() as s:
            run = s.get(Run, run_id)
            return bool(run and _checkpoint(run).get("cancel_requested"))

    def _quarantine(self, s, run: Run, now: int) -> None:
        """Keep a cancelled run's partial output as reviewable evidence.

        The record lists the run's own log files; the workspace is left exactly as the runner
        left it. Nothing here is published, accepted or deleted.
        """
        root = self.runs_dir / "quarantine"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / f"run-{run.id}.json"
        evidence = []
        if run.log_path:
            for log in (Path(run.log_path), Path(run.log_path).with_suffix(".raw.log")):
                if log.is_file():
                    evidence.append({"path": str(log), "bytes": log.stat().st_size})
        payload = {"run_id": run.id, "card_id": run.card_id, "stage": run.stage, "reason": run.error,
                   "workspace": run.working_dir, "evidence": evidence, "quarantined_at": now,
                   "publishable": False}
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(payload, sort_keys=True))
        os.replace(tmp, path)
        run.checkpoint = json.dumps({**_checkpoint(run), "quarantine": str(path), "publishable": False})
        s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                       text="partial output quarantined for review; not publishable"))

    def _settle_cancel(self, s, run_id: int, stage: str, error: str | None) -> tuple[str, str | None]:
        """A result that arrives after a committed cancel is recorded as cancelled, not accepted."""
        run = s.get(Run, run_id)
        if run is not None and stage != "cancelled" and _checkpoint(run).get("cancel_requested"):
            return "cancelled", LATE_CANCEL_ERROR
        return stage, error

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
        provider_limits.observe(s, run, now)
        return run

    def _finish(self, run_id, card_id, stage, exit_code, error, meta, duration) -> None:
        now = _now()
        with self.sessions.begin() as s:
            stage, error = self._settle_cancel(s, run_id, stage, error)
            run = self._record_run(s, run_id, stage, exit_code, error, meta, duration, now)
            if run is None:
                return
            if stage == "cancelled":
                self._quarantine(s, run, now)
            card = s.get(Card, card_id)
            if card and card.column == "running":
                retrying = self._retryable(stage, error) and run.attempt < card.max_attempts and not projects.card_model_locked(s, card)
                if retrying:
                    delay = card.retry_backoff_s * (2 ** max(0, run.attempt - 1))
                    card.column, card.retry_after = "queued", now + delay
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                                   text=f"retry scheduled: attempt {run.attempt + 1} of {card.max_attempts} after {delay}s"))
                else:
                    card.column, card.retry_after = ("done" if stage == "succeeded" else "failed"), None
                    if stage != "succeeded" and self._retryable(stage, error):
                        reason = f"retry budget exhausted after {run.attempt} of {card.max_attempts} attempts"
                        run.error = f"{reason}: {error or 'transient failure'}"
                        s.add(RunEvent(run_id=run.id, ts=now, kind="note", text=reason))
                card.updated_at = now
                if not retrying and card.needs_approval and not projects.binding(s, card.id):
                    approval.issue_challenge(card)  # the used grant is retired; a rerun needs a new one
                if not retrying:
                    projects.on_finish(s, card, run, stage)

    @staticmethod
    def _retryable(stage: str, message: str | None) -> bool:
        """Only identifiable transport/provider failures retry; a timeout needs review.

        A wall-clock timeout cannot prove the remote action stopped, so the existing
        idempotency guard deliberately keeps it out of automatic retry.
        """
        return stage == "failed" and bool(TRANSIENT_ERROR.search(message or ""))

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
            model_requested = thread.model or spec.default_model()
            ctx = SimpleNamespace(mode=thread.mode, working_dir=thread.working_dir,
                                  agent_target=thread.agent_target, timeout_s=CHAT_TIMEOUT_S,
                                  subscription_billing=_reviewed_route_class(s, self.settings, thread, model_requested) == "subscription")
            argv = spec.build(ctx, msg.text, model_requested, self.settings.default_budget_usd,
                              spec.binary(self.settings), session_id=thread.session_id)
            run = Run(thread_id=thread.id, agent=thread.agent,
                      model_requested=model_requested, stage="running",
                      started_at=now, working_dir=thread.working_dir,
                      command=json.dumps(redact(argv, msg.text)), log_path="",
                      checkpoint=json.dumps({"dispatch_policy": dispatch_snapshot(
                          thread, self.settings.default_budget_usd, _reviewed_route_class(
                              s, self.settings, thread, model_requested))}))
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
            stage, error = self._settle_cancel(s, run_id, stage, error)
            run = self._record_run(s, run_id, stage, exit_code, error, meta, duration, now)
            if run is not None and stage == "cancelled":
                self._quarantine(s, run, now)
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
        if not await asyncio.to_thread(self._record_cancel, run_id):
            return False
        handle = self._handles.get(run_id)
        if handle is None:
            # Not yet started here: the pre-spawn check, or restart recovery, acts on the
            # committed request.
            return True
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
