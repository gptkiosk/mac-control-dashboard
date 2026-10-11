"""mac-control API: FastAPI entry point.

Phase 1: health endpoint, security headers, and serving the built Vue app.
Phase 2: SQLite storage with migrations at startup, the background collector
(macmon, launchd, Tailscale, updates), and the metrics/services/release APIs.
Later phases add the task board (Phase 3) and Google sign-in (Phase 4).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from urllib.parse import urlencode
from auth import AuthService, PUBLIC
from routes import authentication, operations, projects as project_routes
from github_read import GithubReader
from alerts import AlertMonitor, HermesSender
from agent_access import AgentAccessService
from routes import agent_tools
from routes import profiles as profile_routes, project_bridge
from project_delivery import ProjectMessenger
from reports import ReportsReader

import guard
from collector import Collector
from dispatcher import Dispatcher
from db import make_engine, make_session_factory
from migrate import upgrade_to_head
from routes import billing as billing_routes, chat, health, mcp as mcp_routes, metrics, release, services, system, tasks
from settings import get_settings
from spa import mount_spa
from version import __version__

logger = logging.getLogger("mac_control.api")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def create_app() -> FastAPI:
    settings = get_settings()
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    engine = make_engine(settings.db_path)
    upgrade_to_head(engine)
    sessions = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        collector = None
        if settings.collector_enabled:
            collector = Collector(
                sessions,
                macmon_path=settings.macmon_path,
                tailscale_path=settings.tailscale_path,
                disk_path=settings.disk_path,
                service_prefixes=tuple(settings.service_prefixes),
                sample_interval_s=settings.sample_interval_s,
            )
            collector.agent_binaries = {
                "openclaw": settings.openclaw_path, "hermes": settings.hermes_path,
                "codex": settings.codex_path, "claude": settings.claude_path,
            }
            collector.start()
        app.state.collector = collector
        dispatcher = None
        if settings.dispatcher_enabled:
            dispatcher = Dispatcher(sessions, settings)
            dispatcher.start()
        app.state.dispatcher = dispatcher
        if settings.dispatcher_enabled:
            app.state.project_messenger.start()
        app.state.alerts.start()
        try:
            yield
        finally:
            await app.state.project_messenger.stop()
            await app.state.alerts.stop()
            if dispatcher:
                await dispatcher.stop()
            if collector:
                await collector.stop()
            engine.dispose()

    app = FastAPI(
        title="mac-control", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.alerts = AlertMonitor(sessions, settings.alerts_path, HermesSender(settings.hermes_path))
    app.state.project_messenger = ProjectMessenger(sessions, settings)
    app.state.github = GithubReader(settings.gh_path)
    app.state.reports = ReportsReader(settings.ops_reports_dir, settings.hermes_reports_dir)
    app.state.auth = AuthService(settings, sessions)
    app.state.agent_access = AgentAccessService(settings, sessions)
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.collector = None
    app.state.dispatcher = None
    guard_ports = (settings.port, settings.dev_port)
    extra_hosts = set(settings.allowed_hosts_extra)

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        if request.headers.get("host", "") in extra_hosts:
            reason = None if request.method in guard.SAFE_METHODS or request.headers.get(guard.GUARD_HEADER) == "1" else "missing X-Mac-Control header"
        else:
            reason = guard.check(request, guard_ports, settings.auth_origins if settings.auth_enabled else ())
        if reason:
            return guard.refusal(reason)
        if request.url.path == '/api/hermes-projects':
            try:
                project_bridge.authorize(request)
                request.state.project_bridge = True
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        elif request.headers.get("authorization"):
            try:
                request.state.agent_grant = app.state.agent_access.authorize(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        elif settings.auth_enabled:
            # Only bootstrap/login/static assets are public; all data and actions require a session.
            if request.url.path not in PUBLIC and not request.url.path.startswith("/assets/"):
                try:
                    user = app.state.auth.current(request)
                except Exception:
                    return JSONResponse({"detail": "Sign-in address unavailable."}, status_code=403)
                if not user:
                    if request.method == "GET" and "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api/"):
                        return RedirectResponse("/login?" + urlencode({"next": request.url.path}), status_code=303)
                    return JSONResponse({"detail": "Sign in to continue."}, status_code=401)
                request.state.user = user
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith("/auth/"):
            return JSONResponse({"detail": "Invalid sign-in request."}, status_code=422)
        if request.url.path.startswith(('/api/profile', '/api/hermes-projects')):
            return JSONResponse({'detail': 'Invalid profile or project request.'}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if settings.auth_enabled:
            response.headers["Cache-Control"] = "no-store"
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.include_router(authentication.router)
    app.include_router(agent_tools.admin)
    app.include_router(agent_tools.router)
    app.include_router(health.router)
    app.include_router(release.router)
    app.include_router(metrics.router)
    app.include_router(services.router)
    app.include_router(system.router)
    app.include_router(tasks.router)
    app.include_router(billing_routes.router)
    app.include_router(chat.router)
    app.include_router(mcp_routes.router)
    app.include_router(operations.router)
    app.include_router(project_routes.router)
    app.include_router(profile_routes.router)
    app.include_router(project_bridge.router)
    # The SPA catch-all is registered last so API routes win.
    mount_spa(app, settings.web_dist)
    return app


app = create_app()
