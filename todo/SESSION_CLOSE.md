# Session Close Procedure

Triggered when the user sends only "goodbye" or "bye" (pointer in `CLAUDE.md`). Follow the steps in this exact order.

1. **Update the TODO list FIRST — always before the regression gate (step 3), never after.** If any item on the TODO list was worked on this session, update it now (per `todo/CONVENTION.md`), in this order: (a) append a dated session-notes block to the detail file; (b) refresh the detail file's `**Status:**` line and `CURRENT STATUS` paragraph — re-read the session notes below it first; its date must not be older than the newest note; (c) mark finished items `— DONE YYYY-MM-DD` in the `TODO.md` header; (d) run `python3 scripts/todo_status_sync.py --fix` to mirror the detail files' status into `TODO.md`, then `python3 scripts/todo_status_sync.py --check` — it must report nothing new. Never hand-edit `TODO.md`'s `CURRENT STATUS` paragraphs (TODO #72: hand-written close-time refreshes produced false status lines). Skip this step only if no TODO item was touched this session.
2. `git status` — commit any uncommitted changes, **including the step-1 TODO edits**, so the gate runs on a tree that already reflects the session's work (do **not** push here — step 3's script does the push, automatically choosing the doc-only `--no-verify` path or the full test gate based on whether code changed).
3. Only now run `nohup /root/task_system/scripts/session_close.sh > /root/task_system/logs/session_close_latest.log 2>&1 &` to kick off the regression gate + push in the background.
4. **Merge this session's PR — only if the session worked on a branch other than `master`.** (A session working directly in the main checkout on `master` has no PR; skip this step.) In the session's own worktree: push the branch (`git push -u origin <branch>`), make sure its PR exists (`gh pr create --draft` if not), then kick off the merge in the background:
   `nohup scripts/merge_session_pr.sh <branch> > /dev/null 2>&1 &`
   The script merges **only that branch's PR** — never other open PRs — and merges **only if the PR's tests pass**. Red tests, a merge conflict, or a CI run that never finishes leaves the PR open and writes a loud line to `notifications.log`, which the next session start banners.
5. Tell the user: "Gate running in background — safe to close. ci-monitor will catch any CI failures." If step 4 ran, add: "Your PR will merge itself once its tests go green; if they fail it stays open and you'll see it at next session start."
6. Verify MEMORY.md is up to date.
7. List any `comm-check-fail-*` entries saved this session.

## PR merge rules (what step 4's script enforces)

- **Scope:** only the PR whose branch is the one this session worked on. Open PRs from other jobs, or ones parked on purpose, are never touched.
- **Green-only:** the PR's Regression Gate check must finish and pass. `.github/workflows/regression-gate.yml` runs on every PR for exactly this reason — without it a PR would have no check to gate on.
- **Draft PRs** are marked ready for review first, then merged.
- **Merge style:** merge commit, and the branch is deleted after it lands.

## Push rules (what step 3's script enforces)

- **Doc-only commits** (only `*.md`, `todo/**`, `TODO.md`, comments changed) push with `git push --no-verify` — no test gate needed.
- **Code changes** (anything under `consensus_engine/`, `scripts/*.py`, `tests/`, config) must go through the full gate (`scripts/pre-push`, `pytest -n 2`) before pushing — never `--no-verify` those.
