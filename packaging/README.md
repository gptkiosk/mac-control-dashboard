# Release packaging

`scripts/release/release.py` turns this source tree into one versioned, OS/arch-specific
archive plus a manifest. It uses only the Python standard library; run it with `python3 -I`.

| Product | Platform key   | Python | Artifact                              |
|---------|----------------|--------|---------------------------------------|
| MCD     | `darwin-arm64` | 3.12   | `mcd-<version>-darwin-arm64.tar.gz`   |
| RCD     | `linux-arm64`  | 3.11   | `rcd-<version>-linux-arm64.tar.gz`    |

`packaging/product.json` names the product, its repository, its platform and the explicit
file allowlist. Anything not listed there is not shipped.

## Commands

```sh
python3 -I scripts/release/release.py lock                 # needs uv and PyPI access
python3 -I scripts/release/release.py build [--dev]        # -> dist-release/
python3 -I scripts/release/release.py repro [--dev]        # build twice, compare digests
python3 -I scripts/release/release.py verify dist-release/<name>.manifest.json
python3 -I scripts/release/release.py scan   dist-release/<name>.tar.gz [--gitleaks on]
```

- **lock** resolves `apps/api/requirements.runtime.in`, constrained to the known-good
  `requirements.lock.txt`, into `apps/api/locks/<platform>.txt`. Every package is pinned
  with `==` and sha256 hashes, and only wheels are allowed, so installs never run package
  build scripts. Commit the lock files; builds refuse to run without them.
- **build** refuses a dirty or unversioned tree unless `--dev` is given. A `--dev` artifact is
  marked `channel: dev` and `release_eligible: false`, and must never be offered as an update.
  The web UI is built with `npm ci --ignore-scripts` from `apps/web/package-lock.json` in a
  temporary copy; `apps/web` itself is not touched. `--skip-web-build` packages the
  existing `apps/web/dist` instead and records `web_build: prebuilt`.
- Every build verifies its own output and runs the content scan. If the scan finds
  anything, the archive is renamed `*.rejected` and the build fails.

## What an artifact contains

```
<product>-<version>-<platform>/
  manifest.json                        file list: path, sha256, size, mode
  BUILD_INFO.json                      product, version, platform, source commit, channel
  packaging/product.json
  apps/api/...                         API source and migrations
  apps/api/requirements.release.txt    the hash-pinned lock for this platform
  apps/web/dist/...                    built UI (no source maps)
  integrations/..., ops/...            only the files product.json allows
  LICENSE, THIRD_PARTY_NOTICES.md, README.md, CHANGELOG.md, SECURITY.md
```

Next to it, `<name>.manifest.json` (schema `packaging/release-manifest.schema.json`) records the
artifact sha256 and size, the inner manifest digest, the full file list, the lock digest and
pinned packages, the source commit and tree digest, and the build tool versions.
`SHA256SUMS` covers every archive and manifest in the output directory.

Python packages are not bundled. The installer creates a venv and runs
`pip install --require-hashes --only-binary :all: -r apps/api/requirements.release.txt`.

## Never in an artifact

- **Secrets:** `.env` files, keys, tokens, OAuth client files and credential stores.
- **Runtime data:** databases, logs, runs, reports and backups. Runtime data lives in the data
  directory (`~/.mac-control` or `~/.rcd-control`), outside the install.
- **Host identities:** the build user, host name, home directory and repository path, LAN and
  tailnet addresses, and real email addresses. Extra strings can be added with
  `RELEASE_SCAN_IDENTITIES` (one per line) or `scan --identity`.
- **Development material:** tests, docs, scripts, `node_modules`, venvs, caches, source maps
  and `apps/mcp`.

The scan checks paths, known secret formats and those identity strings, and runs `gitleaks dir`
when it is installed. A content-rule false positive can be accepted only through a reviewed
entry in `packaging/scan-allowlist.json` (`path`, `rule`, `reason`). Private keys, GitHub
tokens, host identities and forbidden paths can never be allowlisted.

## Reproducibility

