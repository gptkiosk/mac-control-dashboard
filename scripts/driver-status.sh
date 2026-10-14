#!/bin/bash
# Am I on the latest? Prints what is running, what the checkout is on, and the newest tag at a source.
#   scripts/driver-status.sh [--from PATH_OR_URL] [--driver DIR] [--port N]
set -uo pipefail
driver="${MCD_DRIVER_DIR:-$HOME/mcd-driver}"; from=""; port="${MCD_PORT:-8800}"; curl_bin="${MCD_CURL:-curl}"
while [ $# -gt 0 ]; do case "$1" in --from) from="$2"; shift 2;; --driver) driver="$2"; shift 2;; --port) port="$2"; shift 2;; *) echo "unknown option $1" >&2; exit 2;; esac; done
h="$("$curl_bin" -s -m 3 "http://127.0.0.1:$port/healthz" 2>/dev/null || true)"
rv="$(printf '%s' "$h" | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"; rs="$(printf '%s' "$h" | sed -n 's/.*"git_sha":"\([^"]*\)".*/\1/p')"
cs="$(git -C "$driver" rev-parse --short HEAD 2>/dev/null)"; ct="$(git -C "$driver" describe --tags --exact-match 2>/dev/null || echo '-')"
dirty="no"; [ -z "$(git -C "$driver" status --porcelain --untracked-files=no 2>/dev/null)" ] || dirty="YES"
echo "running:   v${rv:-?} @ ${rs:-not answering}"
echo "checkout:  $cs (tag: $ct), modified: $dirty"
[ -z "$rv" ] || [ "$rs" = "$cs" ] || echo "WARNING: the running commit differs from the checkout; restart or upgrade to align them"
src="${from:-origin}"
latest="$(git -C "$driver" ls-remote --tags --refs "$src" 2>/dev/null | sed 's#.*refs/tags/##' | grep -E '^(v[0-9]|driver-)' | sort -V | tail -n 1)"
if [ -z "$latest" ]; then echo "latest:    (no tags reachable at ${from:-origin})"; exit 0; fi
lc="$(git -C "$driver" ls-remote --tags "$src" "refs/tags/$latest^{}" "refs/tags/$latest" 2>/dev/null | tail -n 1 | cut -c1-7)"
echo "latest:    $latest ($lc)"
if [ "$lc" = "$cs" ]; then echo "status:    up to date"; else echo "status:    NOT the newest tag; upgrade with: scripts/upgrade-driver.sh --ref $latest${from:+ --from $from}"; fi
