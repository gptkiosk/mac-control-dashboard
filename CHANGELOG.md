# Changelog

All notable changes to Mac Control Dashboard (MCD) are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). MCD and the Raspberry Pi Control Dashboard (RCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.4.7] - 2026-10-15

### Added
- Telemetry: a Jobs and telemetry page that shows how work is going by job (one approved plan revision), kind, risk, size, route, who it is assigned to (a person or an agent), agent and model. It shows unassigned, in progress, waiting for you, completed, estimates missing and failed work; workload by status and assignee; completed per week; estimate against actual time per job; first-pass rate and time per kind; and a table of agents and models with success rate, median time, tokens, reported cost, API-equivalent cost and how often a different model served a run than the one requested. Filters narrow everything at once. It is read-only and computed from the existing records. See `docs/configuration/telemetry.md`.

## [0.4.6] - 2026-10-15

### Added
- A standard job envelope on every planned story, the foundation for tracking jobs and their telemetry. A job is one approved plan revision. Each story carries a work kind, size, risk, estimate and a one-sentence reason for its route; the server derives the job and the route tier (free, subscription, api or human) and adds standard tags (`job:`, `kind:`, `size:`, `risk:`, `tier:`, `area:`). A plan without the envelope is refused at approval and the message names the gaps. Cards made by hand are unaffected. The card detail shows the envelope and why the route was chosen. See `docs/configuration/job-envelope.md`.
- The Delegator role pack now tells the planner how to fill the envelope and when a free route is safe and when to escalate to a foundation model.
- Tags may contain a colon.
- Human tasks can name the user they are assigned to (`assignee_user`, empty = unassigned), so work is assigned to a person or to an agent. The card detail shows "Assigned to"; plan stories for a human can carry it too.

## [0.4.5] - 2026-10-15

### Added
- Housekeeping in Profile: leftovers the server finds by fixed rules, which only you can resolve. First two kinds: runs left in "awaiting approval" on stories that are already done (they used to block updates), and old update backups beyond the newest three and 30 days. Each finding is re-checked when applied, the database is backed up first, every action is audited, and nothing changes without your confirmation.
- Hermes can read the findings and propose a fix on a free model (new Profile switch, off by default). It cannot change anything: its proposal waits for your approval, and only that approval makes the app act on exactly the findings frozen in the proposal. See `docs/configuration/housekeeping.md`.
- The Updates panel points to Housekeeping when an update is blocked by an approval wait.

## [0.4.4] - 2026-10-15

### Fixed
- An update is no longer blocked by approval waits that nobody can decide. A run left in "awaiting approval" on a story that is already done or failed (a later run completed it) was counted as a pending human decision forever, so the Updates panel and the packaged updater refused to start. Only waits on stories that are still open, or on no story, block an update now.

## [0.4.3] - 2026-10-15

### Added
- Opt-in sharing of the OpenRouter key saved in Profile with Hermes and OpenClaw, so it is not typed into each agent (as in RCD 0.3.6). Off by default, one operator per installation, saved key wins over the agent's own. The key is supplied only in the environment of Hermes and OpenClaw runs, scrubbed from anything they print, and never given to Claude Code, Codex or Grok. Paid models still follow the dispatch policy. Turning it off or removing the key stops it at once. See `docs/configuration/saved-openrouter-key.md`.

## [0.4.2] - 2026-10-14

### Fixed
- The release package builds again. The signed package for 0.4.1 was refused by the content scan because the source-update code spelled out the SSH form of the GitHub address, which looks like an email address. It is now assembled at run time, and a test runs the release content scan over the packaged source so this cannot reach a tag again. 0.4.1 was tagged but never released; 0.4.2 carries everything in it.

## [0.4.1] - 2026-10-14

