# Changelog

All notable changes to Mac Control Dashboard (MCD) are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). MCD and the Raspberry Pi Control Dashboard (RCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.2.6] - 2026-10-13

### Changed
- Runs that never reached a model, because the price gate refused them or the provider turned them away at
  its usage limit, are priced at 0 instead of counted as unpriced. A run cut off by a restart, or a failure
  with no stated cause, still stays unpriced, because it may have used tokens.

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

[Unreleased]: https://github.com/gptkiosk/mac-control-dashboard/compare/v0.2.6...HEAD
[0.2.6]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.6
[0.2.5]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.5
[0.2.4]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.4
[0.2.3]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.3
[0.2.2]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.2
[0.2.1]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.1
[0.2.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.2.0
