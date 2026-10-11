#!/usr/bin/env bash
# Rebuild the API venv from the lock file and the web app from package-lock.json.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO}/apps/api"
[ -x .venv/bin/python ] || /opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -q -r requirements.lock.txt
.venv/bin/pip check
cd "${REPO}/apps/web"
npm ci --no-audit --no-fund
npm run build
