#!/usr/bin/env bash
# First-time install of a released Mac Control Dashboard (MCD) build on macOS arm64.
# Later upgrades belong to the in-app updater (Settings, Updates).
#
# Usage:
#   bootstrap-mcd.sh --version X.Y.Z --manifest-sha256 HEX [options]
#   bootstrap-mcd.sh --archive FILE --manifest FILE --manifest-sha256 HEX [options]
#
# Options:
#   --root DIR          install root (default: ~/Library/Application Support/MacControlDashboard)
#   --python PATH       absolute path to Python 3.12, the version the release pins
#   --manifest-sha256   SHA-256 of the .manifest.json, copied from the release page. Required:
#                       it is the trust anchor until a signing key is configured.
#   --allow-prerelease  required for a prerelease version or manifest
#   --port N            port the dashboard listens on (default 8800)
#   --label LABEL       LaunchAgent label (default com.operator.mac-control); the update
#                       supervisor is LABEL.update-recover
#   --data-dir DIR      data folder (default ~/.mac-control). If it already holds a database the
#                       install is refused unless --adopt-existing-data is given.
#   --adopt-existing-data
#                       use a data folder that already has data.db; data.db and .env are copied to
#                       <root>/state/first-install-backup first
#   --env NAME=VALUE    extra service environment variable (NAME is HOME or MAC_CONTROL_*); repeatable.
#                       Used by isolated previews, for example --env MAC_CONTROL_DISPATCHER_ENABLED=false
#   --dry-run           download/verify everything, print the plan, change nothing
#   -h, --help          show this help
#
# --version downloads mcd-X.Y.Z-darwin-arm64.tar.gz and .manifest.json from the public release
# vX.Y.Z of gptkiosk/mac-control-dashboard. No token is needed. Only HTTPS is used, and redirects
# must land on GitHub hosts. --archive/--manifest use local files instead.
#
# Verification happens before anything is installed: the manifest must match the pinned digest,
# the archive must match the manifest's size and SHA-256, the manifest must name product mcd and
# darwin-arm64, and every archive member must be a plain file or directory inside the release
# root. The packaged update helper then verifies the whole package again during staging.
#
# Layout: <root>/versions/<version>-<sha256[:12]>/ holds the release and its venv at runtime/.
# <root>/current is a symlink to it. The LaunchAgent runs <root>/current. Runtime data stays in
# the data folder and is never inside <root>.
#
# Installs two LaunchAgents in ~/Library/LaunchAgents: LABEL (the dashboard) and
# LABEL.update-recover (finishes or undoes an interrupted update). It refuses to run if LABEL is
# already loaded, so it can never replace a running dashboard.
# Needs: Python 3.12 with venv (brew install python@3.12), curl (for --version), macOS 14 or later.
set -euo pipefail

REPO_SLUG="gptkiosk/mac-control-dashboard"
PLATFORM="darwin-arm64"
MIN_MACOS_MAJOR=14
PORT=8800
LABEL="com.operator.mac-control"
ROOT="${MCD_INSTALL_ROOT:-$HOME/Library/Application Support/MacControlDashboard}"
DATA="${MAC_CONTROL_DATA_DIR:-$HOME/.mac-control}"
AGENT_DIR="$HOME/Library/LaunchAgents"

VERSION=""
ARCHIVE=""
MANIFEST=""
MANIFEST_SHA=""
PY_ARG=""
ALLOW_PRERELEASE=0
ADOPT=0
DRY_RUN=0
EXTRA_ENV=()

