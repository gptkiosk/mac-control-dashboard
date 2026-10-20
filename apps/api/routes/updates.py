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

import release_fetch as rf
import source_update as su
import update_engine as ue
from routes.agent_tools import operator
from settings import REPO_ROOT, get_settings

router = APIRouter(prefix="/api/app-updates")


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=ue.INBOX_NAME.pattern)
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FetchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")  # exactly what the operator was shown
    channel: str = Field(default="stable", pattern=r"^(stable|prerelease)$")
    confirm: bool
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SourceStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")   # exactly the tag the check showed
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")            # and the signed commit it named
    confirm: bool


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
    if cfg is not None:
        body["trust"] = cfg.trust["kind"]   # "ssh-signature": one confirmation verifies the release signature; "pinned-digest": the operator pastes a digest
    if kind == "dev":
        body["source"] = _source_inspection()   # local git state only; nothing is fetched
    if cfg is None:
        return body
    try:
        body["install"] = ue.status(cfg)
    except ue.UpdateError as exc:
        body["problems"] = exc.problems
    body["blockers"] = ue.drain_blockers(cfg.db_path)
    return body


def _source_inspection() -> dict:
    s = get_settings()
    return su.inspect(REPO_ROOT, product=s.product_short_name, label=s.launchd_label)


def _refused(exc: su.SourceUpdateError, status: int = 409):
    first, rest = (exc.problems or ["Refused."])[0], (exc.problems or [])[1:]
    return HTTPException(status, {"message": first, "problems": rest, "blockers": exc.blockers})


@router.get("/operation")
def operation(request: Request):
    """The latest update operation: ordered steps, their state and a log tail. Read-only; survives the service restart."""
    operator(request)
    cfg, problems = _helper(get_settings().update_root)    # not _managed(): that refuses while an update runs, which is when this is needed
    if cfg is None:
        return {"operation": None, "active": False, "log": [], "problems": problems}
    return ue.operation_status(cfg)


@router.get("/source")
def source_status(request: Request):
    """This checkout's eligibility and the last or running source-update operation. Local only."""
    operator(request)
    return {"inspection": _source_inspection(), **su.status(get_settings().data_dir)}


@router.get("/source/check")
def source_check(request: Request):
    """Read-only: the official release list and the signed manifest of the newest stable release. Downloads no package."""
    operator(request)
    s = get_settings()
    try:
        return su.check(REPO_ROOT, s.data_dir, db_path=s.db_path, product=s.product_short_name, label=s.launchd_label)
    except su.SourceUpdateError as exc:
        raise _refused(exc, 502) from None


@router.post("/source/start", status_code=202)
def source_start(request: Request, body: SourceStartIn):
    """Start the update the operator confirmed. The helper outlives the service restart; poll /source/operation."""
    operator(request)
    s = get_settings()
    try:
        return su.begin(REPO_ROOT, s.data_dir, db_path=s.db_path, product=s.product_short_name, label=s.launchd_label,
                        port=s.port, tag=body.tag, commit=body.commit, confirm=body.confirm)
    except su.SourceUpdateError as exc:
        raise _refused(exc) from None


@router.get("/source/operation")
def source_operation(request: Request):
    operator(request)
    return su.status(get_settings().data_dir)


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


@router.get("/check")
def check(request: Request, channel: str = "stable"):
    """Read-only look at the public Releases API. Nothing is downloaded or changed."""
    operator(request)
    if channel not in rf.CHANNELS:
        raise HTTPException(422, "channel must be stable or prerelease")
    cfg = _managed()
    if channel == "prerelease" and not cfg.allow_prerelease:
        raise HTTPException(409, "The prerelease channel is off in the helper configuration.")
    try:
        found = rf.check(cfg, channel)
    except rf.FetchError as exc:
        raise HTTPException(502, {"message": "Could not check for updates.", "problems": exc.problems}) from None
    return {"available": found is not None, "candidate": rf.describe(found) if found else None,
            "installed": rf.installed_version(cfg)}


@router.post("/fetch", status_code=202)
def fetch(request: Request, body: FetchIn):
    """Download, verify and stage the release the operator confirmed. Never switches versions."""
    operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    cfg = _managed()
    if body.channel == "prerelease" and not cfg.allow_prerelease:
        raise HTTPException(409, "The prerelease channel is off in the helper configuration.")
    args = ["fetch", body.version, "--channel", body.channel]
    if body.manifest_sha256:
        args += ["--manifest-sha256", body.manifest_sha256]
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
    if body.version_id == ue._link_target(cfg, "current"):  # noqa: SLF001 - same package
        raise HTTPException(409, "That version is already running.")
    try:  # the helper refuses this too; saying so here means the page can show why instead of waiting
        schema = ue.database_revision(cfg.db_path)
        if not ue.schema_compatible(schema, ue.known_revisions(cfg.versions / body.version_id)):
            raise HTTPException(409, {"message": f"The database is on schema {schema}, which that version does not know, so the code "
                                                 "cannot go back to it. Restore a data snapshot taken before that schema change "
                                                 "on the host first, or install a version that knows this schema.",
                                      "problems": []})
    except ue.UpdateError as exc:
        raise HTTPException(409, {"message": "The database could not be checked.", "problems": exc.problems}) from None
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
