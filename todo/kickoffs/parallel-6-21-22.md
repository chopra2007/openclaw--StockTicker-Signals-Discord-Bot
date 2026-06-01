# Kickoff: three discover runs for #6, #21, #22 (each its own 2–4 agents)

Run the `discover` plugin three times — once per TODO — each with its own 2–4 agents, in isolated worktrees, so no run bloats another's context or clobbers its files.

## The runs (paste ONE trigger line per fresh session)

**Run 1 — #21 SerpAPI failover** (independent; start anytime, parallel-safe):
```
discover: SerpAPI key/provider failover per todo/serpapi-key-failover.md — work in worktree /home/openclaw/wt-serpapi (branch feat/serpapi-failover), native layout, 2 agents, review-then-build, commit only (do NOT push). Read todo/kickoffs/parallel-6-21-22.md first.
```

**Run 2 — #6 broad !all improvements** (start anytime; MUST finish + commit before Run 3):
```
discover: improve what the !all command shows per todo/all-command-quality.md (non-risk fields — catalysts, trade plan, snapshot, etc.; the risk section is handled separately in #22) — work in worktree /home/openclaw/wt-allcmd (branch feat/allcmd), native layout, 4 agents, review-then-build, commit only (do NOT push). Read todo/kickoffs/parallel-6-21-22.md first.
```

**Run 3 — #22 risk-section round 2** (run AFTER Run 2 commits; SAME worktree/branch):
```
discover: sharpen the !all risk section round 2 per todo/all-risk-section-v2.md — work in the EXISTING worktree /home/openclaw/wt-allcmd on branch feat/allcmd (on top of #6's commits), native layout, 3 agents, review-then-build, commit only (do NOT push). Read todo/kickoffs/parallel-6-21-22.md first.
```

## Why this grouping (don't change it without checking files)
- #21 touches `gap_fill.py` + `config/consensus.yaml` — disjoint from the others → its own branch, runs in parallel.
- #6 and #22 BOTH edit `narrator.py` (+ `quality_bar.py`/`output_filter.py`). Separate branches would collide on merge and force a rebase. So they share ONE worktree/branch and run **sequentially: #6 first, then #22 on top.**
- Net: 2 worktrees, 3 discover runs. Two tracks run in parallel (wt-serpapi ‖ wt-allcmd); within wt-allcmd, #6 → #22 are serial.

## Worktree setup (run once, in the main workspace, before the discover runs)
```
git worktree add /home/openclaw/wt-serpapi -b feat/serpapi-failover
git worktree add /home/openclaw/wt-allcmd  -b feat/allcmd
```
Each discover run `cd`s into its worktree and does ALL work there. (Manual external-path worktrees are verified to isolate correctly here; the built-in `isolation:"worktree"` is BROKEN by the `/root/.openclaw` symlink — never use it. See memory `reference_worktree_isolation_broken`.)

## discover settings to use (answer its setup questions with these)
- **Layout:** native (no tmux; parallel `Agent` calls).
- **Agents:** #21 → 2, #6 → 4, #22 → 3 (all within your 2–4).
- **Mode:** autonomous for the research/planning passes (or pause-for-review if you want to steer).
- **Execution handoff:** review-then-build (see each plan before it builds).
- **Push:** OVERRIDE discover's Pass-5 push. This project's CLAUDE.md forbids mid-session push — let discover **commit only**; pushing happens at session close through the gate.

## Merge-back + go-live (after a run's discover reports success + tests green in its worktree)
1. Main workspace: `git merge feat/serpapi-failover` and (after #6→#22 done) `git merge feat/allcmd`.
2. Regression gate: `python3 -m pytest tests/ -n 2` — zero NEW failures vs `.test-baseline`.
3. Live check: restart `consensus-engine.service`, run a real `!all NVDA` (whitelisted webhook ID 1508945176335482880; output lands in the vault file). **A restart also activates any other pending work in the tree — coordinate with the wolf session before restarting.**
4. `git worktree remove /home/openclaw/wt-serpapi` and `/home/openclaw/wt-allcmd` when merged.

## Guardrails
- Never run two agents editing the same file at once. The grouping above guarantees no cross-track file overlap.
- If a second Claude session is open on this repo, commit early/often — uncommitted work in the shared tree is not safe (it got reset this way on 2026-05-31).
- The three TODO detail files already hold the verified findings + file:line pointers — discover should read them in Pass 0/1 rather than re-deriving.
