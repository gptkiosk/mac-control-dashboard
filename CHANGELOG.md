# Changelog

Public release notes for Mac Control Dashboard (`mac-control`).

This file summarizes major development phases; it does not imply that this repository has been published. Internal
operator notes, private hostnames, personal identifiers and retirement
records are omitted by policy.

## Phase 1 — Skeleton (Oct 2026)
- FastAPI backend skeleton (`serve.py`) with health endpoint.
- Vue 3 frontend shell with sidebar, top bar and placeholder panels.
- Python 3.12 virtual environment and pinned dependencies.
- LaunchAgent template (`com.operator.mac-control.plist`) with boot/reload logic.

## Phase 2 — Monitoring and service health (Oct 2026)
- Collector: CPU, memory, disk, network and uptime sampling.
- Temperature and power via `macmon`; no sudo required.
- Services panel: custom LaunchAgents and LaunchDaemons with exit/status flags.
- Overview and Mac health panels with live charts.
- Footer branding (`© {year} mac-control · Bamcio LLC`) plus release labels.

## Phase 3 — Board, dispatch and approvals (Oct 2026)
- Kanban board: Backlog, Queued, Running, Review, Done, Failed.
- Agent adapters for Claude Code, Hermes, Codex and OpenClaw.
- Task execution approvals and operator handoff review; adapter sandboxing and policy coverage vary by agent.
- Agents panel with per-agent runs, tokens and cost totals.

## Phase 3b — Agent chat and MCP (Oct 2026)
- Persistent chat threads per agent with session resume.
- Read-only MCP server listings (`claude mcp list`, `hermes mcp`, `codex mcp list`, `openclaw mcp`).
- MCP add/remove requires approval through the dashboard Review step.
- MCP integration setup and verification remain specific to each installation.

## Phase 3c — Branding, vertical board, human tasks (Oct 2026)
- Brand: M-shaped pulse logo, favicon, manifest and themed icons.
- Vertical task board with status groups, filters and lanes.
- Human tasks (assignee "You"), tags, dependencies, estimates and definitions of done.
- Glass-styled chat panels with backdrop blur and token-based colors.
- Agent explorer, native usage accounting and subscription billing.

## Phase 4 — Google sign-in and access (Oct 2026)
- OIDC login via Google account; allowlist enforcement; session cookie.
- Local admin recovery token (mode 600) for lockouts.
- Private HTTPS access through Tailscale Serve; installation ports are configurable.
- OAuth credentials and host configuration remain outside distributable source and documentation.

## Phase 5 — Look and feel (Oct 2026)
- Blue glass theme with gradient actions, accessible dropdown menus and keyboard navigation.
- Light/dark mode toggle (persistent per device/browser).
- Screenshot reference library for every section and settings screen.

## Phase 6 — GitHub and ops reports (Oct 2026)
- Read-only GitHub panel (`gh api --method GET`): repos, PRs, issues.
- Ops reports viewer (read-only, with historical warnings preserved) for the Hermes cron archive and the configured ops-reports directory.

## Phase 7 — Alerts and stability (Oct 2026)
- Durable failure alerts through Hermes with outbox and crash-loop detection.
- Live-service preview safeguards keep project previews separate from the dispatcher.
- Service restart and uptime evidence is installation-specific; release notes do not imply continuous uptime.


## Phase 8 — Projects, profiles and shared handoffs (Oct 2026)
- Editable project maps, story assignments, prerequisites and shared execution context.
- Centered Balanced assignment preference and editable agent/model recommendations.
- Subscription-first planning and explicit paid-route approval; provider limits remain visible.
- Optional Discord planning connection and profile preferences with encrypted write-only credential storage.
- Direct task approval actions and explicit handoff review before dependent stories proceed.
