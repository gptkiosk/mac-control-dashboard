# Getting started

## Purpose

Quick orientation for a new user or developer: prerequisites, building both apps, starting the API and web server, running checks, and installing the LaunchAgent. This page supports first-time setup and recovery after a clean clone or a system reset.

Target reader: operator, developer, or contributor who needs the app running at `http://127.0.0.1:8800` with a validated build.

## Screenshots

- Pending capture: `getting-started-overview.png`
- Pending capture: `run-local-api.png`
- Pending capture: `launchagent-installed.png`

## Controls

- Header sun/moon toggle (theme switch) — does not affect setup.
- Sidebar navigation — accessible after login or when auth is disabled.
- `LoginGate` — appears when `MAC_CONTROL_AUTH_ENABLED=true`.
- `Scripts` folder commands — `bootstrap.sh`, `install-launchagent.sh`, `serve.py`, `npm run dev`.
- Health endpoint — `GET /healthz` (used by LaunchAgent verification).

## Prerequisites

Verified on the primary host (Mac mini M4, macOS 27.0.1):

- macOS 27.0.1+ (confirmed); earlier macOS versions untested.
- Python 3.12 (`/opt/homebrew/bin/python3.12`) — the `.venv` is rebuilt by `scripts/bootstrap.sh` with this binary. System Python 3.14.6 exists but is not used by the app.
- Node v22.22.3 and npm 10.9.8 (`node --version`, `npm --version`).
- `brew` or `/opt/homebrew/bin/python3.12` in `PATH` (used by `bootstrap.sh`).
- Write access to `~/Library/LaunchAgents/` (for LaunchAgent install).
- `plutil` available (macOS built-in; used by `scripts/install-launchagent.sh`).
- Ports 8800 and 5173 available. The API port is configurable; the Vite development port and API proxy are defined in `apps/web/vite.config.ts`.

Verified command outputs (primary host):

```bash
sw_vers                        # ProductName: macOS, ProductVersion: 27.0.1
/opt/homebrew/bin/python3.12 --version  # Python 3.12.13
node --version                  # v22.22.3
npm --version                   # 10.9.8
bash -n scripts/bootstrap.sh    # syntax OK
bash -n scripts/install-launchagent.sh  # syntax OK
```

Not required for basic run:
- Tailscale (`/usr/local/bin/tailscale`) — only needed for remote reachability on 9443 (operator-configured).
- `~/.mac-control/.env` — created manually; the server runs with safe defaults (`MAC_CONTROL_HOST=127.0.0.1`, auth disabled) without it.

## Build

`scripts/bootstrap.sh` rebuilds the API venv and the web build in one command:

```bash
cd $(git rev-parse --show-toplevel 2>/dev/null || pwd)
bash scripts/bootstrap.sh
```

What it does (verified against script source):

1. Creates `apps/api/.venv` with `/opt/homebrew/bin/python3.12 -m venv .venv` (only if `.venv/bin/python` is missing).
2. Installs `requirements.lock.txt` via `.venv/bin/pip install -q -r requirements.lock.txt`.
3. Runs `.venv/bin/pip check` to confirm dependency consistency.
4. Runs `npm ci --no-audit --no-fund` in `apps/web`.
5. Builds `npm run build` (Vue 3 + TypeScript) producing `apps/web/dist/index.html`.

If any step fails, the script exits (`set -euo pipefail`). Check the output; common failures are missing `/opt/homebrew/bin/python3.12` or a locked `package-lock.json` with an outdated `npm` version.

## Running the API

Start the FastAPI server (single source of truth for host/port):

```bash
cd apps/api
.venv/bin/python serve.py
```

This binds to `MAC_CONTROL_HOST` (`127.0.0.1` by default) and `MAC_CONTROL_PORT` (`8800`). `serve.py` refuses a non-loopback bind if auth is not enabled (`MAC_CONTROL_AUTH_ENABLED=false`). Verify it is running:

```bash
curl -fsS --max-time 2 http://127.0.0.1:8800/healthz || echo "not answering"
```

The LaunchAgent (`scripts/install-launchagent.sh`) uses the same verification pattern (`curl -fsS --max-time 2 "http://127.0.0.1:8800/healthz"`) and retries up to 10 s. Its health probe uses port 8800 even if you customize the API port.

## Guided setup

After opening MCD, choose **Setup wizard** in the header account menu or visit `/setup`. The [wizard guide](SETUP_WIZARD.md) covers host prerequisites, Google sign-in, Hermes and OpenClaw, OpenRouter credentials, subscription routes and Help. It does not install agents or grant execution permissions.

## Running the web (dev)

In a separate terminal:

```bash
cd apps/web
npm run dev
```

This starts Vite on loopback port 5173 and proxies API requests to loopback port 8800 (see `apps/web/vite.config.ts`). If you change these ports, update that configuration and the application request-guard settings together. The API serves the production build at `/` when the configured `MAC_CONTROL_WEB_DIST` directory exists; its default is `apps/web/dist`.

## Checks

From the repository root, run:

```bash
# API tests
(cd apps/api && .venv/bin/python -m pytest -q)

# Web type check, tests and production build
(cd apps/web && npm run type-check && npm test && npm run build)
```

