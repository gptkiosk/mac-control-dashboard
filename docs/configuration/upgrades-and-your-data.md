# What survives an update

## Purpose

Explains what MCD keeps, replaces and never touches when you update it, so you can customize the coordinator, keep your
agents' knowledge and trust that your preferences are still there afterwards. The short version: an update replaces the
program; everything that is yours lives outside it and is left alone.

## Controls

There is nothing to switch on. This page tells you where each kind of thing lives, what an update does to it, and what to look at
after an update.

| What | Where it lives | An update |
|---|---|---|
| The program: code, built interface, shipped docs, the starter standards and the shipped coordinator text | the install: your git checkout, or a packaged version folder | **Replaces it.** Do not edit files here; a checkout with uncommitted changes is refused by the updater, and a packaged version is replaced whole. |
| Host settings | `~/.mac-control/.env` | **Never touches it.** New settings default to off or safe. The checkout updater also copies it into the backup first. |
| Everything MCD remembers: tasks, runs, projects, approvals, decisions, project memory, usage, alerts | the database `~/.mac-control/data.db` | **Keeps it.** Schema changes run at start and only add; the checkout updater takes a consistent copy of the database and the `.env` file into `~/.mac-control/upgrades/<stamp>/` before it changes anything. |
| Profile preferences, linked accounts and switches | the database | **Keeps them.** A preference added by a newer version takes its default (off unless stated). A profile saved by a newer version still opens in an older one; keys the older version does not know are ignored. |
| Saved credentials and tokens | encrypted in the database with `vault.key`, plus `agent-tokens/`, in the data folder | **Keeps them.** They are never part of a package or a release. |
| Hermes as Coordinator and the other agents’ role labels | `<data>/roles/assignments.json` | **Keeps them.** The Settings card fixes Hermes as Coordinator; legacy role data is retained for compatibility. |
| Coordinator guidance inside your agents' own files (the managed block, for example in Hermes `SOUL.md` or Claude `CLAUDE.md`) | the agent's own folder | **Does not change it.** It is a copy made when you applied the roles. Your own text around the block is kept byte for byte. After an update, open the roles preview to see whether the shipped guidance changed and apply it if you want it. |
| Planner, review, dispatch and coordination prompts | shipped in the program, read each time a plan runs | **Changes what they say** as soon as you update. To keep your own wording, use a custom copy (below). |
| Your own coordinator wording | `<data>/roles/custom/<file>` | **Keeps it, and it wins** over the shipped file of the same name. |
| Your own starter standards | `<data>/standards/starter.md` | **Keeps it, and it wins** over the shipped starter. |
| A project's repository standards | in that project's own repository | **Never touched.** They change by a normal change in that repository. |
| What your agents know (Hermes, Claude, Codex, Grok and OpenClaw memory, notes and projects) | each agent's own home | **Never read or changed by an update.** The only thing MCD writes there is the managed guidance block. |
| The last read of the public model list, the model watch's state and your model notes | `<data>/models/` | **Keeps them.** |
| The audit of service actions | `<data>/services-audit.jsonl` | **Keeps it.** |
| Run logs, reports, project outputs, workspaces, alert rules | the data folder | **Keeps them.** Old runs are pruned only by the retention setting (90 days by default). |

## Your agents' own settings

Claude Code, Codex, Grok, Hermes and OpenClaw keep their settings, credentials, memory and instructions in their own folders
(for example `~/.claude`, `~/.codex`, `~/.hermes`, `~/.openclaw`). MCD does not own any of that, and these rules keep it safe:

- **Managed tool copies live apart.** When MCD installs or updates an agent tool, the program goes into its own tools folder with
  its own `current` and `previous` links, using a throwaway home folder for the installer. Updating, rolling back or removing that
  copy never reads, rewrites or deletes anything in your agent's own folder. An update of the tool is only ever a new program;
  your settings are still read by it from where you put them.
