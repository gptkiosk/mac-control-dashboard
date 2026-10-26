# Mac Control Dashboard documentation

**[Why use MCD / RCD for project delivery?](project-workflow-value.md)** Benefits, measured planning evidence, context/model efficiency and honest limits.

Start with [Getting started](getting-started.md), then open the [Setup wizard](SETUP_WIZARD.md) in MCD to check your host, sign-in, agents and chosen model routes. [Tested environments](tested-environments.md) distinguishes the confirmed Mac setup from untested platforms.

## Feature guides

| Feature | Guide |
|---|---|
| Overview and alerts | [Overview](sections/overview.md) · [Alerts](sections/alerts.md) |
| Mac health | [Mac](sections/mac.md) |
| Services | [Services](sections/services.md) |
| Tasks and approvals | [Tasks](sections/tasks.md) |
| Agents, models and usage | [Agents](sections/agents.md) · [Routing reference](AGENT_USAGE.md) |
| Chat | [Chat](sections/chat.md) |
| Project planning and shared memory | [Projects](sections/projects.md) |
| MCP and Hermes access | [MCP](sections/mcp.md) |
| GitHub and operational reports | [GitHub](sections/github.md) · [Reports](sections/reports.md) |
| Help chat and how-tos | [Help](sections/help.md) · [Printable how-tos](HOW_TO.md) |
| Profile, credentials and Discord | [Settings](configuration/settings.md) · [Profiles and Discord](PROFILES_AND_DISCORD.md) |

- [Managed agent tools](install/agent-tools.md)
- [Recommended agent mix and memberships](configuration/recommended-agent-mix.md)
- [Agent roles](configuration/agent-roles.md)

## Configuration reference

- [Settings](configuration/settings.md) and [Environment variables](configuration/environment.md)
- [Google sign-in](configuration/google-sign-in.md)
- [Private remote access](configuration/remote-access.md)
- [Remote project preview access](configuration/remote-project-previews.md)
- [Alerts configuration](configuration/alerts-config.md)
- [LaunchAgent installation](configuration/launchd.md)
- [One-click update of a source checkout](configuration/source-update.md)
- [Housekeeping: findings Hermes can propose and you approve](configuration/housekeeping.md)
- [Bug reports: the header icon, GitHub moderation and tasks](configuration/bug-reports.md)
- [Repository bootstrap: from no repository to one set up for the project](configuration/repository-bootstrap.md)
- [The standard job envelope](configuration/job-envelope.md)
- [Jobs and telemetry](configuration/telemetry.md)
- [Repository standards](configuration/standards.md)
- [Starter standards](configuration/starter-standards.md)
- [What survives an update](configuration/upgrades-and-your-data.md)
- [Model profiles](configuration/model-profiles.md)
- [Coordinator scorecard](configuration/coordinator-scorecard.md)
- [Service actions](configuration/service-actions.md)
- [Share the saved OpenRouter key with Hermes and OpenClaw](configuration/saved-openrouter-key.md)
- [Runtime data and backups](configuration/runtime-data.md)
- [Platform parity with RCD (Raspberry Pi OS)](PLATFORM_PARITY.md)

## Reuse and development

MCD is MIT licensed and provided as-is for independent personal and commercial use. No ongoing upstream development, updates or support is promised. See [Developing your fork](../CONTRIBUTING.md), [Security policy](../SECURITY.md), [License](../LICENSE), [Third-party notices](../THIRD_PARTY_NOTICES.md), [Release and update pipeline](development/distribution.md), [Change history](../CHANGELOG.md) and [Ideas for forks](development/ROADMAP.md).

Screenshots use [synthetic preview data](screenshots/README.md). They illustrate controls, not verified connections to external services. Optional captures that are not included are identified explicitly in individual guides.

- [Clean Mac and Raspberry Pi OS0.3.1 installation](install/clean-os-0.3.1.md)

- [Project consultant and AI defaults (0.3.1)](project-consultant.md)

- [Model recovery and bootstrap](configuration/model-recovery.md) — route choices, telemetry, retry boundaries and built-in setup plans.
- [Engineering rules](development/engineering-rules.md) — standing rules agents must not undo: parity, bounded prompts, setup, models and failover.
- [Shared-feature parity audit](development/parity-audit-0.6.38.md) — inventory, repaired differences and platform limits.

- [Coordinator pipeline, selected context and channel contract](configuration/coordinator-pipeline.md)

- [Shared project workspaces and existing repository intake](configuration/project-workspaces.md)
