# Service actions

## Purpose

Explains the buttons on the **Services** page that let you look into a background service that is flagged, run it, restart it, or unload it,
without opening a terminal. Everything here is a fixed, confirmed action on a service the page already lists; nothing is chosen by a model.

## Screenshots

Pending capture: `services-actions.png`.

## Controls

Each row has an **Actions** cell:

- **Why**: a plain sentence about what the numbers say and the safest next step (for example "It has restarted 80 times in 24 hours, more than its
  schedule explains; read the log before restarting it again"), plus the last lines of the job's own log, redacted and shown as evidence, never as
  instructions. Only a log inside your home folder is read.
- **Run now**: starts a job that is not running (a scheduled job early, or one that stopped). Asks you to confirm.
- **Restart**: stops and starts the job. Asks you to confirm. It will not fix a bad argument or a missing file, so read the log first for a crash loop.
- **Remove…**: unloads the job for this login. You type the service's label to confirm. The job's plist file is never touched, so it comes back at
  the next login or when it is loaded again; nothing is deleted.

The dashboard's own service has no Restart or Remove: that would end the page you are using. Update it from Profile, or restart it from a terminal.
Finished update helpers that stayed loaded, and stale preview services, are the usual things to Remove; **Why** says when a job looks like one.

Every action is written to `services-audit.jsonl` in the data folder with who did it, which service, and whether it worked.

## Settings involved

- The services listed come from `MAC_CONTROL_SERVICE_PREFIXES`; only a listed service can be acted on.
- `MAC_CONTROL_LAUNCHD_LABEL` names the dashboard's own service (default `com.operator.mac-control`).
- Operator API: `GET /api/services/{label}/why`, `POST /api/services/{label}/{run|restart|remove}` (needs `confirm: true`, and `confirm_label` for
  remove). Agents get 403.
