"""Narrow operator-only update API. It reads install state and starts the host helper; it
never stops the service, switches versions or touches packages itself.

Every route needs a signed-in operator (no agent grant); the operator boundary has already
refused agent processes. With sign-in off, use the helper CLI on the host instead.
"""
from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import update_engine as ue
from routes.agent_tools import operator
from settings import REPO_ROOT, get_settings

router = APIRouter(prefix="/api/app-updates")


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=ue.INBOX_NAME.pattern)
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(pattern=ue.VERSION_ID.pattern)


def _helper(root: Path | None) -> tuple[ue.HelperConfig | None, list[str]]:
    if root is None:
        return None, []
    try:
        cfg = ue.load_config(root / "helper" / "helper.json")
        if cfg.root != root:
            return None, ["helper.json root does not match MAC_CONTROL_UPDATE_ROOT"]
        ue.prepare_layout(cfg)
        return cfg, []
    except (ue.UpdateError, OSError) as exc:
        return None, getattr(exc, "problems", [f"update root is not usable ({type(exc).__name__})"])


@router.get("")
def update_status(request: Request):
    operator(request)
    root = get_settings().update_root
    kind, detail = ue.install_kind(REPO_ROOT, root)
    cfg, problems = _helper(root)
    body = {"kind": kind, "detail": detail, "configured": cfg is not None, "problems": problems,
            "manual_instructions": ue.manual_instructions(kind, _product(cfg))}
    if cfg is None:
        return body
    try:
        body["install"] = ue.status(cfg)
    except ue.UpdateError as exc:
        body["problems"] = exc.problems
    body["blockers"] = ue.drain_blockers(cfg.db_path)
    return body


@router.post("/stage", status_code=202)
def stage(request: Request, body: StageIn):
    operator(request)
    cfg = _managed()
    try:
        ue.inbox_paths(cfg, body.name)  # same name rule the helper applies
    except ue.UpdateError as exc:
        raise HTTPException(422, exc.problems[0]) from None
    args = ["stage", body.name] + (["--manifest-sha256", body.manifest_sha256] if body.manifest_sha256 else [])
    return _spawn(cfg, args)


@router.post("/apply", status_code=202)
def apply(request: Request, body: VersionIn):
    operator(request)
    cfg = _managed()
    blockers = ue.drain_blockers(cfg.db_path)
    if blockers:
        # Explicit drain: nothing is stopped or cancelled on the operator's behalf.
        raise HTTPException(409, {"message": "Drain first. Nothing was stopped.", "blockers": blockers})
    if ue.read_receipt(cfg, body.version_id) is None:
        raise HTTPException(409, "That version is not completely staged.")
    return _spawn(cfg, ["apply", body.version_id])


@router.post("/recover", status_code=202)
def recover(request: Request):
    operator(request)
    return _spawn(_managed(), ["recover"])


def _product(cfg: ue.HelperConfig | None) -> str:
    return cfg.product if cfg else ("rcd" if get_settings().product_short_name.upper() == "RCD" else "mcd")


def _managed() -> ue.HelperConfig:
    root = get_settings().update_root
    kind, detail = ue.install_kind(REPO_ROOT, root)
    if kind != "release":
        raise HTTPException(409, {"message": f"Automatic updates are off: {detail}.",
                                  "manual_instructions": ue.manual_instructions(kind, _product(None))})
    cfg, problems = _helper(root)
    if cfg is None:
        raise HTTPException(409, {"message": "The update helper is not set up.", "problems": problems})
    try:
        if ue.load_state(cfg).get("tx"):
            raise HTTPException(409, "An update is in progress or was interrupted. Run recovery.")
    except ue.UpdateError as exc:
        raise HTTPException(409, {"message": "Install state is unreadable.", "problems": exc.problems}) from None
    return cfg


def _spawn(cfg: ue.HelperConfig, args: list[str]) -> dict:
    """Start the pinned helper outside this service, so stopping the service cannot stop it."""
    helper = cfg.root / "helper" / "update_helper.py"
    argv = [cfg.python, "-I", str(helper), *args]
    if cfg.service["kind"] == "systemd-user":
        # A child of this service would die with its cgroup; run it as its own transient unit.
        systemd_run = next((p for p in ("/usr/bin/systemd-run", "/bin/systemd-run") if os.path.isfile(p)), None)
        if not systemd_run:
            raise HTTPException(409, "systemd-run is not available, so the helper cannot run outside the service.")
        argv = [systemd_run, "--user", "--collect", "--quiet", f"--unit=dashboard-update-{secrets.token_hex(4)}",
                "--", *argv]
    # Only what the helper needs; none of this app's settings or credentials.
    env = {**ue.COMMAND_ENV, "HOME": str(Path.home())}
    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if key in os.environ:
            env[key] = os.environ[key]
    log = os.open(cfg.state_dir / "helper.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                         cwd=str(cfg.root / "helper"), start_new_session=True, close_fds=True)
    except OSError:
        raise HTTPException(409, "The update helper could not be started.") from None
    finally:
        os.close(log)
    return {"started": args[0], "poll": "/api/app-updates"}