die() { echo "error: $*" >&2; exit 1; }
need_value() { [ $# -ge 2 ] || die "$1 needs a value"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) need_value "$@"; VERSION="$2"; shift 2 ;;
    --archive) need_value "$@"; ARCHIVE="$2"; shift 2 ;;
    --manifest) need_value "$@"; MANIFEST="$2"; shift 2 ;;
    --manifest-sha256) need_value "$@"; MANIFEST_SHA="$(printf '%s' "$2" | tr 'A-F' 'a-f')"; shift 2 ;;
    --root) need_value "$@"; ROOT="$2"; shift 2 ;;
    --python) need_value "$@"; PY_ARG="$2"; shift 2 ;;
    --port) need_value "$@"; PORT="$2"; shift 2 ;;
    --label) need_value "$@"; LABEL="$2"; shift 2 ;;
    --data-dir) need_value "$@"; DATA="$2"; shift 2 ;;
    --adopt-existing-data) ADOPT=1; shift ;;
    --env) need_value "$@"; EXTRA_ENV+=("$2"); shift 2 ;;
    --allow-prerelease) ALLOW_PRERELEASE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,37p' "$0"; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# --- arguments ----------------------------------------------------------------------------

SEMVER='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'
if [ -n "$VERSION" ]; then
  [ -z "$ARCHIVE" ] && [ -z "$MANIFEST" ] || die "use either --version or --archive with --manifest, not both"
  printf '%s' "$VERSION" | grep -Eq "$SEMVER" || die "--version must be X.Y.Z or X.Y.Z-pre"
  MODE=download
elif [ -n "$ARCHIVE" ] && [ -n "$MANIFEST" ]; then
  MODE=local
else
  die "give --version X.Y.Z, or --archive FILE --manifest FILE (see --help)"
fi
printf '%s' "$MANIFEST_SHA" | grep -Eq '^[0-9a-f]{64}$' \
  || die "--manifest-sha256 must be the 64-hex digest from the release page"
printf '%s' "$PORT" | grep -Eq '^[0-9]{2,5}$' && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] \
  || die "--port must be a number from 1024 to 65535"
printf '%s' "$LABEL" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$' || die "--label must be letters, digits and ._- only"

# Paths end up in plists and JSON; keep them to a plain character set (spaces are allowed in the
# root because macOS puts Application Support there).
valid_path() {
  case "$1" in /*) ;; *) return 1 ;; esac
  case "$1" in *[!A-Za-z0-9._/+:\ -]*) return 1 ;; esac
  case "$1" in *..*) return 1 ;; esac
}
valid_path "$ROOT" || die "--root must be an absolute path of letters, digits, spaces and ._/+:- only: $ROOT"
valid_path "$DATA" || die "--data-dir must be an absolute plain path: $DATA"

for pair in ${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"}; do
  printf '%s' "$pair" | grep -Eq '^(HOME|MAC_CONTROL_[A-Z0-9_]{1,60})=[^[:cntrl:]]{0,200}$' \
    || die "--env accepts HOME=... or MAC_CONTROL_...=... only: ${pair%%=*}"
  case "$pair" in
    MAC_CONTROL_DATA_DIR=*|MAC_CONTROL_PORT=*|MAC_CONTROL_UPDATE_ROOT=*) die "set ${pair%%=*} with its own option, not --env" ;;
  esac
done

# --- Python -------------------------------------------------------------------------------

# The release pins Python 3.12 (manifest runtime.python); the update helper refuses any other.
find_python() {
  local candidate found
  # An explicit --python is the only candidate; a bad path must not fall back to another interpreter.
  if [ -n "${PY_ARG}" ]; then
    set -- "${PY_ARG}"
  else
    set -- "${MCD_PYTHON:-}" /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.12
  fi
  for candidate in "$@"; do
    [ -n "${candidate}" ] || continue
    found="$(command -v "${candidate}" 2>/dev/null)" || continue
    [ "$("${found}" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "3.12" ] || continue
    printf '%s' "${found}"
    return 0
  done
  return 1
}
PY="$(find_python)" || die "Python 3.12 is required. Install it with: brew install python@3.12 (or pass --python PATH)"
case "$PY" in /*) ;; *) die "the Python path must be absolute: $PY" ;; esac
"$PY" -I -c 'import venv, ensurepip' 2>/dev/null \
  || die "$PY lacks venv/ensurepip; install a complete Python 3.12 (brew install python@3.12)"

# --- host ---------------------------------------------------------------------------------

[ "$(uname -s)" = Darwin ] || die "this installer is for macOS; it cannot run on $(uname -s)"
[ "$(uname -m)" = arm64 ] || die "the host must be arm64 (uname -m reports $(uname -m))"
MACOS_VERSION="$(sw_vers -productVersion 2>/dev/null || echo 0)"
[ "${MACOS_VERSION%%.*}" -ge "$MIN_MACOS_MAJOR" ] \
  || die "macOS ${MIN_MACOS_MAJOR} or later is required (found ${MACOS_VERSION})"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mcd-bootstrap.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fetch() { # Fetch one HTTPS hop at a time and validate its destination before the next request.
  local url="$1" dest="$2" max="${3:-104857600}" headers="${WORK}/headers.$$" body="${WORK}/body.$$" code location hop=0
  while [ "$hop" -le 5 ]; do
    case "$url" in https://github.com/*|https://objects.githubusercontent.com/*|https://release-assets.githubusercontent.com/*|https://github-releases.githubusercontent.com/*) ;; *) die "download URL uses an unexpected host: $url" ;; esac
    code="$(curl --silent --show-error --proto '=https' --tlsv1.2 --max-redirs 0 \
      --connect-timeout 15 --max-time 900 --speed-limit 1024 --speed-time 60 \
      --max-filesize "$max" --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$url")" \
      || die "download failed: $url"
    case "$code" in
      2*) mv "$body" "$dest"; rm -f "$headers"; return 0 ;;
      3*) # macOS awk has no IGNORECASE; match the header name with grep -i
          location="$(grep -i '^location:' "$headers" | tail -n 1 | sed -e 's/^[^:]*:[[:space:]]*//' -e 's/[[:space:]]*$//')"
          [ -n "$location" ] || die "redirect has no Location header: $url"
          case "$location" in https://*) url="$location" ;; *) die "redirect must use an absolute HTTPS URL: $location" ;; esac
          hop=$((hop + 1)) ;;
      *) die "download returned HTTP $code: $url" ;;
    esac
  done
  die "too many download redirects: $1"
}