Entries are sorted, with owner 0:0, fixed modes (0644, or 0755 for directories and
executables) and mtime `SOURCE_DATE_EPOCH`. The gzip header carries no name or time.
`SOURCE_DATE_EPOCH` comes from `--source-date-epoch`, the environment, or the commit time of a
clean checkout. A dirty dev tree falls back to the newest source file mtime.

Builds are expected to match byte for byte when they use the same source, lock,
`package-lock.json`, Node/npm and Python (zlib) versions. `repro` writes `repro-report.json`
and lists any files whose contents differ. If the contents match but the digest does not, the
difference is in the compression.

## Verifying before install

`apps/api/release_verify.py` is the verifier that the updater and recovery CLI use. It uses only
the standard library and doesn't depend on the rest of the app. Before anything from a package
is written or run, it checks the following, and refuses the package if any check fails or
cannot complete:

- **Authenticity:** the manifest bytes must carry an SSH signature (namespace
  `dashboard-release`) from a pinned allowed-signers file, or match a manifest digest pinned
  through a separately verified channel. With no authenticity check configured, every package
  is refused. The trust model itself is still a human decision (h5-trust-model).
- **Release identity:**
  - It must be the official repository for the product; forks need opt-in.
  - The product and platform (os and arch) must match, and so must this host.
  - Prereleases need opt-in. Dev builds are never update candidates.
  - Reinstalling the same version and downgrading each need opt-in.
- **Size:** the manifest, the artifact, each file, the expanded total and the member count are
  all capped. A decompression bomb stops at the cap.
- **Archive members:** only regular files and directories inside the release root are allowed.
  Refused: `..`, absolute paths, backslashes, symlinks, hardlinks, devices, sparse members,
  setuid and other unexpected modes, duplicate or case-colliding names, and a file that is also
  used as a directory.
- **Contents:** the inner manifest, every file's digest, size and mode, the dependency lock and
  `BUILD_INFO.json` must all match the release manifest.

`extract()` writes only the verified bytes, already held in memory, into a new staging
directory. It uses no-follow opens and never reads the archive from disk a second time.

## Managed updates

`apps/api/update_engine.py` installs verified packages and `apps/api/update_helper.py` is the
host helper that runs it. Both use only the standard library. The helper is the only process
that stages, switches or recovers an install. The API never does.

**Who gets managed updates.** Only a packaged install whose `BUILD_INFO.json` is a stable or
prerelease build, run from `<update root>/current`. A source checkout, a dev or dirty build, or a
package run from anywhere else gets the manual steps in `GET /api/updates` and nothing else.

**Layout** (one owner-only root; every directory is a real directory owned by the service user):

```
<root>/versions/<version>-<sha12>/   immutable once its receipt is written (write bits removed)
<root>/current  -> versions/<id>     the service runs <root>/current/runtime/bin/python serve.py
<root>/previous -> versions/<id>
<root>/inbox/                        packages: <base>.tar.gz, <base>.manifest.json[, .sig]
<root>/helper/                       update_helper.py, update_recovery.py, update_engine.py, release_verify.py, helper.json
<root>/state/                        install.json journal, lock, backups/, history.jsonl, helper.log
```

**Steps and their guarantees.**
- **Stage:** the package is verified (see above), extracted into a new version directory, given
  its own `runtime/` virtualenv (Python must match the manifest; the lock installs with
  `--require-hashes --only-binary :all: --no-deps`, so no package build script runs), then
  sealed. A version only counts as staged once its receipt is written and sealed.
- **Apply:** refused while any agent or chat run is live, a run waits on a human decision, a
  task is queued or running, a project is dispatching, or an approved task has not started.
  The operator drains them; nothing is stopped or cancelled for them. The service is then
  stopped, the drain check runs again (work that slipped in aborts the update and restarts
  the old version), the database is copied, `current` is replaced with `rename(2)`, and the
  service is started.
- **Readiness:** `/healthz` on loopback must report the new version, healthy, from a process
  started after the switch, within `readiness_timeout_s`. Otherwise the update is rolled
  back: `current` returns to the previous version and the database copy is restored.