- **Runs see your settings.** An agent started by MCD gets the service's own environment (so `HOME` and any settings location
  such as `CODEX_HOME` or `HERMES_HOME` point where you set them) minus MCD's own settings and credentials.
- **The only things MCD ever writes into an agent's folder** are the marked guidance block when you apply roles (your own text
  around it is kept byte for byte, and rolling back restores it), and, only if you run the Hermes plugin installer yourself, the
  plugin files and one added entry in Hermes' Discord toolset list. It refuses to replace a plugin that differs from its own.
- **Tests check this** for every agent: a synthetic copy of each agent's settings, credentials and memory is left byte for byte
  unchanged, with unchanged modification times and no new files, across install, update, rollback and remove of its managed tool.

## Customizing the coordinator so it survives updates

The shipped coordinator text lives in the program folder, so editing it there would be lost (or would stop a checkout updating).
Put your version in the data folder instead:

1. Copy the file you want to change from `packs/roles/delegator/` (`plan.txt`, `review.txt`, `dispatch.txt`, `coordinate.txt`,
   `SOUL.md` or `context.md`) to `<data>/roles/custom/` with the same name, and edit the copy.
2. Keep every `$placeholder` the shipped file has (for example `$schema`, `$project`, `$catalog`, `$standards`): MCD fills them
   in. A copy that drops one, has a stray `$`, is empty, is a symlink or cannot be read is **ignored** and the shipped text is used,
   so a mistake cannot stop planning. The roles status (`GET /api/roles`) lists which files are customized and which copies are being ignored, and why.
3. The same safety scan applies: a copy cannot carry host paths or credentials.
4. After an update, compare your copy with the new shipped file. Your copy does not pick up new shipped sentences by itself; that
   is the trade for keeping your wording. The changelog says when guidance changed.

Standards work the same way: copy `packs/standards/starter.md` to `<data>/standards/starter.md` (see
[Starter standards](starter-standards.md)).

## How the update paths treat your data

- **Checkout updater** (Profile, Updates; or `scripts/upgrade-driver.sh`): refuses a modified checkout and while work is running, backs up
  the database and `.env` and records the previous commit, checks out the signed commit, syncs dependencies only when a lock
  changed, rebuilds the interface, restarts and requires the health check to report exactly the new commit and version. On any
  failure it puts the previous commit back and restarts it. The backup stays in `~/.mac-control/upgrades/` with a receipt; rolling
  back the program does not restore the database, and restoring a backup is a separate step you take on purpose.
- **Packaged install:** the signed-package updater stages the new version beside the old one, copies the database before it
  switches, and rolls back to the previous version if the health check fails. Your data folder is outside the version folders and is
  never opened by the update.

## After an update

1. Read the release notes for the version. Anything that changes the coordinator, standards or defaults is listed there.
2. If you use the managed guidance blocks, open the Agents roles preview. If it shows a change, review it and apply it, or leave
   your current block.
3. If you keep custom coordinator text or your own starter standards, compare them with the new shipped files.
4. Check the Updates panel for the log and the receipt, and confirm the footer shows the new version.

## For people building on this

These are the rules the update path relies on, and any change should keep:

- User data lives outside the install folder, and the program never writes into its own folder at run time.
- Schema changes are additive. A new setting or preference has a safe default (off unless the change says otherwise), and loaders
  ignore keys they do not know.
- Shipped text and user text are separate files. A user's copy wins and a broken copy falls back to the shipped one.
- An update never overwrites a file the user edited, and never reaches into an agent's own folder.
- Backups are taken before the switch, and a rollback restores the program; restoring data is a separate, explicit step.

## Settings involved

- `MAC_CONTROL_DATA_DIR` (the data folder; default `~/.mac-control`).
- Files under the data folder: `roles/assignments.json`, `roles/custom/`, `standards/starter.md`, `vault.key`, `agent-tokens/`.
- Operator API: `GET /api/roles` reports `custom` and `custom_ignored`.