Bootstrap installs locked dependencies and builds the frontend; tests check application behavior. Start `serve.py` separately to run MCD. Passing tests does not establish that your Google, agent or remote-access integrations are configured.

## LaunchAgent install

The LaunchAgent keeps the API running and restarts it on abnormal exit (`KeepAlive` with `SuccessfulExit` false; `RunAtLoad` true by default).

```bash
bash scripts/install-launchagent.sh
```

What the script does (verified from source):

1. Reads environment variables (`MAC_CONTROL_*` with safe defaults) to set `LABEL`, `PYTHON_PATH`, `WORKING_DIRECTORY`, `SERVE_SCRIPT`, `PATH`, `PYTHONUNBUFFERED`, `RUN_AT_LOAD`, `KEEP_ALIVE_SUCCESSFUL_EXIT`, `THROTTLE_INTERVAL`, `STDOUT_PATH`, `STDERR_PATH`.
2. Validates that `PYTHON_PATH` exists (must be `.venv/bin/python` after `bootstrap.sh`).
3. Validates the web build (`apps/web/dist/index.html` must exist; produced by `npm run build` in `bootstrap.sh`).
4. Renders `ops/launchd/com.operator.mac-control.plist.template` into `~/Library/LaunchAgents/com.operator.mac-control.plist` using `sed`.
5. Runs `plutil -lint` on the rendered `.plist`.
6. Removes the old job (`launchctl bootout`) with a 45 s wait loop.
7. Loads the new job (`launchctl bootstrap`) with one retry.
8. Confirms health (`curl http://127.0.0.1:8800/healthz`) within 10 s.

If the script reports `loaded ... but healthz did not answer`, check:
- `~/.mac-control/logs/api.err.log`
- That `.venv/bin/python` exists and `serve.py` starts without errors (`python serve.py` manually)
- That `apps/web/dist/index.html` exists (rerun `scripts/bootstrap.sh` if missing)

Uninstall or disable:

```bash
launchctl bootout gui/$(id -u)/com.operator.mac-control 2>/dev/null || true
rm ~/Library/LaunchAgents/com.operator.mac-control.plist
```

## Settings involved

- `MAC_CONTROL_HOST`, `MAC_CONTROL_PORT`, `MAC_CONTROL_DEV_PORT` — server bind and dev ports.
- `MAC_CONTROL_DATA_DIR` — `~/.mac-control` (default); holds `.env`, `alerts.toml`, `data.db`, `logs/`.
- `MAC_CONTROL_LOG_LEVEL` — `info` by default; affects LaunchAgent stdout/stderr logs.
- `MAC_CONTROL_AUTH_ENABLED` — defaults to false; must be enabled (with valid dotenv credentials and allowlists) before changing host from loopback.
- `MAC_CONTROL_PYTHON_PATH` — overrides Python binary for LaunchAgent (default: `.venv/bin/python` relative to repo).
- LaunchAgent settings (`MAC_CONTROL_LAUNCHD_LABEL`, `RUN_AT_LOAD`, `KEEP_ALIVE_SUCCESSFUL_EXIT`, `THROTTLE_INTERVAL`, `STDOUT_PATH`, `STDERR_PATH`) — exported shell variables read by `scripts/install-launchagent.sh`. The installer does not read `.env`; the Python app reads its own dotenv configuration at runtime.

See `docs/configuration/settings.md` and `docs/configuration/launchd.md` for full reference.

## Troubleshooting

- **`serve.py` refuses non-loopback bind** — `MAC_CONTROL_HOST` is set to a non-local address but auth (`google_client_id`, `google_client_secret`, `auth_allowed_emails`, `auth_origins`) is not configured. Either keep `MAC_CONTROL_HOST=127.0.0.1` or complete [Google sign-in configuration](configuration/google-sign-in.md).
- **`bootstrap.sh` fails on `pip check`** — dependency conflict in `.venv`; delete `.venv` and rerun `bootstrap.sh`.
- **Web build missing (`dist/index.html`)** — `npm run build` failed or `bootstrap.sh` was interrupted; rerun `bootstrap.sh` or `npm run build` manually in `apps/web`.
- **LaunchAgent does not load** — verify `.plist` syntax with `plutil -lint ~/Library/LaunchAgents/com.operator.mac-control.plist`; confirm `MAC_CONTROL_PYTHON_PATH` points to an executable Python.
- **Healthz fails** — confirm `serve.py` responds (`curl http://127.0.0.1:8800/healthz`); check `~/.mac-control/logs/api.err.log` for import or auth errors.
- **Port conflict on 8800 or 5173** — change the API `MAC_CONTROL_PORT` in its dotenv or environment. For Vite, update `apps/web/vite.config.ts` and keep its proxy and request-guard development port consistent.

## Related pages

- [Tested environments](tested-environments.md) — confirmed/untested platforms and versions
- [Overview](sections/overview.md)
- [Profile settings](sections/profile-settings.md)
- [Configuration / Settings](configuration/settings.md)
- [Configuration / LaunchAgent](configuration/launchd.md)
- [Configuration / Auth (Google)](configuration/auth-google.md)
- [Development tracking](development/CHANGELOG.md) · [Contributing](development/CONTRIBUTING.md) · [Security](development/SECURITY.md)
