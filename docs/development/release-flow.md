# Release flow (MCD and RCD)

A version is finished when it is **committed, on GitHub, released with its notes, and the running app
is on that release**. The same steps apply to both products; MCD and RCD share major.minor.

1. **Commit** small, conventional commits on the working branch. Update `CHANGELOG.md`: move the
   entries from `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` under Added, Changed or Fixed, and add
   the `[X.Y.Z]:` link at the bottom. Bump `apps/api/version.py` and `apps/web/package.json` together
   (a test fails if they differ, and another fails if the changelog has no section for the version).
2. **Test.** The API suite, the web type-check and tests, and `scripts/check-docs.py`.
3. **Push** the branch to the product's GitHub repository.
4. **Release.** The operator runs, from the checkout:

   ```sh
   scripts/release/publish-release.sh --version X.Y.Z --target <commit> --dry-run   # shows the notes
   scripts/release/publish-release.sh --version X.Y.Z --target <commit>
   ```

   It creates the tag `vX.Y.Z` on that commit and the release at
   `https://github.com/<owner>/<repo>/releases`, with the notes taken from the changelog section and a
   link to the full comparison. It refuses when the commit is not on GitHub, carries another version,
   has no dated changelog section, or the tag already exists. Tags and releases are never moved or
   replaced; a mistake is fixed by the next version. Use `--prerelease` for a candidate.
5. **Roll.** Put the running app on the release:

   ```sh
   scripts/upgrade-driver.sh --ref vX.Y.Z --from https://github.com/<owner>/<repo>.git --dry-run
   scripts/upgrade-driver.sh --ref vX.Y.Z --from https://github.com/<owner>/<repo>.git
   ```

   It refuses while runs are in progress or the checkout is modified, backs up the database and
   environment file, syncs dependencies only when a lock file changed, rebuilds the web UI, restarts the
   service, and requires the health check to report exactly the new commit and version. On any failure
   it restores the previous commit. A receipt is written to `~/.mac-control/upgrades/`.
6. **Confirm.** `scripts/driver-status.sh --from https://github.com/<owner>/<repo>.git` and the footer
   should both name the release's commit.

`scripts/driver-status.sh` answers "am I on the latest?" at any time.

Release notes are written for people reading the Releases page, so each entry says what changed for
the operator, not how. A release cannot be built (`scripts/release/release.py build`) without them.
