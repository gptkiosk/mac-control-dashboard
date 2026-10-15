"""Background collector: Mac metrics, launchd services, Tailscale, and pending updates.

Runs inside the API process (started from the FastAPI lifespan). Each loop is independent
so a failure in one source never stops the others. All subprocess calls go through
`self.run`, which tests replace, so tests never spawn macmon or launchctl.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import psutil
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import facts
import rollups
import sampling
import services_probe
import subagents
from models import METRIC_FIELDS, MetricSample, ServiceSnapshot
from processes import ProcessSampler

logger = logging.getLogger("mac_control.collector")

Runner = Callable[..., Awaitable[tuple[int, str]]]


async def run_command(*argv: str, timeout: float = 30.0, input_data: bytes | None = None) -> tuple[int, str]:
    """Run a command and return (returncode, stdout). Never raises for a missing binary."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(input_data), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, ""
    return proc.returncode or 0, out.decode("utf-8", "replace")


class Collector:
    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        macmon_path: str,
        tailscale_path: str,
        disk_path: str,
        service_prefixes: tuple[str, ...],
        sample_interval_s: int = 10,
        run: Runner = run_command,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.sessions = session_factory
        self.macmon_path = macmon_path
        self.tailscale_path = tailscale_path
        self.disk_path = disk_path
        self.prefixes = service_prefixes
        self.interval = sample_interval_s
        self.run = run
        self.clock = clock

        self.latest: dict[str, Any] | None = None
        self.processes: list[dict[str, object]] = []
        self.tailscale: dict[str, Any] | None = None
        self.updates: dict[str, Any] | None = None
        self.subagents: dict[str, Any] | None = None
        self.agent_binaries: dict[str, str] = {}
        from usage import UsageScanner
        self.usage_scanner = UsageScanner(self.sessions)
        from openrouter_costs import OpenRouterCosts, configured_keys

        def _resolve_keys(home):
            # An operator who shared their saved OpenRouter key with Hermes and OpenClaw: that key is what they run with.
            saved = None
            try:
                from profiles import saved_openrouter_key
                from settings import get_settings
                with self.sessions() as db:
                    saved = saved_openrouter_key(db, get_settings())
            except Exception:  # noqa: BLE001 - the meter must never depend on this
                saved = None
            return configured_keys(home, saved)
        self.openrouter_costs = OpenRouterCosts(resolve=_resolve_keys)
        self.macmon_status = "starting"

        self._net_prev: tuple[float, int, int] | None = None
        self._proc_sampler = ProcessSampler()
        self._tasks: list[asyncio.Task] = []
        self._macmon: asyncio.subprocess.Process | None = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        loops = (self._metrics_loop, self._services_loop, self._tailscale_loop,
                 self._updates_loop, self._maintenance_loop, self._subagents_loop, self._usage_loop, self._openrouter_loop)
        self._tasks = [asyncio.create_task(loop(), name=loop.__name__) for loop in loops]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._macmon and self._macmon.returncode is None:
            self._macmon.terminate()
            try:
                await asyncio.wait_for(self._macmon.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._macmon.kill()

    # ------------------------------------------------------------------ metrics

    async def system_extras(self) -> dict[str, float | None]:
        """Memory used, pressure, disk and network: the parts macmon does not cover."""
        _, vm_text = await self.run("vm_stat")
        _, pressure_text = await self.run("sysctl", "-n", "kern.memorystatus_vm_pressure_level")
        disk = psutil.disk_usage(self.disk_path)
        net = psutil.net_io_counters()
        now = (self.clock(), net.bytes_recv, net.bytes_sent)
        rx, tx = sampling.net_rates(self._net_prev, now)
        self._net_prev = now
        return {
            "mem_used": sampling.memory_used_bytes(sampling.parse_vm_stat(vm_text)),
            "pressure_level": sampling.parse_pressure_level(pressure_text),
            "disk_used": float(disk.used),
            "disk_total": float(disk.total),
            "net_rx_bps": rx,
            "net_tx_bps": tx,
        }

    async def record(self, macmon_values: dict[str, float | None]) -> dict[str, Any]:
        """Merge one macmon reading with system extras, store it, and refresh processes."""
        row: dict[str, Any] = {field: None for field in METRIC_FIELDS}
        row.update(macmon_values)
        row.update(await self.system_extras())
        if row.get("mem_total") is None:
            row["mem_total"] = float(psutil.virtual_memory().total)
        row["ts"] = int(self.clock())
        await asyncio.to_thread(self._insert_sample, row)
        self.processes = await asyncio.to_thread(self._proc_sampler.sample, 15)
        self.latest = row
        return row

    def _insert_sample(self, row: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.execute(insert(MetricSample).prefix_with("OR REPLACE"), [row])

    async def _metrics_loop(self) -> None:
        backoff = 5
        while True:
            try:
                self._macmon = await asyncio.create_subprocess_exec(
                    self.macmon_path, "pipe", "-i", str(self.interval * 1000),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
            except FileNotFoundError:
                self.macmon_status = "missing"
                logger.warning("macmon not found at %s; collecting without power/temperature",
                               self.macmon_path)
                await self._fallback_loop()
                return
            self.macmon_status = "running"
            assert self._macmon.stdout is not None
            async for raw in self._macmon.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    await self.record(sampling.parse_macmon(line))
                    backoff = 5
                except Exception:  # one bad line or a DB hiccup must not stop collection
                    logger.exception("failed to record sample")
            code = await self._macmon.wait()
            self.macmon_status = "restarting"
            logger.warning("macmon exited with %s; restarting in %ss", code, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _fallback_loop(self) -> None:
        while True:
            try:
                await self.record({"cpu_pct": psutil.cpu_percent(None)})
            except Exception:
                logger.exception("fallback sample failed")
            await asyncio.sleep(self.interval)

    # ------------------------------------------------------------------ services

    async def snapshot_services(self) -> list[dict[str, Any]]:
        code, listing = await self.run("launchctl", "list")
        if code != 0:
            return []
        labels = services_probe.parse_launchctl_list(listing, self.prefixes)
        uid = os.getuid()
        ts = int(self.clock())
        rows: list[dict[str, Any]] = []
        for label in labels:
            code, printed = await self.run("launchctl", "print", f"gui/{uid}/{label}")
            if code != 0:
                continue
            fields = services_probe.parse_launchctl_print(printed)
            rows.append({"ts": ts, "label": label, "domain": "gui", **fields})
        if rows:
            await asyncio.to_thread(self._insert_services, rows)
        return rows

    def _insert_services(self, rows: list[dict[str, Any]]) -> None:
        with self.sessions.begin() as session:
            session.execute(insert(ServiceSnapshot), rows)

    async def _services_loop(self) -> None:
        while True:
            try:
                await self.snapshot_services()
            except Exception:
                logger.exception("service snapshot failed")
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ facts

    async def refresh_tailscale(self) -> None:
        code, out = await self.run(self.tailscale_path, "status", "--json")
        if code == 0 and out.strip():
            self.tailscale = {**facts.parse_tailscale(out), "checked_at": int(self.clock())}
        else:
            self.tailscale = {"error": f"tailscale status failed (exit {code})",
                              "checked_at": int(self.clock())}

    async def refresh_updates(self) -> None:
        code, out = await self.run("softwareupdate", "-l", timeout=180)
        if code == 0:
            self.updates = {"updates": facts.parse_softwareupdate(out),
                            "checked_at": int(self.clock())}
        else:
            self.updates = {"error": f"softwareupdate failed (exit {code})",
                            "checked_at": int(self.clock())}

    async def _tailscale_loop(self) -> None:
        while True:
            try:
                await self.refresh_tailscale()
            except Exception:
                logger.exception("tailscale refresh failed")
            await asyncio.sleep(60)

    async def _updates_loop(self) -> None:
        while True:
            try:
                await self.refresh_updates()
            except Exception:
                logger.exception("update check failed")
            await asyncio.sleep(6 * 3600)

    # ------------------------------------------------------------------ sub-agents

    async def refresh_subagents(self) -> None:
        if self.agent_binaries:
            self.subagents = await subagents.snapshot(self.run, self.agent_binaries)

    async def _subagents_loop(self) -> None:
        while True:
            try:
                await self.refresh_subagents()
            except Exception:
                logger.exception("sub-agent refresh failed")
            await asyncio.sleep(60)

    async def _usage_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.usage_scanner.scan)
            except Exception:
                logger.exception("usage indexing failed")
            await asyncio.sleep(15)

    async def _openrouter_loop(self) -> None:
        while True:
            await asyncio.to_thread(self.openrouter_costs.refresh)
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ maintenance

    def maintain(self, now: int, full: bool) -> None:
        """Roll minutes every call; roll days and apply retention when `full`."""
        with self.sessions.begin() as session:
            rollups.roll_minutes(session, now)
            if full:
                rollups.roll_days(session, now)
                rollups.apply_retention(session, now)

    async def _maintenance_loop(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(60)
            ticks += 1
            try:
                await asyncio.to_thread(self.maintain, int(self.clock()), ticks % 60 == 0)
            except Exception:
                logger.exception("maintenance failed")
