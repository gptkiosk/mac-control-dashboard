# Screenshot capture inventory

Captured October 10, 2026 in an isolated loopback preview using a fresh synthetic dataset. These images illustrate the interface; they are not evidence of live jobs, real spending, grants, pairing, service health or publication.

The preview used an unused port, separate disposable data and demo workspaces. Collection, dispatch, external delivery and native agent/GitHub binaries were disabled. No production data, credentials or private native configurations were copied. MCP listings, agent names, metrics, tasks, planning nodes and conversations are fixtures. The access-review form uses preview-only demo identity and capability metadata; no grant was submitted or issued. The live MCD service was preserved.

All captures are light mode except `appearance-dark.png`. Images retain the browser-rendered pixels, encoded as optimized PNG. Width is 1280 pixels (below the 1600-pixel maximum). Long pages are illustrated with viewport captures; these are not exhaustive full-page exports.

## Views

| View | Capture |
| --- | --- |
| Overview | [overview-overview.png](overview-overview.png) |
| Mac health charts | [mac-health.png](mac-health.png) |
| Services | [services-table.png](services-table.png) |
| Projects: populated planning map | [projects-planning-map.png](projects-planning-map.png) |
| Tasks: grouped board | [tasks-board.png](tasks-board.png) |
| Agents: fleet and explorer | [agents-list.png](agents-list.png) |
| Chat: synthetic conversation | [chat-thread.png](chat-thread.png) |
| MCP: synthetic server list | [mcp-server.png](mcp-server.png) |
| GitHub: disconnected state | [github-repo.png](github-repo.png) |
| Ops reports: synthetic report | [reports-catalog.png](reports-catalog.png) |
| Help & how-tos | [help-guide.png](help-guide.png) |
| Settings: profile preferences | [profile-settings.png](profile-settings.png) |

## Forms and details

| Detail | Capture |
| --- | --- |
| New project and centered Balanced slider | [projects-brief.png](projects-brief.png) |
| Story instructions and definition of done | [projects-story-assignment.png](projects-story-assignment.png) |
| Story agent, model and fallback controls | [projects-story-assignment-model.png](projects-story-assignment-model.png) |
| New task form | [tasks-story-assignment.png](tasks-story-assignment.png) |
| Named sub-agent dropdown | [agents-subagent-select.png](agents-subagent-select.png) |
| Billing and subscription settings | [agents-billing-rates-dialog.png](agents-billing-rates-dialog.png) |
| New chat form | [chat-new-dialog.png](chat-new-dialog.png) |
| MCP access review form (unsubmitted) | [mcp-grants-dialog.png](mcp-grants-dialog.png) |
| MCP server request form (unsubmitted) | [mcp-server-request-dialog.png](mcp-server-request-dialog.png) |
| Header account/settings menu | [profile-settings-account.png](profile-settings-account.png) |
| Discord planning connection form (unpaired) | [profile-discord-planning.png](profile-discord-planning.png) |
| Empty credential vault controls | [profile-credentials-vault.png](profile-credentials-vault.png) |
| Dark appearance | [appearance-dark.png](appearance-dark.png) |
| Paused alert status | [overview-alerts-panel.png](overview-alerts-panel.png) |
| Help chat | [help-chat.png](help-chat.png) |

## Verification

- [x] All 12 sidebar views have a capture.
- [x] Planning map contains a phase, three stories and visible connections.
- [x] Balanced is centered and is the default in the creation dialog.
- [x] Named sub-agent selector, billing, creation and access-review forms are visible.
- [x] Help chat and light/dark appearance are captured.
- [x] Screenshot contents were visually inspected by the monitoring agent; no real personal identifiers or secrets were seen.
- [x] Credential field values were verified empty; nothing was saved.
- [x] PNG signatures and dimensions verified for all 27 files.
- [x] Total image size: 12,094,467 bytes (12.09 MB), below 15 MB.
- [ ] Independent human/second-person redaction review of this final set, with reviewer and date recorded.
- [ ] Operator acceptance of task #16 after that review.

The run's original receipt described an incomplete dark-mode set. This inventory describes the corrected files on disk; it does not rewrite that historical receipt or accept the task.

## Accurate coverage limits

Alert rules are configured in `~/.mac-control/alerts.toml`; MCD has an alert-status panel, not an alert-rules dialog. The capture shows delivery paused. See [alert configuration](../ALERTS.md).

The isolated preview has no Google session, so the account menu shows Settings; Sign out requires a real authenticated session. GitHub and Tailscale are intentionally disconnected. Real repository cards, OAuth account selection, Discord pairing and actual provider cost retrieval were not exercised for these screenshots.

Separate terminal/installation illustrations referenced as pending captures elsewhere are not supplied by this UI set. Do not use a screenshot of a different state to imply that an installation, permission grant, pairing or delivery occurred.

## Naming and publication review

Use `<section>-<state>.png`. From a section guide, link to `../screenshots/<filename>.png`; from the documentation root, use `screenshots/<filename>.png`.

Before publication, independently inspect every image for personal emails, real channel/account IDs, tailnet/host names, private repository names, personal filesystem paths and secret values. Use synthetic data at capture time. Keep security review and publication approval separate from the screenshot task; these images do not authorize either.
