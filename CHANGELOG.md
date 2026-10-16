# Changelog

All notable changes to Mac Control Dashboard (MCD) are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). MCD and the Raspberry Pi Control Dashboard (RCD) share
major.minor, so a feature level means the same in both. Release notes on GitHub are generated from
the section of the version being released, and a release cannot be built without one.

Internal operator notes, private hostnames and personal identifiers are omitted by policy.

## [Unreleased]

## [0.6.0] - 2026-10-16

New in 0.6.0: a bug icon in the header, repository bootstrap for projects that need a new private GitHub repository, and an opt-in parallel build. Bug
intake, Hermes repository proposals and the parallel auto-accept gate are all off until you turn them on, and a project builds serially unless you switch parallel on.

### Added

- A bug icon in the header. It opens a short form, shows the exact issue that would be sent (with paths, emails, addresses and
  key-shaped text removed and listed), and then either files it on the product's official GitHub repository as your signed-in account
  (through the same guarded GitHub action as other writes, after you confirm) or opens a prefilled GitHub page for you to submit under
  your own account. No token, relay or hosted service is involved. See `docs/configuration/bug-reports.md`.
- Bug intake (off by default, `MAC_CONTROL_BUG_INTAKE_ENABLED`). Issues a maintainer has labelled `bug-report` and `accepted` become one
  read-only triage task each, tagged `release-blocker` (label `break-fix`) or `release-queued`, with the report quoted as untrusted
  evidence. A Profile panel lists new tasks and the reports still waiting for a maintainer's label.
- Build in parallel, a switch chosen when a project is created (off by default; off builds one story at a time in dependency order). On, the planner is told to
  plan branches that change different files, with a `touches` list per editing story and integration stories where branches join (role pack version 6).
  Submission refuses two stories that can run together but overlap, a longest-chain-first build order, a schedule readout (longest chain, best-case
  speed-up, width, and the real overlap once runs finish), integration-story instructions, and an optional lighter gate
  (`MAC_CONTROL_PROJECT_AUTO_ACCEPT_LOW`, off by default) that accepts low-risk stories whose changes stay inside their declared files. See `docs/PROJECTS.md`.
- Repository bootstrap. Hermes can propose a new private GitHub repository for a project (`propose_repository`, behind a new Profile switch), which
  waits in Profile under "GitHub actions waiting for you" with its exact request. Approving creates it under your account, always private, with an
  initial README commit, and adds it to the install's GitHub list. A project's "Repository access for agents" form grants agents one branch,
  `project-<id>/<name>`, never main. The planner starts a plan with the approval and setup steps when a repository is missing (role pack version 5).
  See `docs/configuration/repository-bootstrap.md`.
- A "Delivering a containerized web app, local first" guide and a paragraph in the coordinator context (role pack version 4): a private
  repository created first, a pipeline on Linux runners that builds and tests the image, a local run on Colima, and repository setup
  planned as the first step with the repository creation, first push and secrets left to a person.
- A Discord alert when a project's planning or story hand-out stops after its run succeeded, for example when the plan is refused for a
  missing field or a bad dependency. Until now only failed runs alerted, so a plan that came back and then failed validation was
  silent. One alert per project, revision and reason; turn it off with `[projects] enabled = false` in `alerts.toml`.

## [0.5.5] - 2026-10-16

### Fixed

- A failed project task can be deleted as soon as its retry is queued or running. Retrying from Projects creates a new task, and the old
  failed one used to stay greyed out until the retry finished, which looked like a duplicate you could not remove. The retry itself stays
  protected, a lone failed task is still kept (it holds the only record), and the project ledger notes the deletion.
- The consultant no longer ends every reply with another question. Once you say you are done it confirms and waits, and the brief it
  writes has no closing question: anything still undecided becomes a stated assumption or a human decision story (or is dropped if it
  does not change the plan), so it reaches the coordinator as work instead of a dangling question.
- The planner is told that every story needs its instructions in the description field. A free planner returned a story with scope and
  acceptance but no description, and planning stopped with "needs instructions". (Coordinator role pack version 3.)