- **Recovery:** every step is written to the journal first. `update_helper.py recover` finishes
  or undoes whatever an interrupted helper left: a partial version is removed, an unswitched
  update restarts the old version, a switched one is committed if healthy and rolled back if
  not. It is safe to run at any time. Run it from the supervisor unit
  (`ops/launchd/com.operator.mac-control.update-recover.plist.template`), at login and every 5 minutes.
- One helper invocation at a time (`state/lock`, released by the kernel if the holder dies).

**Setting up (by hand, once).** Create the root (mode 0700), copy the four helper files into
`<root>/helper/` and write `helper.json` (mode 0600):

```json
{"schema": "dashboard-update-helper/v1", "product": "mcd", "platform": "darwin-arm64",
 "root": "/srv/dashboard/install", "db_path": "/Users/<you>/.mac-control/data.db",
 "health_url": "http://127.0.0.1:8800/healthz", "python": "/opt/homebrew/bin/python3.12",
 "service": {"kind": "launchd", "label": "com.operator.mac-control",
             "plist": "/Users/<you>/Library/LaunchAgents/com.operator.mac-control.plist"},
 "trust": {"kind": "ssh-signature", "allowed_signers": "/srv/dashboard/allowed_signers",
           "identity": "<signer>"}}
```

`trust.kind` may instead be `pinned-digest`: each stage then needs the manifest sha256 the
operator copied from the release page. Then stage the first package, run
`update_helper.py activate-initial <id>`, point the LaunchAgent at
`<root>/current/runtime/bin/python` and `<root>/current/apps/api`
(`MAC_CONTROL_PYTHON_PATH`, `MAC_CONTROL_WORKING_DIRECTORY` for `scripts/install-launchagent.sh`),
and set `MAC_CONTROL_UPDATE_ROOT=<root>`.

**Operator API** (signed-in operator only; agent processes and agent grants are refused):
`GET /api/updates`, `POST /api/updates/stage {"name", "manifest_sha256"?}`,
`POST /api/updates/apply {"version_id"}`, `POST /api/updates/recover`. The POST routes only
start the pinned helper, detached from the service, and return 202; poll `GET /api/updates`.
With sign-in off, run the helper on the host instead.

**Limits.** Agents run as the same OS user, so they could still change files under the root
directly; a separate service account is the stronger boundary. Packages are placed in the
inbox by hand; nothing is downloaded. The helper does not update itself. A rollback restores
the database as it was before the switch, so anything written while the failed version ran
is lost.

**Recovery CLI (works with the app down).** `update_recovery.py` runs from the same pinned
helper folder, never contacts the API and needs no sign-in. It reads the journal and version links
on disk and drives the same engine, so use it when the app will not start:

```
python -I <root>/helper/update_recovery.py status      # app up/down, current, previous, interrupted update, work in flight
python -I <root>/helper/update_recovery.py versions    # every installed version and its role
python -I <root>/helper/update_recovery.py snapshots   # kept data snapshots (ids for restore)
python -I <root>/helper/update_recovery.py rollback    # code back to the previous version
python -I <root>/helper/update_recovery.py restore <snapshot id>   # database back to a snapshot
python -I <root>/helper/update_recovery.py recover     # finish or undo an interrupted update
```

`rollback`, `restore` and `recover` show what they will do and ask first. `rollback` and `restore`
are confirmed by typing the version or snapshot id back; with no terminal the same id must be
passed as `--confirm <id>`, otherwise nothing changes (exit 3). `rollback` switches code only and
keeps a copy of the database; it is refused if the database is on a schema the previous version
does not know. `restore` discards every change made since the snapshot, after copying the current
database first. Both stay refused while work is in flight. If the app is down and the database
still lists runs that died with it, `--skip-drain` (terminal only, a second typed question, refused
while the app answers) ignores that check. `--json` prints one object. Exit 0 done, 1 refused or
failed, 2 bad usage, 3 declined.

## CI

`.github/workflows/release-artifacts.yml` is a local draft that runs only when started by
hand. It builds twice, verifies, scans, checks that the lock installs from wheels only, and
uploads a short-lived workflow artifact. It does not publish a release. Action pinning and
enablement are handled in the s8-ci story.

Production 0.3.1 verification key and signing procedure: [release signatures](release-signing.md).
