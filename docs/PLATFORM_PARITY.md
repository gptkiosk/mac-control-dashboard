# Platform parity: MCD (macOS) and RCD (Raspberry Pi OS)

Status: **draft, unverified.** Written for the P2–P5 features (Ops collectors, finding-to-task drafts, report storage, GitHub settings, and the app update panel). Source of truth is the code; this page records what is shared and what is meant to differ. Tests were not run for this revision; see [Verification](#verification).

RCD is a separate codebase with the same web interface and the same API surface for these features. Keep the two in step by changing shared behaviour in both apps.

## Shared behaviour (identical files)

These P2–P5 files are byte-identical in MCD and RCD. Changing one means changing both.

- Components: `ReportFindings.vue`, `FindingTaskDialog.vue`, `ReportStoragePanel.vue`, `UpdatePanel.vue`, `GithubSettingsPanel.vue`, `GithubWorkList.vue`, `OpsHealthPanel.vue`
- Library: `lib/findings.ts`, `lib/operations.ts`, `lib/reportMarkdown.ts`
- Mounts: Ops reports (`ReportsView`), Settings (`ProfileView`: storage, updates, GitHub), GitHub (`GithubView`), and the setup wizard (`SetupView`: storage and GitHub steps)
- API client: the P2–P5 request and response types in `lib/api.ts` and `lib/operations.ts`

## Intended differences

| Area | MCD (macOS) | RCD (Raspberry Pi OS) | Reason |
| --- | --- | --- | --- |
| Host health page | `/mac`, "Mac": CPU, memory, disk, temperature and power via macmon | `/pi`, "Pi health": temperature, firmware throttling, disk, memory, CPU | Different hardware telemetry sources |
| Collector kinds `memory`, `disk`, `load`, `dir_age` | Link to `/mac` | Link to `/pi` | Host page per platform |
| Collector kind `service` | Links to `/services` | Links to `/services` | Shared page; see the service probe row below |
| Service probe in `ops_collectors.py` | `launchctl print` in the configured domain (`sys.platform == "darwin"`) | `systemctl is-active`, with `--user` when the configured scope is user | Different service managers |
| Background service install | LaunchAgent via `scripts/install-launchagent.sh` | systemd user unit via `scripts/install-systemd-user.sh`, plus `loginctl enable-linger` for boot | Different service managers |
| OS update help | macOS updates, read-only, installed in System Settings (`updates` help article) | apt updates, read-only, installed in a terminal (`updates` help article) | Different OS update mechanisms |
| Setup wizard host step | macOS prerequisites, `~/.mac-control/.env` | Raspberry Pi OS 64-bit on a Pi 4 or newer, `~/.rcd-control/.env` | Different hosts and default data directories |
| Subscription CLIs | Codex desktop app and CLI, Claude desktop app and Claude Code CLI | Codex CLI and Claude Code CLI only (no desktop apps); OpenRouter routes are offered as the non-subscription alternative | No desktop apps on Pi OS |
| Wording | "Mac" and "macOS" | "Pi" and "Raspberry Pi" | Name of the host |

The update panel UI is identical in both apps. Whether the backend update helper behaves the same on each host (service stop, data snapshot, health check, rollback) is not verified here; it needs the P5 release tests. OS-level packaging is separate and not covered by this page.

## Fixed for parity (this revision)

- Collector links: `service` checks now go to the shared Services page instead of the host page. The backend `LINKS` map in `apps/api/ops_collectors.py` now matches the frontend `KIND_LINKS` map in `lib/opsHealth.ts`.
- RCD labelled its host page "Mac" and pointed at a redirect (`/mac` to `/pi`). Its links now go to `/pi` with the label "Pi health". This fixed the label; the old `/mac` redirect still exists for bookmarks.
- Settings-page link from release checks: the backend pointed at `/settings`, which is not a route. It now points at `/profile`, matching the frontend.
- Help: the `reports` article now explains the finding-to-task drafts. A new shared `app-updates` article explains the app update panel, with an operator sign-in note. OS update articles stay platform-specific.

## Not changed (needs an owner decision)

- RCD's help has 30 articles and MCD's has 31. The one missing from RCD is `price-unknown` ("A task fails with PRICE_UNKNOWN"). RCD's help spec pins its count, so adding it is a deliberate change.
- The task retry UI (`TaskRetryAction.vue`) and its test exist only in MCD. The retry-field types are in RCD's `lib/api.ts` but not in MCD's. Approval fields (`approval`, `decision_pending`) also differ between the two API clients. These belong to the lifecycle stories, not P2–P5.
- Pi firmware throttling fields (`throttled`, `throttle_flags`) and the `platform` field are RCD-only. They are intended.

## Verification

- Web and API test suites were **not run** in this revision because the sandbox denied the test commands. Expected results are unconfirmed until an approved run.
- No preview or screenshot was captured. Visual parity is unverified. Any UI claim needs an isolated preview on a free loopback port with synthetic data.
- Snapshots were not updated.


## Version 0.3.0 capability alignment

The shared feature level includes five agent types (Claude Code, Codex CLI, Grok Build, Hermes and OpenClaw) plus the GitHub CLI as an optional managed tool, managed installers for all five, operator-reviewed update/remove/rollback, release updates with verification and recovery, Hermes as the fixed Coordinator with Worker, Reviewer and Security labels for other agents, plus generic role guidance, and free-only planning without a required membership CLI.

| Capability | MCD | RCD |
|---|---|---|
| Managed agent tools and version pins | Apple Silicon installers | Linux arm64 installers |
| Installer privilege restriction | macOS Seatbelt | Linux no_new_privs |
| Release updater and recovery | launchd service | systemd service |
| Roles, marked guidance, preview/rollback/recovery | Same controls | Same controls |
| Reviewed Hermes free-router planning | Supported | Supported |
| Cost-aware planning tiers, paused retiering, incomplete-story repair | Supported | Supported |
| Version header and standard release footer | Same fields | Same fields |
| Membership/API/BYOK setup guidance | Same billing distinctions | Same billing distinctions |
| Worker recommendation | OpenClaw | ZeroClaw/PicoClaw experimental integrations |
| Host health | Mac metrics | Pi metrics |

ZeroClaw/PicoClaw are not yet supported selectable dashboard workers. Their current integration/conformance limits are documented, rather than counted as completed 0.3.0 features. Pi hardware, account sign-ins and real model quality need separate evidence. Matching capability does not mean identical host-specific code or default spending policy.