if [ "$MODE" = download ]; then
  command -v curl >/dev/null 2>&1 || die "curl is required for --version"
  ASSET="https://github.com/${REPO_SLUG}/releases/download/v${VERSION}/mcd-${VERSION}-${PLATFORM}"
  fetch "${ASSET}.manifest.json" "$WORK/release.manifest.json" 1048576
  fetch "${ASSET}.tar.gz" "$WORK/release.tar.gz" 104857600
  MANIFEST="$WORK/release.manifest.json"
  ARCHIVE="$WORK/release.tar.gz"
fi
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
[ -f "$ARCHIVE" ] || die "archive not found: $ARCHIVE"

GOT_SHA="$(shasum -a 256 "$MANIFEST" | cut -d' ' -f1)"
[ "$GOT_SHA" = "$MANIFEST_SHA" ] || die "manifest sha256 is $GOT_SHA, not the pinned $MANIFEST_SHA; refusing this package"

# Package checks, run before the host is touched. Prints: version artifact-sha256 channel.
CHECK_PY='
import hashlib, json, re, sys, tarfile
manifest_path, archive_path, want, allow_pre = sys.argv[1:5]
problems = []
def need(ok, why):
    if not ok:
        problems.append(why)
try:
    with open(manifest_path, "rb") as f:
        m = json.loads(f.read().decode("utf-8"))
except (OSError, ValueError) as exc:
    sys.exit("error: manifest is not valid JSON: %s" % exc)
if not isinstance(m, dict):
    sys.exit("error: manifest is not a JSON object")
need(m.get("schema") == "dashboard-release-manifest/v1", "manifest schema is not dashboard-release-manifest/v1")
need(m.get("product") == "mcd", "manifest is for product %r, not mcd: cross-product packages are refused" % (m.get("product"),))
plat = m.get("platform") if isinstance(m.get("platform"), dict) else {}
need(plat.get("key") == "darwin-arm64" and plat.get("os") == "darwin" and plat.get("arch") == "arm64",
     "manifest is not for darwin-arm64")
version = m.get("version") if isinstance(m.get("version"), str) else ""
need(re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?", version) is not None,
     "manifest version is not X.Y.Z")
