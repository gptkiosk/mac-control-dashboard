#!/bin/bash
# Upgrade the running MCD (a git checkout the LaunchAgent runs from) to a tag, safely.
#
#   scripts/upgrade-driver.sh --ref driver-2026-10-13.3 [--from PATH_OR_URL] [--driver DIR] [--dry-run]
#
# Preflight (clean checkout, nothing running, the tag exists and carries release notes), backup
# (database, environment file, previous commit), checkout, dependency sync only when a lock changed,
# web build, restart, then a health check that must report exactly the new commit and version. Any
# failure puts the previous commit back and restarts it. A receipt is written either way.
set -euo pipefail

ref=""; from=""; driver="${MCD_DRIVER_DIR:-$HOME/mcd-driver}"; data="${MAC_CONTROL_DATA_DIR:-$HOME/.mac-control}"
label="${MCD_LAUNCHD_LABEL:-com.operator.mac-control}"; port="${MCD_PORT:-8800}"; dry=0; force_busy=0
launchctl_bin="${MCD_LAUNCHCTL:-launchctl}"; curl_bin="${MCD_CURL:-curl}"; npm_bin="${MCD_NPM:-npm}"; uv_bin="${MCD_UV:-uv}"
wait_s="${MCD_HEALTH_WAIT_S:-45}"
while [ $# -gt 0 ]; do case "$1" in
  --ref) ref="$2"; shift 2;; --from) from="$2"; shift 2;; --driver) driver="$2"; shift 2;;
  --dry-run) dry=1; shift;; --force-busy) force_busy=1; shift;;
  -h|--help) sed -n 2,11p "$0"; exit 0;; *) echo "unknown option $1" >&2; exit 2;; esac; done
