# Hermes access to MCD

MCP → Agent access is a separate approval from registering an MCP server. It defaults to
Read only for seven days. The operator may approve Read + planning drafts for 1, 7 or 30 days.
The review names the permissions, expiration and replacement of any previous Hermes grant.
Deploying this feature creates no live grant and applies no pending MCP change.

Read access exposes task descriptions, definitions of done, dependencies, task configuration
and limited agent metadata through `/api/agent-tools`. It does not expose run commands, logs,
result text, chat content, billing, Google sessions, credentials or integration settings.
Draft access additionally creates Backlog tasks and edits or links dependencies only on
Hermes-created Backlog drafts. Working-directory allowlists, field validation, approval flags,
self/cycle checks and human-task rules still apply. Only the operator queues work, changes
status, approves tasks, deletes tasks or starts/cancels runs. Queue/status requests through
MCP fail before changing anything; they never create a partial queued task.

A grant writes `~/.mac-control/agent-tokens/hermes.token` as a regular file, mode 600, inside
an owned mode-700 directory. Only its SHA-256 hash and permission/audit metadata are stored
in SQLite migration 0009. The API and UI never return the secret. Creating a new grant revokes
all previous Hermes grants. Revoke is immediate on the next request; expiration is enforced
server-side. Revoked file contents do not confer access. Agents cannot renew or broaden grants.
The local admin recovery token and browser session cookie must never be supplied to Hermes.
These capabilities restrict API access, not what other processes running as the same Mac user
can read from that user's filesystem.

The MCD stdio tool server reads its private file before every request. `MCD_TOKEN_FILE` may
point to another private credential file for isolated testing. It uses an explicit HTTP
loopback IP/port, ignores inherited proxy settings and refuses redirects. Bearer requests
are accepted only on a direct local connection without Origin or forwarded headers. An
invalid bearer credential never falls back to an operator browser session. Tokens cannot
access the normal operator API, the approval routes, tailnet requests or browser pages.

Register Hermes's MCD server only through the separately approved pending MCP change (A8):

- Command: `<REPOSITORY_ROOT>/apps/mcp/.venv/bin/python`
- Argument: `<REPOSITORY_ROOT>/apps/mcp/mcd_server.py`
- No credential arguments or environment secret values are needed.

Hermes 0.21.5 asks to enable discovered tools during registration. After operator approval,
MCD supplies one default answer, requires the CLI's saved-config receipt, and checks the
persisted server listing. Cancellation, failed discovery, or a missing registration is a
failed change even if the CLI exits zero. Existing-server overwrite and failed-probe save
prompts default to No; MCD does not repeatedly answer confirmation prompts.

The server's tools are list_tasks, get_task, create_task, update_task, add_dependency,
remove_dependency and list_agents. Legacy queue/status parameters return an explicit operator
review requirement. Credentials are not printed, captured in command arguments, or sent to
an LLM. Tests use temporary grants/databases; the stdio proof invokes the tool server directly,
without invoking Hermes's model or changing its configuration.
