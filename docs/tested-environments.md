# Tested environments

## Purpose

Reference support matrix for the mac-control dashboard (MCD). Confirmed environment: the Mac mini M4 that runs the local control center (developer, ops, and public docs target). Untested platforms are listed so a new user knows what is not verified. This page supports install, troubleshooting and contribution decisions.

## Screenshots

Placeholder (not a UI capture; environment checklist).

- Pending capture: `tested-environments-checklist.png`

## Controls

None — reference page. The settings that affect environment behavior are listed under Settings involved.

## Settings involved

- `MAC_CONTROL_HOST` — bind address (default `127.0.0.1`)
- `MAC_CONTROL_PORT` — server port (default `8800`)
- `MAC_CONTROL_DEV_PORT` — Vite dev server (default `5173`)
- `MAC_CONTROL_DATA_DIR` — local data directory (`~/.mac-control`)
- `MAC_CONTROL_LOG_LEVEL` — logging level (`info`)

These keys are loaded from `.env` (see `configuration/environment.md`) and control how the API and LaunchAgent behave on the target machine.

## Tested platforms

### Confirmed (primary)

| Component | Version / value | Source / note |
|---|---|---|
| Hardware | Mac mini M4 (Mac16,10) | Apple M4 chip, 4P + 6E cores, 16 GB RAM |
| macOS | 27.0.1 (Build 26A434) | `sw_vers` |
| Kernel | Darwin 27.0.0 (RELEASE_ARM64_T8132) | `uname -a` |
| Python (API) | 3.12.13 (`/opt/homebrew/bin/python3.12`) | `python3 --version` shows 3.14.6 system; the venv uses Homebrew 3.12 |
| Virtualenv | `.venv` under `apps/api` | rebuilt by `scripts/bootstrap.sh` |
| Node (web) | v22.22.3 | `node --version` |
| npm | 10.9.8 | `npm --version` |
| Web build | `npm ci` + `npm run build` (Vue 3, Vite, TypeScript) | `apps/web/package.json` v0.1.0 |
| LaunchAgent label | `com.operator.mac-control` | `ops/launchd/com.operator.mac-control.plist.template` |
| Service ports | 8800 (API + web), 5173 (dev) | `serve.py`, `settings.py` |
| Auth | Disabled by default (`MAC_CONTROL_AUTH_ENABLED=false`) | `settings.py` Phase 4 |

Verified commands on this host:

```bash
bash -n scripts/bootstrap.sh          # syntax OK
bash -n scripts/install-launchagent.sh  # syntax OK
/opt/homebrew/bin/python3.12 --version  # 3.12.13
node --version                           # v22.22.3
npm --version                            # 10.9.8
sw_vers                                  # macOS 27.0.1
```

### Untested / not verified

| Platform | Status | Note |
|---|---|---|
| macOS < 27 (e.g. Tahoe 26.x) | Untested | `serve.py` uses `ipaddress` from stdlib; should work on any Python 3.12+ macOS |
| Intel Mac (x86_64) | Untested | Build scripts are architecture-neutral; LaunchAgent template has no ARM-specific keys |
| Linux (Ubuntu, Fedora, etc.) | Untested | FastAPI + Vue stack is portable; `macmon`, `tailscale_path`, `disk_path` assume macOS binaries and `/System/Volumes/Data` |
| Windows | Untested | LaunchAgent (`.plist`) and `macmon` references are macOS-only |
| Python 3.14 (system) | Untested for venv | System Python 3.14.6 exists; the app's `.venv` is pinned to Homebrew 3.12 (`bootstrap.sh` creates `.venv` with `/opt/homebrew/bin/python3.12`) |
| Node < 22 | Untested | `package-lock.json` pinned; `npm ci` expects the locked tree |

## Troubleshooting

- **Port 8800 already in use** — check `lsof -i :8800`; change `MAC_CONTROL_PORT` or stop the conflicting service before running `serve.py`.
- **Port 5173 conflict (dev)** — `MAC_CONTROL_DEV_PORT` defaults to 5173; adjust if another Vite instance is running.
- **Tailscale not reachable on 9443** — `serve.py` binds to `127.0.0.1` by default; remote access requires an operator-configured HTTPS endpoint. See `docs/configuration/auth-google.md` for Phase 4 auth setup.
- **`.env` missing** — `scripts/bootstrap.sh` does not create `.env`; copy `.env.example` or create `~/.mac-control/.env` manually. Without auth keys the server refuses non-loopback binds (`serve.py`).
- **LaunchAgent fails** — `scripts/install-launchagent.sh` reports `loaded ... but healthz did not answer` if the API does not respond within 10 s. Check `~/.mac-control/logs/api.err.log` and verify the web build exists (`apps/web/dist/index.html`).
- **Python version mismatch** — the venv uses `/opt/homebrew/bin/python3.12`. If that binary is missing, `bootstrap.sh` creates the venv automatically but `serve.py` will fail. Confirm `/opt/homebrew/bin/python3.12` exists before running the LaunchAgent.

## Related pages

- [Getting started](getting-started.md) — prerequisites, bootstrap, running, LaunchAgent
- [Configuration / Settings](configuration/settings.md) — `MAC_CONTROL_*` keys
- [Configuration / Environment](configuration/environment.md) — `.env`, dispatcher environment
- [Configuration / LaunchAgent](configuration/launchd.md) — `.plist` template and install
- [Development tracking](development/CHANGELOG.md) · [Contributing](development/CONTRIBUTING.md)