channel = m.get("channel")
need(channel in ("stable", "prerelease"), "manifest channel is %r; only stable or prerelease packages install" % (channel,))
need(channel != "prerelease" or allow_pre == "1", "a prerelease needs --allow-prerelease")
src = m.get("source") if isinstance(m.get("source"), dict) else {}
need(src.get("release_eligible") is True, "manifest was not built from a clean committed tree")
need(not want or want == version, "manifest version %s is not the requested %s" % (version, want))
base = "mcd-%s-darwin-arm64" % version
art = m.get("artifact") if isinstance(m.get("artifact"), dict) else {}
need(art.get("name") == base + ".tar.gz" and art.get("root") == base,
     "artifact name or root does not match version %s" % version)
with open(archive_path, "rb") as f:
    data = f.read()
need(art.get("size") == len(data), "archive is %d bytes; the manifest says %r" % (len(data), art.get("size")))
need(art.get("sha256") == hashlib.sha256(data).hexdigest(), "archive sha256 differs from the manifest")
if not problems:
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            count = 0
            for mem in tf:
                count += 1
                parts = mem.name.split("/")
                bad = (not (mem.isreg() or mem.isdir()) or mem.name.startswith("/") or ".." in parts
                       or "\\" in mem.name or parts[0] != base or (mem.mode & 0o6000))
                if bad or count > 5000:
                    problems.append("archive member refused: %r" % (mem.name,))
                    break
    except tarfile.TarError as exc:
        problems.append("archive is not a valid tar.gz: %s" % exc)
if problems:
    for p in problems:
        sys.stderr.write("error: %s\n" % p)
    sys.exit(1)
print(version, art["sha256"], channel)
'
PACKAGE_INFO="$("$PY" -I -c "$CHECK_PY" "$MANIFEST" "$ARCHIVE" "$VERSION" "$ALLOW_PRERELEASE")" \
  || die "package refused; nothing was installed"
read -r VERSION ART_SHA CHANNEL <<< "$PACKAGE_INFO"
BASE="mcd-${VERSION}-${PLATFORM}"
VID="${VERSION}-${ART_SHA:0:12}"
echo "package  ${BASE}.tar.gz  sha256 ${ART_SHA}  channel ${CHANNEL}  manifest pinned"

# --- existing-install checks --------------------------------------------------------------

DOMAIN="gui/$(id -u)"
RECOVER_LABEL="${LABEL}.update-recover"
PLIST="$AGENT_DIR/${LABEL}.plist"
RECOVER_PLIST="$AGENT_DIR/${RECOVER_LABEL}.plist"
command -v launchctl >/dev/null 2>&1 || die "launchctl not found"
[ ! -e "$ROOT/current" ] && [ ! -L "$ROOT/current" ] || die "$ROOT/current already exists; MCD is installed there. Upgrade with the in-app updater."
[ ! -e "$PLIST" ] || die "$PLIST already exists; refusing to replace it"
[ ! -e "$RECOVER_PLIST" ] || die "$RECOVER_PLIST already exists; refusing to replace it"
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  die "the LaunchAgent $LABEL is already loaded (a dashboard is running); this installer never replaces it. Use another --label and --port, or move that install to managed updates deliberately (docs/install/driver-to-managed.md)"
fi
if launchctl print "$DOMAIN/$RECOVER_LABEL" >/dev/null 2>&1; then
  die "the LaunchAgent $RECOVER_LABEL is already loaded; refusing to replace it"
fi
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
  die "something already answers on 127.0.0.1:${PORT}; stop it or pass another --port"
fi
if [ -e "$DATA/data.db" ] && [ "$ADOPT" != 1 ]; then
  die "$DATA already holds a database. This installer does not take over existing data unless you pass --adopt-existing-data (a copy of data.db and .env is kept first)"
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "dry run: nothing was changed. A real run would:"
  echo "  - stage ${VID} under ${ROOT}/versions and point ${ROOT}/current at it (Python ${PY})"
  echo "  - write ${ROOT}/helper/helper.json (trust: pinned-digest) and the update helper"
  echo "  - use the data folder ${DATA}$([ -e "$DATA/data.db" ] && echo ' (existing data adopted; data.db and .env copied first)')"
  echo "  - install ${PLIST} and ${RECOVER_PLIST}, then load them"
  echo "  - check http://127.0.0.1:${PORT}/healthz"
  exit 0