### Fixed
- The one-click update now works on a checkout that has no `origin` remote, which is how a production driver is usually kept: it fetches the release from the official repository directly. A remote that points anywhere else is still refused.
- The Updates panel is easier to read: clearer spacing and headings, a plain facts list, separated buttons, the exact release and commit shown before you confirm, numbered progress steps, and the manual steps folded away when the one-click update is available.

## [0.4.0] - 2026-10-14

MCD reaches the 0.4 feature level. The new item is specific to MCD running from a source checkout; RCD updates from its signed package and has no equivalent.

### Added
- One-click, operator-approved update for MCD running from a source checkout. The Updates page checks the official stable release, shows the exact tag, the commit its signed manifest names and the release notes, and updates only after a separate confirmation. The signature is verified independently, the tag must point at the signed commit, and the existing reviewed upgrade script does the work (clean-tree check, data backup, drain check, exact commit and version health check, automatic rollback, private log). A detached helper survives the service restart and the page reports success, failure or rollback. Forks, modified checkouts and unsupported hosts are refused with the reason; packaged installs keep their signed updater. See `docs/configuration/source-update.md`.
- `MAC_CONTROL_LAUNCHD_LABEL` setting so the app knows its LaunchAgent label.

## [0.3.1] - 2026-10-14

### Added
- First production release with signed installer manifests and a committed public verification key for both products.
- Project consultant conversation in a glass panel below the project brief controls. Refine goals, phases, stories, scope, definitions of done and dependencies, then review an editable brief before submitting it to Hermes coordination. Existing planning and execution approvals remain required.
- Profile AI defaults start new consultant chats, agent chats, task forms and project planning with Hermes and OpenRouter free. Installed membership CLI/model routes are configurable, with settings links and help guidance. Existing conversations and approved routes retain their choices.

### Fixed
- OAuth setup uses installation-specific paths and explicit host origins; shared client JSON no longer imports unrelated callbacks. Generic examples and private-address disclosure keep personal endpoints out of standard setup.
- Wizard links missing agents to runtime installers and explains install, native configuration and readiness refresh. Saved OpenRouter keys no longer trigger another entry form; spending checks remain available.
- Installer helper status resumes after navigation, retries temporary failures, updates every three seconds while active, and shows its log below the matching runtime's buttons. Completed logs remain available.
- Raspberry Pi wizard prerequisites match the packaged Python 3.11 runtime.


## [0.3.0] - 2026-10-13

- Agent tools recognizes existing native installs, shows current versions and offers verified upgrades. Claude Code pin updated to2.1.299 and Hermes to0.22.0.

- Project Model lock stops failed tasks without automatic retries or equivalent-model failover; default behavior retains reviewed alternatives. Clean Mac/Pi OS install instructions are included.

### Added
- Matching lower-cost planning tiers, operator-reviewed paused-project retiering and repair of explicitly
  incomplete read-only story assignments, preserving scope and execution gates.
- Header version and commit tags remain visible on small screens; release footer information matches
  across products with product/owner, environment, API/web commits and modified status.
- Operator-confirmed managed installers for Claude Code, Codex CLI, Grok Build, Hermes and OpenClaw,
  with pinned downloads, update/remove/rollback, clean install environments and platform privilege restrictions.
- Agent roles with one assignable Delegator, generic starter guidance, managed instruction-block previews,
  private backups, rollback and interrupted-assignment recovery. In-progress pipelines keep their approved
  Delegator and model; a changed assignment requires new coordination review.
- OpenRouter/Hermes free-first setup guidance, platform worker choices and native membership prerequisites.
  Free-only planning can use a reviewed free Delegator route without a subscription CLI. Membership access,
  provider API charges and Google credit eligibility are explained separately.
- Grok Build is a supported agent, next to Claude Code, Codex, Hermes and OpenClaw: tasks, chat, project story
  agent and approved fallback, on an eligible Grok membership only (the CLI has no dollar cap, so an API route is
  refused). Runs are confined: telemetry and trace upload off, a filesystem sandbox, git push and merge denied.
  xAI prices are in the price catalog and the price checker reads docs.x.ai. See `docs/configuration/grok.md`.
