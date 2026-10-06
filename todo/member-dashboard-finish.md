# Member dashboard (TODO #121): finish plan

Written 2026-10-05 from the Codex session "implement member dashboard design"
(it ran out of usage credits right after finishing). Read this whole file before acting.

## What is already DONE (do not redo, do not re-review, do not re-run)

All built, reviewed and verified by Codex on the user's **Windows PC**, in the detached
git worktree `C:/Users/Desktop/.codex/worktrees/ac44/Discord bot`:

- Plan: `docs/superpowers/plans/2026-10-05-member-dashboard.md` (spec beside it in `docs/superpowers/specs/`).
- Tasks 1, 2, 3, 4, 4A, 5, 6, 7, 8, 9, 10, 11, 12: implemented, independently reviewed, every finding closed.
- Final code commit `83f98c085a8712d0a176d535f356bbc975c3c293`; docs-only closing commit
  `421d71c6904d113295aaa86f8f26235e9006459a` (branch base `725e48f`, about 35 commits).
- Final full verification once at `49037c4` + focused re-checks of the `83f98c0` delta:
  bot 4,451 passed / 12 baseline failures (unchanged, tracked as TODO #120) / 10 unchanged skips;
  dashboard backend 688 passed; protected contracts 153 passed; frontend lint, typecheck, build and
  26 browser tests pass; the 20-member, 300-second browser load test passed
  (feed updates p95 15.1 s, API reads p95 130 ms, 0 failures).
- Results doc: `docs/member-dashboard-verification.md`. Runbook: `deploy/member-dashboard/README.md`.
  TODO #121 was added to the PC copy of `TODO.md`.
- Evidence and handoffs (not committed): `.superpowers/sdd/2026-10-05-member-dashboard/`
  on the PC (`progress.md`, `final-verification-report.md`, `final-integration-checks.md`,
  `task-*-report.md`, `final-evidence/`).

## What is NOT done (never mark these complete without proof)

1. The work exists **only on the PC**. It is not on GitHub and not on this server (checked:
   `git cat-file -t 421d71c` fails here; no matching branch on origin).
2. Not merged into `master`. Master has moved since the base: `eb4faa1`, `077a05f`,
   `0d8d1d9`, `5a7af09` (touching `TODO.md`, `config/consensus.yaml`,
   `consensus_engine/alerts/commands.py`, `scanners/youtube.py`, among others). Expect conflicts there.
3. The dashboard branch changes **live bot code** (scanners, `sec_edgar`, Schwab client, http/budget
   hooks, `all_command` aggregator/narrator/levels, `cross_reference`). After the merge the running bot
   uses that code, so live checks are required.
4. Open regression on master, unrelated to the dashboard but in the same scoring area:
   `tests/test_pr2_score_ticker.py::test_cross_reference_still_caches` (session-close gate, 2026-10-05 18:22 PDT).
   The 3 local master commits are unpushed because of it.
5. Launch (TODO #121 gates). Blocked on the user, see Phase C. Nothing is deployed and all dashboard
   service units are shipped switched off (`ExecCondition=false`).

## Phase A: transfer (Windows PC, Claude Code, small)

Implementer: Claude Code on the PC (Codex has no credits until 2026-10-12). Run from the worktree folder.

1. `git status --short` is clean; `git rev-parse HEAD` = `421d71c6904d113295aaa86f8f26235e9006459a`. If not, stop and report.
2. Push the work to the **server repo, not GitHub** (GitHub is public, and pushes only happen at session close):
   `git push Hetzner:/home/openclaw/.openclaw/workspace HEAD:refs/heads/member-dashboard`
3. Copy the evidence text files (skip runtimes: `node-v24*`, `*.tar.gz`, `*.zip`, `linux-wheels*`, `web-clean-venv`, `.e2e` screenshots are optional)
   into the server path `/home/openclaw/.openclaw/workspace/.omc/member-dashboard-evidence/`. Use tar over ssh or scp.
4. On the server: `chown -R openclaw:openclaw /home/openclaw/.openclaw/workspace/.git /home/openclaw/.openclaw/workspace/.omc/member-dashboard-evidence`.
5. Report the branch hash and the evidence file count. Change nothing else. No commits, no GitHub push.

## Phase B: integrate (this server, Claude Code)

Implementer: main session. Verifier: a **separate** subagent that wrote none of the code.
Follow CLAUDE.md "Start of Build", "Definition of Done" and "Regression Gate".

1. **Check the transfer** (this is the independent check of Phase A): `git rev-parse member-dashboard` = `421d71c…`;
   `git log --oneline 725e48f..member-dashboard | wc -l` matches the PC; the evidence folder has `final-verification-report.md`.
2. **Fix the open master regression first** (`test_cross_reference_still_caches`): reproduce, find the cause, fix, commit.
   This keeps it from being mistaken for a merge problem.
3. **Merge** `member-dashboard` into `master` (merge commit, keep history). Resolve conflicts by keeping both sides' intent.
   TODO.md: keep master's entries plus #121. Don't re-number.
4. **Focused checks only on what the merge changed**: run the tests for every conflicted file plus their
   dependents (`grep -rn` symbol/old string across `tests/`). Don't re-run Codex's full matrix.
   The dashboard web suite runs on Python 3.12 at `/tmp/member-dashboard-webtest-20261005/web-venv/bin/python`,
   and only if the merge touched `member_dashboard/` or its shared contracts. Don't build the frontend on this
   server (low disk). It was verified on the PC at the same commit and the merge doesn't touch `web/`. If it does, stop and say so.
5. **One full bot suite** (`make test`, through `bounded-run`) after the merge. Compare by test ID to `.test-baseline`.
   Any new failing ID is a regression and must be fixed.
6. **Live checks** (the merge changes the running bot): restart `consensus-engine.service` as documented in memory
   `reference_engine_restart_and_dbpath.md`. Buckets: `[always]`, `[discord-commands]` (`!all NVDA`, `!sec NVDA`, the
   options/expected-move command), `[ingest]` (one real poll cycle lands sane rows/log lines for SEC/options/Schwab).
   Read the real Discord replies. Compare them to the pre-merge output. The bot's numbers must not change (Codex proved parity on fixed inputs).
7. **Independent verifier subagent**: re-runs the full suite, diffs against `.test-baseline`, re-reads the live command replies and the engine log,
   and reports. Stop it once its result is accepted.
8. `python3 scripts/check_ownership.py`, then commit locally. Push happens only at session close ("bye").
9. After the verifier passes, delete the Codex scratch on this server: `/tmp/member-dashboard-webtest-20261005`,
   `/tmp/member-dashboard-parity-20261005-golden*` (about 1.2 GB). Those are Codex test copies, not live data.

Done for Phase B = merged on master, no new failing test IDs, live `!all`/`!sec`/options replies coherent with
unchanged numbers, verifier agrees. The dashboard is still not launched.

## Phase C: launch (blocked on the user; do not start without their answers)

These are real outside requirements, not code. Synthetic tests never prove them.

| Gate | Status | Who |
|---|---|---|
| Disk: needs ≥10 GiB free and ≥15% free (≈11.3 GiB on the 75 GB disk) | MET 2026-10-05: 29 GB free (61% used) after the Drive offload (`todo/vps-offload-2026-10-05.md`). Recheck with `df -h /` before launch | done |
| Data-provider permission to show members data/analysis (Finnhub terms forbid sharing derived results without written OK) | none recorded; all real sources off | user |
| Assistant model access (dedicated key; design picked OpenAI `gpt-4o-mini-2024-07-18`) | none; assistant off | user |
| Provider quota/account evidence for the shared budget | unverified | user / research |
| HTTPS domain + certificate, production service users | not set | user decision, then agent |
| Same-server bot speed comparison with dashboard running | not measured (disk now OK, so it can run) | agent |
| Owner go-live approval | not given | user |
| 9 dev-tool advisories (`braces`, build-time only, no fix released) | accepted risk, tracked | none now |

Once the user answers, start a new session for Phase C with its own short plan. One implementer, a separate verifier.