fi

# --- install ------------------------------------------------------------------------------

mkdir -p "$ROOT/helper" "$ROOT/inbox" "$ROOT/versions" "$ROOT/state" "$DATA" "$AGENT_DIR"
chmod 700 "$ROOT" "$ROOT/helper" "$ROOT/inbox" "$ROOT/versions" "$ROOT/state" "$DATA"

if [ "$ADOPT" = 1 ] && [ -e "$DATA/data.db" ]; then
  BACKUP="$ROOT/state/first-install-backup"
  mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
  cp -p "$DATA/data.db" "$BACKUP/data.db"
  [ ! -e "$DATA/.env" ] || { cp -p "$DATA/.env" "$BACKUP/.env"; chmod 600 "$BACKUP/.env"; }
  echo "kept a copy of the existing data.db and .env in $BACKUP"
fi

mkdir "$WORK/tree"
tar -xzf "$ARCHIVE" -C "$WORK/tree" --no-same-owner --no-same-permissions
SRC="$WORK/tree/${BASE}"
[ -f "$SRC/apps/api/update_helper.py" ] || die "the archive has no update helper"

# The helper is the only code that stages or switches; it runs from this pinned copy. Every module
# the helper imports, and the recovery CLI, must be here: update_helper imports release_fetch at load.
for f in update_helper.py update_engine.py release_fetch.py release_verify.py update_recovery.py; do
  [ -f "$SRC/apps/api/$f" ] || die "the archive has no $f"
  cp "$SRC/apps/api/$f" "$ROOT/helper/$f"
  chmod 600 "$ROOT/helper/$f"
done

CONFIG_PY='
import json, os, sys
path, root, db, python, health, prerelease, label, plist = sys.argv[1:9]
cfg = {"schema": "dashboard-update-helper/v1", "product": "mcd", "platform": "darwin-arm64",
       "root": root, "db_path": db, "health_url": health, "python": python,
       "service": {"kind": "launchd", "label": label, "plist": plist},
       "trust": {"kind": "pinned-digest"}, "readiness_timeout_s": 90, "keep_versions": 3,
       "allow_prerelease": prerelease == "1", "allow_downgrade": False}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(cfg, f, indent=2, sort_keys=True)
    f.write("\n")
'
"$PY" -I -c "$CONFIG_PY" "$ROOT/helper/helper.json" "$ROOT" "$DATA/data.db" "$PY" \
  "http://127.0.0.1:${PORT}/healthz" "$ALLOW_PRERELEASE" "$LABEL" "$PLIST"

HELPER=("$PY" -I "$ROOT/helper/update_helper.py" --config "$ROOT/helper/helper.json")
cp "$ARCHIVE" "$ROOT/inbox/${BASE}.tar.gz"
cp "$MANIFEST" "$ROOT/inbox/${BASE}.manifest.json"
chmod 600 "$ROOT/inbox/${BASE}.tar.gz" "$ROOT/inbox/${BASE}.manifest.json"

STAGED="$("${HELPER[@]}" stage "$BASE" --manifest-sha256 "$MANIFEST_SHA")" \
  || { echo "$STAGED" >&2; die "staging refused the package; nothing was switched"; }
printf '%s' "$STAGED" | grep -q '"ok": true' || { echo "$STAGED" >&2; die "staging did not succeed"; }
[ -d "$ROOT/versions/$VID" ] || die "expected staged version directory $ROOT/versions/$VID"

"${HELPER[@]}" activate-initial "$VID" >/dev/null \
  || die "activate-initial failed; $ROOT/current was not created"

# The inbox copies were only needed for staging. Left there they would make the in-app updater refuse to
# fetch the same version again ("already in the inbox") and hold the disk for nothing.
rm -f "$ROOT/inbox/${BASE}.tar.gz" "$ROOT/inbox/${BASE}.manifest.json"