- Settings, Updates can now look for a newer release on GitHub. **Check for updates** reads the public
  release list and shows the release notes as plain text; it downloads nothing and changes nothing.
  **Download and verify** fetches the release into the private inbox once you paste its manifest SHA-256
  from the release page and confirm. **Install** asks for a second confirmation that shows what changed in
  that version, and **Roll back** returns to the previous version. The changelog of a staged version stays
  visible in Settings until you install it.
- A macOS package, `mcd-<version>-darwin-arm64.tar.gz`, and `scripts/install/bootstrap-mcd.sh` to install it
  for the first time under launchd. The script checks the package against a digest you pin before it
  touches anything and refuses to replace a running dashboard, a listening port, an existing install or a
  data folder that already holds a database.
- A draft release workflow for macOS arm64 that builds the package from a tag and drafts the release with
  the notes from this changelog. It cannot sign a release until a signing key is added to the repository,
  and it fails before publishing anything until then. `scripts/release/publish-release.sh --package`
  creates only the tag for it and refuses without the key.

### Changed
- MCD works with any mix of agents installed. Setup readiness needs any one subscription CLI and any one of
  Hermes or OpenClaw instead of all of them, a new project story starts on an agent that is installed, and the
  story agent picker marks agents that are not installed. A test runs every one of the 32 combinations.
- When a new version fails its health check, the rollback now starts the previous version even if launchd
  had disabled the service or answered a bootstrap with a transient error after the failed version
  crash-looped.
- An installed package reports the commit it was built from instead of "unknown".

### Fixed
- Rollback restores the previous release link. Install and rollback refuse incompatible database schemas and show the reason. Notes-only releases explain that no installable package is available.
- The price catalog was missing from the release package, so an installed build could not start. A test now
  fails if any data file under `apps/api` is missing from the package list.
- The release content scan no longer reads a binary-like run in a minified web bundle as an e-mail address.

## [0.2.7] - 2026-10-13

### Changed
- "Unpriced" now means one thing: a model was used and has no recorded price. Runs that recorded no tokens
  and no cost (refused by the price gate, turned away at a usage limit, cut off before the model answered)
  are no longer usage records, so they are neither priced nor counted as unpriced. This replaces the 0.2.6
  rule that priced some of them at 0.
- A model used without a recorded price is named next to the unpriced count on the Agents page and the
  Overview ("no price for gpt-x"), as the signal that the price catalog needs updating.

### Added
- `scripts/pricing/check.py --used` lists the models used this month that the catalog has no price for and
  what the provider pages say about them; `--used --add` adds the ones the pages list.

## [0.2.6] - 2026-10-13

### Changed
- Runs that never reached a model, because the price gate refused them or the provider turned them away at
  its usage limit, are priced at 0 instead of counted as unpriced. A run cut off by a restart, or a failure
  with no stated cause, still stays unpriced, because it may have used tokens.
- Scheduled monitor jobs, which never call a model, are no longer counted as usage records.

## [0.2.5] - 2026-10-13

### Added
- Tasks list has a Model column. It shows a condensed model name (for example `inkling · free`), the
  model that actually ran when there is a run and the requested one otherwise; hover for the full id.
- Price catalog (`apps/api/pricing_catalog.json`): the recent models of each platform (OpenAI/Codex,
  Anthropic/Claude, Google, OpenRouter free routes) with their published standard prices, long-context
  tiers and dated changes. `scripts/pricing/check.py` compares it with the providers' pages, reports
  differences and new models, and can write the changes back with `--apply`. See
  `docs/configuration/pricing-catalog.md`.

### Changed
- API-equivalent prices now cover every model in use, read from the catalog instead of being typed into
  the code. Newly priced: GPT-5.6 Sol and Luna, GPT-5.5, GPT-5.4, Gemini 2.5 and 3.x, Claude Fable 5 and
  5.1, Opus 4.5, 4.7 and 4.8 and Sonnet 5; GPT-5.6 Terra now has its published long-context tier instead
  of a cut-off. Prices were checked against the provider pages on 2026-10-13.
