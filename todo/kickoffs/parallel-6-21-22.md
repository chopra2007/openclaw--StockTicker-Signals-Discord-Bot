# Kickoff: work #6+#22 and #21 in parallel, isolated, background

**Trigger (paste this one line into a fresh session):**
`run todo/kickoffs/parallel-6-21-22.md`

## Goal
Advance the open !all-improvement work as TWO independent streams, each in its own git worktree and driven by background agents, so this orchestrating session's context stays light (only summaries return here).

## The two streams (NOT three — see why)
- **Stream A — `!all` risk section (#6 + #22).** #22 is round 2 of #6; both edit the SAME files (`narrator.py`, `quality_bar.py`, `output_filter.py`). They CANNOT run in parallel with each other — run them as one stream, #22's fixes on top of #6. Plan source: `todo/all-command-quality.md` (#6) + `todo/all-risk-section-v2.md` (#22, has the verified fix list + file:line pointers).
- **Stream B — SerpAPI key failover (#21).** Touches `gap_fill.py` + `config/consensus.yaml` — disjoint from Stream A, so it runs in parallel safely. Plan source: `todo/serpapi-key-failover.md`.

## Why isolation is mandatory (hard lesson, 2026-05-31)
This repo has ONE shared working tree (the `/root/.openclaw → /home/openclaw/.openclaw` symlink). Two agents editing the same tree clobber each other — a concurrent session's worktree workflow silently reset uncommitted files mid-build. The Agent/Workflow built-in `isolation:"worktree"` is BROKEN here (it nests worktrees inside `.claude/worktrees/` and the symlink duplicates them). See memory `reference_worktree_isolation_broken`.
**Therefore: use MANUAL worktrees at EXTERNAL paths (verified working), never the built-in isolation. Commit early and often.**

## Setup the orchestrator should run
1. Create two external worktrees, each on its own branch:
   - `git worktree add /home/openclaw/wt-all-risk -b feat/all-risk-v2`
   - `git worktree add /home/openclaw/wt-serpapi  -b feat/serpapi-failover`
2. Dispatch ONE background agent per worktree (`Agent` with `run_in_background: true`), each told to:
   - `cd` into its worktree path and do ALL work there (never touch the other worktree or the main workspace).
   - Read its plan source file(s) above; for thoroughness it may run the `discover` skill scoped to that stream.
   - Build → write/update tests → run `python3 -m pytest tests/ -n 2` IN THE WORKTREE → commit to its branch. Establish the test baseline first.
   - Report back a summary only (keeps this session's context light).
3. Each agent runs `verify`/a separate reviewer before claiming done (author ≠ reviewer).

## Merging back (after a stream's agent reports success)
Worktree changes are NOT live until merged into the main workspace and the service restarts:
1. In the main workspace: `git merge feat/<branch>` (resolve any overlap — there shouldn't be cross-stream overlap by design).
2. Run the regression gate (`scripts/pre-push`, `pytest -n 2`) — no NEW failures vs `.test-baseline`.
3. For live verification, restart `consensus-engine.service` and run a real `!all NVDA` (see this session's pattern: webhook ID 1508945176335482880 is whitelisted; the live narrative lands in the vault file). NOTE: a restart also activates whatever else is in the working tree — check with whoever owns concurrent work first.
4. `git worktree remove /home/openclaw/wt-<name>` when done.

## Guardrails
- NEVER run two agents editing the same file. Stream A owns narrator/quality_bar/output_filter; Stream B owns gap_fill/config. If a real overlap appears (gap_fill is touched by both the macro query and #21), sequence those, don't parallelize.
- If another Claude session is open on this repo, prefer worktrees + frequent commits — uncommitted work in the shared tree is not safe.
- Doc/TODO commits push with `--no-verify` at session close; code changes go through the full gate.

## Simpler fallback (if worktrees feel heavy)
Do the two streams one at a time as separate `discover` runs in the main workspace. `discover` already keeps each run's context lean (sub-agents + on-disk artifacts) and supports separate-session handoff. Zero conflict risk; trade-off is sequential, not simultaneous.
