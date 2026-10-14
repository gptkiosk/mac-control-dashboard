# One-click update of a source checkout

## Purpose

Explains the Updates page for an MCD that runs from a git checkout (the "driver" the LaunchAgent starts), how it decides what to install, what it refuses, and how to recover. Packaged installs keep their own signed-package updater, and RCD updates from its signed package, not this way. Read this before using the button or when an update was refused.

## Screenshots

Pending capture: `profile-updates-source-checkout.png`.

## Controls

On **Profile → Updates**, a host that runs from a checkout shows **Update this checkout**:

1. **Check for updates** reads the public list of releases of `gptkiosk/mac-control-dashboard`, picks the newest stable one, and downloads only its signed manifest and signature (never the package). It verifies the signature with the key in `packaging/allowed_signers` and shows the exact tag, the commit the signature names, the release notes as plain text, and anything that would be interrupted.
2. **Update to X.Y.Z** opens a separate confirmation naming that tag and commit. Nothing starts until you tick the box and confirm.
3. The service starts a helper as its own `launchd` job, so restarting the service cannot stop it. The page shows each step and a log tail, reconnects by itself during the restart, and reports success, a failure, or a rollback. Reopening the page later shows the last operation.

The helper runs the same reviewed script as the command line, `scripts/upgrade-driver.sh --ref <signed commit> --label vX.Y.Z --require-idle`: clean-tree check, data and `.env` backup, dependency sync only when a lock changed, web build, restart, a health check that must report exactly the new commit and version, automatic restore of the previous commit on any failure, and a receipt in `~/.mac-control/upgrades/`. Operation state and the private log are kept in `~/.mac-control/source-updates/` (mode 700; files 600).

It refuses, and says why, when:

- origin is not the official repository (forks and other remotes are never updated this way), or the checkout has uncommitted changes to tracked files;
- the host is not macOS on Apple silicon, `git`, `npm` or `uv` is missing, or the LaunchAgent is not loaded;
- the signed manifest is not signed by the dedicated release key, is not MCD's stable release of that version, or names a dirty or ineligible source tree;
- the tag does not point at exactly the commit the signature names (a moved tag);
- a run is in progress, a task is queued or running, a project is dispatching, an approval is waiting, or an approved task has not started. Nothing is stopped or cancelled for you; drain first and check again;
- the newest release changed after you checked, or the checkout changed after you confirmed.

There is no timer and no unattended install. If an update fails the previous version is restored and the page says so; the backup stays in `~/.mac-control/upgrades/`.

The trust key is the one in the checkout you are updating. If the project ever rotates its release key, update `packaging/allowed_signers` by hand from a source you trust before using the button.

What the panel shows:

- Not available: an explanation and no button.
- Available: tag, commit, notes and either a button or the work to drain.
- Updating: a step list; the page shows "Reconnecting" while the service restarts.
- Succeeded: the new version is healthy; reload the page to load the new interface.
- Rolled back or failed: the message says what was restored; read the log and the receipt before trying again.

## Settings involved

- `.env`: `MAC_CONTROL_LAUNCHD_LABEL` (default `com.operator.mac-control`) when the LaunchAgent has another label; `MAC_CONTROL_PORT` for the health check.
- Files: `~/.mac-control/source-updates/operation.json`, `operation.lock` and one `.log` per update; `~/.mac-control/upgrades/` for backups and receipts.
- API (operator only): `GET /api/app-updates/source`, `GET /api/app-updates/source/check`, `POST /api/app-updates/source/start`, `GET /api/app-updates/source/operation`.
- Command line equivalent: `scripts/upgrade-driver.sh` and `scripts/driver-status.sh` (see [Release flow](../development/release-flow.md)).

## Troubleshooting

- A helper that stopped without a result is reported as failed after 20 seconds. Check `~/.mac-control/source-updates/*.log`, then `scripts/driver-status.sh`.
- "Not idle" from the script means work started after you confirmed. Wait and check again.
- To update by hand instead: `scripts/upgrade-driver.sh --ref vX.Y.Z --dry-run`, then without `--dry-run`.

## Related pages

- [Release flow](../development/release-flow.md)
- [LaunchAgent installation](launchd.md)
- [Environment variables](environment.md)