- Planning no longer stops with "Dependencies must connect different stories in this project" when the planner orders phases against each
  other or makes a story depend on its own phase. Those links are dropped from planner proposals (story order is kept; a dependency on a
  key that does not exist is still refused, and your own edits are checked as written). Because the saved plan is read again by **Resume
  saved plan**, a project that failed this way can continue from the saved proposal without another planning run.

## [0.5.4] - 2026-10-16

### Fixed

- Planning runs and board tasks on the default free model now start too. 0.5.3 fixed new chats; a project plan run, a task made from a form
  or an older saved task still carried the generic `openrouter/free` and was stopped with `PRICE_UNKNOWN` ("Budget check stopped the
  run"). The dashboard now replaces that default with the free model Hermes or OpenClaw is set up with when a task is created or edited,
  when a plan is requested, and when a saved task starts, so retrying a task that failed this way works without editing it. A model you
  name is never replaced, and a paid default is never chosen for you. Your saved keys were never involved.

## [0.5.3] - 2026-10-16

### Fixed

- Chats with Hermes or OpenClaw on the default model now start. The default, `openrouter/free`, is a generic name that neither agent
  lists, so the dashboard refused every new chat with `PRICE_UNKNOWN` (0.5.2 made that refusal readable; this removes the cause). A new
  chat on that default now uses the free model the agent is set up with (its own default, for example the one `hermes setup` chose),
  shown on the chat as the model in use. A model you pick by name is never replaced, and a paid default is never chosen for you. A
  chat created earlier that has not run yet is corrected the same way when you send its first message.

## [0.5.2] - 2026-10-16

### Fixed

- The project consultant's first message no longer waits for an approval nobody knew to give. The consultant opens with long guidance and
  your installation's standards, which mention releases and deploys, and the approval check read all of it as if you had asked to
  publish something. The guidance now travels as background beside your own words, and only your words are checked. The chat shows
  your message with a note that background was sent with it, and a "Sending your goal" line while the first message goes out.
- The project consultant now works as a conversation. It answers what you ask, asks a few clarifying questions at a time, and keeps going
  until you choose **That’s enough, write up the plan**, which asks for the brief from the whole discussion and opens it for you to edit
  before anything goes to the coordinator. The chat no longer shows the consultant’s instructions or your installation’s background.
- A chat on a model the dashboard has no reviewed pricing for (for example Hermes on `openrouter/free` when Hermes does not list that
  model) no longer looks sent and then fails with `PRICE_UNKNOWN` in the bubble. The dashboard now says so before the conversation
  starts: which agent and model, that the route has not been reviewed, and which free models Hermes is set up with so you can choose
  one in Profile, AI defaults. No empty thread is left behind.

## [0.5.1] - 2026-10-16

### Added
- After-hours housekeeping. Set `MAC_CONTROL_HOUSEKEEPING_AUTO` to the kinds you want cleaned up overnight (`stale_update_helper`, `stale_approval_wait`, `old_update_backup`) and the server applies exactly those fixed actions once a day inside a window (default 1 to 5 local time). Off by default. Each finding is re-checked at that moment, a database backup is taken before any row changes, nothing runs during an update, and every action is audited as `after-hours`. The Housekeeping panel shows the last run; Hermes can read and explain the status.
- A new housekeeping finding, "Finished update helper still loaded", for update helper jobs left registered with launchd after their update.

### Fixed
- Remove on the Services page failed for jobs started with `launchctl submit` (the update helpers) with "Boot-out failed: 3: No such process". Remove now uses `launchctl remove`, which works for them, with the newer command as a fallback; Run now and Restart gain the matching fallbacks.
- Update helper jobs piled up on the Services page, each showing as running with a process that no longer exists. MCD now unloads a finished helper automatically about a quarter of an hour after its update (never while an update is running; `MAC_CONTROL_REAP_UPDATE_HELPERS=false` switches it off), and the helper process now ends itself explicitly.
- Every update logged "warning: ... has no dated CHANGELOG section" even when the section was there: `grep -q` closed the pipe and the upgrade script's strict mode counted the writer's broken pipe as a failure. The check now reads the whole file.
- The Services Actions column is wider so the buttons and the explanation do not stack into a tall block.

## [0.5.0] - 2026-10-15

### Added
- Coordinator scorecard, in a new section of the Telemetry page. Every approved plan is scored by fixed checks (schema, the job envelope, estimates against size, checkable acceptance criteria, bounded scope, dependencies, route reasons, no stories too big to run, a review for high-risk work, and the standards' floors), compared with what the coordinator returned (how many nodes a person added, removed or changed) and recorded with the planner, the Delegator and the coordinator wording in effect (a version label such as `v2`, `+custom` for your own copies, and a hash). The page shows plan score by planner and by wording with edits per plan, first-pass completion and estimate error, so a change can be compared with the one before it. Eight fixed, general briefs and a scoring route let you try any model or wording change on the same plans. See `docs/configuration/coordinator-scorecard.md`.
- A weekly model watch (off by default; `MAC_CONTROL_MODEL_WATCH_ENABLED=true`). It reads OpenRouter's public model list and, only when something is new, leaves one Backlog card with the sources and exactly what differs: first, models your catalog lists as free that are no longer free, then new free models and changes. It edits nothing: adopting or dropping a model stays a reviewed change. The Models section shows when it last ran. See `docs/configuration/model-profiles.md`.
- Service actions on the Services page: **Why** (a plain explanation, the safest next step and the job's own log as evidence), **Run now**, **Restart** and **Remove** (unloads the job for this login; the plist is untouched; you type the label to confirm). Only listed services can be acted on, the dashboard's own service is protected, and every action is audited. See `docs/configuration/service-actions.md`.

### Changed
- Continuous integration now runs the macOS API tests once per merge to main (and on demand) instead of on every pull request push, and cancels superseded pull request runs. macOS runners bill at ten times the Linux rate; Linux still runs on every pull request, and every change is tested on a Mac before it is proposed.

## [0.4.14] - 2026-10-15

### Changed
- The project consultant chat now starts with the same knowledge a plan run gets: how the software is delivered, which agent runtimes are installed here and the spending policy, the standards that apply to the chosen working directory, the methods and practices (development practice, hosted and packaged delivery, application security) and the track record of the models it could recommend. It writes the brief so the coordinator can plan from it directly (approach and methods, risks by standards area, security considerations, model and route considerations). You can keep your own copy of any guide in the data folder. It is advice for the conversation and authorizes nothing; if it cannot be read the chat starts without it. See `docs/project-consultant.md`.

## [0.4.13] - 2026-10-15

### Added
- The coordinator now uses model profiles. A planning request includes a compact paragraph on the models it may choose (free or paid, context, tool support, and the track record here by kind of work, with unproven stated plainly), and the submit review shows non-blocking route advice for each story: a proven poor record for that kind of work, no listed tool use for work that edits files, or an unproven model on medium or high risk work. The gates, risk floors and approvals still decide; your own coordinator wording keeps working. See `docs/configuration/model-profiles.md`.

## [0.4.12] - 2026-10-15

### Added
- Model profiles, in a new Models section of the Telemetry page: what each model can do (free or paid, context size, tools, structured output, reasoning, price), how it has done in your own runs (runs, success rate, median time, cost, by kind of work, with a model shown as unproven for a kind until it has 10 runs) and notes people add with a source and a date (stale after 90 days). A Refresh free models action reads OpenRouter's public model list and shows what is new, what is no longer free and what changed, without editing your price catalog or any route. MCD ships no opinions about which model is better at what. The last read and your notes are kept across updates, and `MAC_CONTROL_MODEL_REFRESH_ENABLED` can switch the refresh off. See `docs/configuration/model-profiles.md`.

## [0.4.11] - 2026-10-15

### Added
- Ask Hermes to add to a repository's standards. With the new Profile switch on, Hermes can read a project's standards and propose an addition to the repository's standards file: a risk area, a check, a security bullet or a tightening rule. The server proves it is only an addition (nothing removed, reworded, lowered or loosened) and shows you the exact diff on the project page. Approving creates a new branch in the repository for you to review and merge; your current branch and files are not touched and nothing is pushed. See `docs/configuration/standards.md`.

## [0.4.10] - 2026-10-15

### Added
- You can keep your own coordinator wording across updates. Copy a file from `packs/roles/delegator/` into `roles/custom/` in your data folder and edit it: your copy is used instead of the shipped one, survives every update, and a copy that would break planning (a dropped placeholder, a stray `$`, empty or unreadable) is ignored in favour of the shipped text. The roles status lists customized and ignored files.
- A guide, `docs/configuration/upgrades-and-your-data.md`, says what an update keeps, replaces and never touches: settings, the database, preferences, credentials, the coordinator assignment and guidance, standards, project memory, and what your agents know.

### Fixed
- Agent settings are now covered by tests for every agent (Claude Code, Codex, Grok, Hermes, OpenClaw): installing, updating, rolling back or removing a managed agent tool, applying role guidance and starting a run leave each agent's own settings, credentials and memory untouched. The guide says exactly what MCD writes into an agent's folder (only the marked guidance block).
- A profile saved by a newer version (for example after a rollback) no longer breaks the profile page in an older one: preferences this version does not know are ignored when loading, and missing ones take their defaults.

## [0.4.9] - 2026-10-15

### Changed
- Repository standards now shape plans. When a project's repository has `docs/development/standards.md`, the planner is told the repository's areas and their minimum risk, every story's `area` must be one of them, its risk may not be below the area's minimum, and a high-risk story may not use a free-only route. A plan that breaks these is refused at approval with the reasons. A missing or unreadable file still only warns. See `docs/configuration/standards.md`.
- Starter standards: MCD now ships general standards, so a project is useful out of the box even when its repository has none. They cover areas with a minimum risk, checks for the definition of done and a security checklist for high-risk stories, plus plain guides on application security, development practice and delivering hosted and packaged apps. They apply when a repository has no standards of its own, you can change them by placing your own copy in the data folder, and the project page says which standards apply. See `docs/configuration/starter-standards.md`.
- The repository's checks (its Definition of done table) are frozen on the approved plan revision and added to the definition of done of every agent story that writes, so the agent has to run and report them. The Delegator's planning guidance now also explains how to choose area and risk and to cite the standard in the route reason.
- Telemetry can be cut by property (the standards' property the plan was approved under): a Property filter and a "Work by property" chart with each property's first-pass rate and median time.

## [0.4.8] - 2026-10-15

### Added
- A reference page, `docs/development/distribution.md`, for how this product reaches users: it is packaged code users pull from public releases, not a hosted service. It covers the steps from changelog and version to tag, signed package, draft verification and publishing, what makes a version offered to users, what users do, and what to do about a bad release. The Delegator's guidance now includes this model, and treats publishing a release as at least a medium-risk act.
- Repository standards: a project now reads `docs/development/standards.md` from its working directory, shows on the project page which standards it is working under (the property, the number of areas and checks, and the file's hash), and records that on each approved plan revision. The two tables in the file (Definition of done, Risk by area) are parsed by fixed code. A missing or unreadable file is a warning and planning goes on without it. Nothing is fetched and nothing outside the working directory is read. See `docs/configuration/standards.md`.

## [0.4.7] - 2026-10-15

### Added
- Telemetry: a Jobs and telemetry page that shows how work is going by job (one approved plan revision), kind, risk, size, route, who it is assigned to (a person or an agent), agent and model. It shows unassigned, in progress, waiting for you, completed, estimates missing and failed work; as charts you can read at a glance (donuts for workload by status and by route; stacked bars for work by assignee, by job, by model and by kind; completed per week; median time per kind), with the numbers on hover. The detailed tables (jobs, agents and models with success rate, median time, tokens, reported cost, API-equivalent cost and how often a different model served a run than the one requested, and kinds of work) are folded away until you open them. Filters narrow everything at once. It is read-only and computed from the existing records. See `docs/configuration/telemetry.md`.

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
[Unreleased]: https://github.com/gptkiosk/mac-control-dashboard/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.6.0
[0.5.5]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.5
[0.5.4]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.4
[0.5.3]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.3
[0.5.2]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.2
[0.5.1]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.1
[0.5.0]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.5.0
[0.4.14]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.14
[0.4.13]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.13
[0.4.12]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.12
[0.4.11]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.11
[0.4.10]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.10
[0.4.9]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.9
[0.4.8]: https://github.com/gptkiosk/mac-control-dashboard/releases/tag/v0.4.8
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