# Plists come from the activated version, so they match the code they start.
TEMPLATES="$ROOT/current/ops/launchd"
mkdir -p "$DATA/logs"; chmod 700 "$DATA/logs"

render_service() { # writes $PLIST from the packaged template, then adds the deployment environment
  sed -e "s|__LABEL__|${LABEL}|g" -e "s|__PYTHON_PATH__|${ROOT}/current/runtime/bin/python|g" \
      -e "s|__SERVE_SCRIPT__|serve.py|g" -e "s|__WORKING_DIRECTORY__|${ROOT}/current/apps/api|g" \
      -e "s|__PATH__|${PATH}|g" -e "s|__PYTHONUNBUFFERED__|1|g" \
      -e "s|__RUN_AT_LOAD__|<true/>|g" -e "s|__KEEP_ALIVE_SUCCESSFUL_EXIT__|<false/>|g" \
      -e "s|__THROTTLE_INTERVAL__|10|g" -e "s|__STDOUT_PATH__|${DATA}/logs/api.out.log|g" \
      -e "s|__STDERR_PATH__|${DATA}/logs/api.err.log|g" \
      "$TEMPLATES/com.operator.mac-control.plist.template" > "$PLIST.tmp"
  if grep -q '__[A-Z_]*__' "$PLIST.tmp"; then rm -f "$PLIST.tmp"; die "unrendered placeholder in the service template"; fi
  # plistlib escapes folder names correctly, including spaces and XML characters.
  "$PY" -I - "$PLIST.tmp" "$DATA" "$ROOT" "$PORT" ${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"} <<'PYCONFIG'
import plistlib
import sys
path, data, root, port, *extra = sys.argv[1:]
with open(path, "rb") as file:
    config = plistlib.load(file)
values = config["EnvironmentVariables"]
values["MAC_CONTROL_DATA_DIR"] = data
values["MAC_CONTROL_UPDATE_ROOT"] = root
values["MAC_CONTROL_PORT"] = port
for pair in extra:
    name, _, value = pair.partition("=")
    values[name] = value
with open(path, "wb") as file:
    plistlib.dump(config, file)
PYCONFIG
  plutil -lint "$PLIST.tmp" >/dev/null || die "the rendered service plist is not valid"
  chmod 644 "$PLIST.tmp"; mv "$PLIST.tmp" "$PLIST"
}

render_recover() {
  sed -e "s|com.operator.mac-control.update-recover|${RECOVER_LABEL}|g" \
      -e "s|__UPDATE_ROOT__|${ROOT}|g" -e "s|__PYTHON_PATH__|${PY}|g" \
      "$TEMPLATES/com.operator.mac-control.update-recover.plist.template" > "$RECOVER_PLIST.tmp"
  if grep -q '__[A-Z_]*__' "$RECOVER_PLIST.tmp"; then rm -f "$RECOVER_PLIST.tmp"; die "unrendered placeholder in the recovery template"; fi
  plutil -lint "$RECOVER_PLIST.tmp" >/dev/null || die "the rendered recovery plist is not valid"
  chmod 644 "$RECOVER_PLIST.tmp"; mv "$RECOVER_PLIST.tmp" "$RECOVER_PLIST"
}

render_service
render_recover
launchctl bootstrap "$DOMAIN" "$PLIST" || die "launchctl could not load $PLIST"
launchctl kickstart "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$RECOVER_PLIST" || die "launchctl could not load $RECOVER_PLIST"

for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "installed MCD ${VERSION} (${VID}) under ${ROOT}; ${LABEL} healthz OK on 127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 0.5
done
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "$DOMAIN/$RECOVER_LABEL" >/dev/null 2>&1 || true
die "installed ${VERSION} but healthz did not answer within 20 s, so both LaunchAgents were unloaded. This is a first install, so there is no previous version to roll back to. Inspect ${DATA}/logs/api.err.log. Remove it with the steps in docs/install/uninstall-troubleshooting.md"