- OpenRouter models ending in `:free` are priced at 0 (shown as a free model) even when a run reports no
  token counts, so they no longer count as unpriced. A gateway or vendor prefix on a model id no longer
  hides its rate.

## [0.2.4] - 2026-10-13

### Added
- Close project: ends a project that will not be finished, with a reason kept in its ledger. It is shown
  as Closed, never Complete, no new story starts, and its failed tasks (and those of completed
  projects) can be removed from the board while the ledger keeps their record.

### Changed
- Publishing a release scans the commits being released with gitleaks and refuses on any finding.

## [0.2.3] - 2026-10-13

### Added
- Failure mining: Hermes can answer "what has been failing and why?" in Discord. It reads failed runs
  classified by cause (subscription limit, price gate, permission, gateway, incomplete handoff, test
  failure and more), counts by agent, model and project, the errors that repeat, the cards still Failed,
  and a single run's error, handoff excerpt and log tail. Read only, with credentials, addresses and
  e-mail removed and every field bounded, and behind its own switch in Profile.

## [0.2.2] - 2026-10-13

### Fixed
- The Mac and Overview pages show the macOS software-update panels again. A newer route had taken over
  `/api/updates`, so those panels received the wrong data. The application updater now lives at
  `/api/app-updates`, and a test fails if two routes ever share a method and path.
- After a crash or restart, MCD stops a leftover agent process more reliably. It now recognises the
  process even when a launcher rewrites its name (a symlinked or script-run CLI, or Python on macOS), so
  an agent is not left running and started a second time.
- A handoff that says "Status: incomplete", "this story is incomplete" or "the evidence pack is
  incomplete" is no longer accepted as finished work.

## [0.2.1] - 2026-10-13

### Changed
- GitHub settings: tick repositories from a checklist loaded from the account instead of typing
  names. Saved repositories are pre-ticked, the list can be searched, and a repository from another owner
  can still be added by name.

### Fixed
- A failed coordination, plan or dispatch card that another card already carries can be deleted, not
  only duplicate stories, so a leftover duplicate no longer sits in Failed forever.
- The GitHub page names the repository that has a problem and why (not found, access refused, or
  temporarily unreadable) and keeps showing the others. One misspelled repository no longer blanks the
  page or blames your login.
- Saving the GitHub settings refuses a repository name that does not exist and suggests the closest
  match, such as `rbp-control-dashboard` for `rpd-control-dashboard`.

## [0.2.0] - 2026-10-13

### Added
- A release flow: release notes generated from this changelog, a script that publishes the GitHub
  release for a committed version, and a one-command upgrade of the running app to a tag with a backup,
  an exact-commit health check and automatic rollback.
- Branch-scoped git access for project agents: operator grants, commit and push gating hooks, and a
  credential helper limited to the MCD and RCD repositories.
- Subscription limits: when a Claude Code or Codex limit lifts is read from the CLI's own message and
  shown once, with a one-click option to send waiting stories to the approved alternate of the same
  grade, and a status request through Hermes on Discord.
- A project ledger file holding the full, uncompacted history that story prompts point to.
- A "modified" marker in the footer when a running build differs from the commit it names.

### Changed
- Story context is about a third smaller: stable parts first for prompt caching, digests of earlier
  handoffs, and only the decisions that concern the story. Nothing is lost; the full text is in the ledger.
- The footer takes the product and owner from the running app, so MCD and RCD share one footer.

### Fixed
- A failed project story that another card already carries can be deleted instead of staying on the
  board as an unneeded duplicate.

## Development history

Before versioned releases the work was grouped into phases. These notes describe what each phase added.