[ -n "$ref" ] || { echo "--ref is required (a tag such as driver-2026-10-13.3 or v0.2.0)" >&2; exit 2; }
[[ "$ref" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "unsafe ref" >&2; exit 2; }
say() { printf '%s\n' "$*"; }
die() { say "upgrade: $*" >&2; exit 1; }
g() { git -C "$driver" "$@"; }

# ---- preflight
[ -d "$driver/.git" ] || die "$driver is not a git checkout"
[ -z "$(g status --porcelain --untracked-files=no)" ] || die "the driver has uncommitted changes; refusing to overwrite them"
previous="$(g rev-parse HEAD)"; previous_short="$(g rev-parse --short HEAD)"
if [ -f "$data/data.db" ] && command -v sqlite3 >/dev/null 2>&1 && [ "$force_busy" = 0 ]; then
  busy="$(sqlite3 -readonly "$data/data.db" "select count(*) from run where stage in ('running','starting')" 2>/dev/null || echo 0)"
  [ "${busy:-0}" = 0 ] || die "$busy run(s) in progress; wait for them, or pass --force-busy (they would be interrupted)"
fi
src="${from:-origin}"
if [ -n "$from" ]; then g remote remove upgrade-src >/dev/null 2>&1 || true; g remote add upgrade-src "$from"; src=upgrade-src; fi
trap '[ -z "$from" ] || g remote remove upgrade-src >/dev/null 2>&1 || true' EXIT
g fetch -q "$src" --tags "+refs/tags/$ref:refs/tags/$ref" 2>/dev/null || g fetch -q "$src" --tags || die "could not fetch $ref from $src"
target="$(g rev-parse --verify -q "refs/tags/$ref^{commit}" || g rev-parse --verify -q "$ref^{commit}")" || die "$ref was not found"
target_short="$(g rev-parse --short "$target")"
version="$(g show "$target:apps/api/version.py" | sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' | head -n 1)"
[ -n "$version" ] || die "$ref has no apps/api/version.py version"
if [ "$target" = "$previous" ]; then say "already on $ref ($target_short, v$version)"; exit 0; fi
g show "$target:CHANGELOG.md" 2>/dev/null | grep -Eq "^## \[$version\] - [0-9]{4}-[0-9]{2}-[0-9]{2}" || say "warning: $ref has no dated CHANGELOG section for v$version"
say "upgrade: v$(g show "$previous:apps/api/version.py" | sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' | head -n 1) ($previous_short) -> v$version ($target_short, $ref)"
changed() { ! g diff --quiet "$previous" "$target" -- "$1" 2>/dev/null; }
sync_api=0; sync_mcp=0; sync_web=0
changed apps/api/requirements.lock.txt && sync_api=1
changed apps/mcp/requirements.lock.txt && sync_mcp=1
changed apps/web/package-lock.json && sync_web=1
say "plan: backup, checkout, deps api=$sync_api mcp=$sync_mcp web=$sync_web, build web, restart $label, verify $target_short v$version"
[ "$dry" = 0 ] || { say "dry run: nothing changed"; exit 0; }

# ---- backup
stamp="$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$data/upgrades"; chmod 700 "$data/upgrades"
backup="$data/upgrades/$stamp"; mkdir -p "$backup"; chmod 700 "$backup"
[ ! -f "$data/data.db" ] || { command -v sqlite3 >/dev/null 2>&1 && sqlite3 "$data/data.db" ".backup '$backup/data.db'" || cp -p "$data/data.db" "$backup/data.db"; }
[ ! -f "$data/.env" ] || cp -p "$data/.env" "$backup/env"
say "backup: $backup"

receipt() { # result rolled_back
  printf '{"result":"%s","rolled_back":%s,"from":{"commit":"%s"},"to":{"ref":"%s","commit":"%s","version":"%s"},"backup":"%s","at":"%s"}\n' \
    "$1" "$2" "$previous" "$ref" "$target" "$version" "$backup" "$stamp" > "$data/upgrades/$stamp.json"; }
healthy() { # sha version
  local h; h="$("$curl_bin" -s -m 3 "http://127.0.0.1:$port/healthz" 2>/dev/null || true)"
  printf '%s' "$h" | grep -q '"status":"ok"' && printf '%s' "$h" | grep -q "\"git_sha\":\"$1\"" && printf '%s' "$h" | grep -q "\"version\":\"$2\""; }
wait_healthy() { local i=0; while [ "$i" -lt "$wait_s" ]; do healthy "$1" "$2" && return 0; sleep 1; i=$((i+1)); done; return 1; }
restart() { "$launchctl_bin" kickstart -k "gui/$(id -u)/$label" >/dev/null 2>&1 || return 1; }
deps() { # ref-dir flags
  [ "$1" = 1 ] && ( cd "$driver/apps/api" && "$uv_bin" pip sync -q --python .venv/bin/python requirements.lock.txt )
  [ "$2" = 1 ] && ( cd "$driver/apps/mcp" && "$uv_bin" pip sync -q --python .venv/bin/python requirements.lock.txt )
  [ "$3" = 1 ] && ( cd "$driver/apps/web" && "$npm_bin" ci --no-audit --no-fund --silent )
  ( cd "$driver/apps/web" && "$npm_bin" run build >/dev/null ); }

# ---- apply, verify, roll back on any failure
rollback() {
  say "upgrade FAILED at: $1. Restoring $previous_short"
  g checkout -q "$previous" && deps "$sync_api" "$sync_mcp" "$sync_web" || true
  restart || true
  if wait_healthy "$previous_short" "$(g show "$previous:apps/api/version.py" | sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' | head -n 1)"; then say "rolled back and healthy on $previous_short"; else say "WARNING: could not confirm health after rollback; check $label and $backup"; fi
  receipt failed true; exit 1; }
g checkout -q "$target" || rollback "checkout"
deps "$sync_api" "$sync_mcp" "$sync_web" || rollback "dependencies or web build"
restart || rollback "restart"
wait_healthy "$target_short" "$version" || rollback "health check (expected $target_short v$version)"
receipt ok false
say "upgraded: v$version ($target_short). Receipt: $data/upgrades/$stamp.json"