### Phase 1 — Skeleton (Oct 2026)
- FastAPI backend skeleton (`serve.py`) with health endpoint.
- Vue 3 frontend shell with sidebar, top bar and placeholder panels.
- Python 3.12 virtual environment and pinned dependencies.
- LaunchAgent template (`com.operator.mac-control.plist`) with boot/reload logic.

### Phase 2 — Monitoring and service health (Oct 2026)
- Collector: CPU, memory, disk, network and uptime sampling.
- Temperature and power via `macmon`; no sudo required.
- Services panel: custom LaunchAgents and LaunchDaemons with exit/status flags.
- Overview and Mac health panels with live charts.
- Footer branding (`© {year} mac-control · Bamcio LLC`) plus release labels.

### Phase 3 — Board, dispatch and approvals (Oct 2026)
- Kanban board: Backlog, Queued, Running, Review, Done, Failed.
- Agent adapters for Claude Code, Hermes, Codex and OpenClaw.
- Task execution approvals and operator handoff review; adapter sandboxing and policy coverage vary by agent.
- Agents panel with per-agent runs, tokens and cost totals.

### Phase 3b — Agent chat and MCP (Oct 2026)
- Persistent chat threads per agent with session resume.
- Read-only MCP server listings (`claude mcp list`, `hermes mcp`, `codex mcp list`, `openclaw mcp`).
- MCP add/remove requires approval through the dashboard Review step.
- MCP integration setup and verification remain specific to each installation.

### Phase 3c — Branding, vertical board, human tasks (Oct 2026)
- Brand: M-shaped pulse logo, favicon, manifest and themed icons.
- Vertical task board with status groups, filters and lanes.
- Human tasks (assignee "You"), tags, dependencies, estimates and definitions of done.
- Glass-styled chat panels with backdrop blur and token-based colors.
- Agent explorer, native usage accounting and subscription billing.

### Phase 4 — Google sign-in and access (Oct 2026)
- OIDC login via Google account; allowlist enforcement; session cookie.
- Local admin recovery token (mode 600) for lockouts.
- Private HTTPS access through Tailscale Serve; installation ports are configurable.
- OAuth credentials and host configuration remain outside distributable source and documentation.

### Phase 5 — Look and feel (Oct 2026)
- Blue glass theme with gradient actions, accessible dropdown menus and keyboard navigation.
- Light/dark mode toggle (persistent per device/browser).
- Screenshot reference library for every section and settings screen.

### Phase 6 — GitHub and ops reports (Oct 2026)
- Read-only GitHub panel (`gh api --method GET`): repos, PRs, issues.
- Ops reports viewer (read-only, with historical warnings preserved) for the Hermes cron archive and the configured ops-reports directory.

### Phase 7 — Alerts and stability (Oct 2026)
- Durable failure alerts through Hermes with outbox and crash-loop detection.
- Live-service preview safeguards keep project previews separate from the dispatcher.
- Service restart and uptime evidence is installation-specific; release notes do not imply continuous uptime.


### Phase 8 — Projects, profiles and shared handoffs (Oct 2026)
- Editable project maps, story assignments, prerequisites and shared execution context.
- Centered Balanced assignment preference and editable agent/model recommendations.
- Subscription-first planning and explicit paid-route approval; provider limits remain visible.
- Optional Discord planning connection and profile preferences with encrypted write-only credential storage.
- Direct task approval actions and explicit handoff review before dependent stories proceed.

[0.3.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.3.0
[Unreleased]: https://github.com/gptkiosk/mac-control-dashboard/compare/v0.4.7...HEAD
[0.4.7]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.7
[0.4.6]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.6
[0.4.5]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.5
[0.4.4]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.4
[0.4.3]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.3
[0.2.7]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.7
[0.2.6]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.6
[0.2.5]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.5
[0.2.4]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.4
[0.2.3]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.3
[0.2.2]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.2
[0.2.1]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.1
[0.2.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.0

[0.4.2]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.2
[0.4.1]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.1
[0.4.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.0
[0.3.1]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.3.1
