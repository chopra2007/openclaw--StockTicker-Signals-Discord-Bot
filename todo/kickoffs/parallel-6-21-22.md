# Kickoff: run discover for #6, #21, #22 — ONE session, sequential, worktree-isolated

**You (the human) do ONE thing:** in a fresh session, paste `run todo/kickoffs/parallel-6-21-22.md` (no `discover:` prefix — that would misfire on this file). Then answer discover's short setup questions when they pop up (recommended answers below). Everything else below is for the orchestrating session to execute.

**Orchestrator note:** for EACH feature, invoke the full `discover` skill (Skill tool, `skill: discover`) on that feature — i.e. run the complete 5-pass flow per feature. The user running this kickoff IS the explicit authorization to use discover; do not do an ad-hoc build instead, and do not start a single discover run on this kickoff file itself.

## Recommended answers when discover asks (every run)
- Run name → confirm the suggested one
- Layout → **native**
- Agents → **3** (use **2** for #21)
- Mode → **autonomous**
- Execution handoff → **review-then-build**
- (Pushing is OFF — see rule below)

---

## Orchestrator instructions (the session follows these in order)

This is ONE session running three discover runs back-to-back. Worktrees are used ONLY to keep this work isolated from the concurrent wolf session (which shares this tree and reset uncommitted files on 2026-05-31). The session stays the orchestrator; discover's own 2–4 sub-agents do the heavy lifting per run.

### Step 0 — set up two isolated folders (run once)
```
git worktree add /home/openclaw/wt-allcmd  -b feat/allcmd
git worktree add /home/openclaw/wt-serpapi -b feat/serpapi-failover
```
(External paths are verified to isolate correctly; NEVER use the built-in `isolation:"worktree"` — it's broken by the `/root/.openclaw` symlink. See memory `reference_worktree_isolation_broken`.)

### Step 1 — #21 SerpAPI failover (in wt-serpapi)
`cd /home/openclaw/wt-serpapi`, then run discover scoped to `todo/serpapi-key-failover.md`, native, **2 agents**, review-then-build. Build + test + commit to `feat/serpapi-failover`. **Commit only — do NOT push** (CLAUDE.md: push only at session close).

### Step 2 — #6 broad !all improvements (in wt-allcmd)
`cd /home/openclaw/wt-allcmd`, run discover scoped to `todo/all-command-quality.md` (non-risk fields; the risk section is #22), native, **3 agents**, review-then-build. Build + test + commit to `feat/allcmd`. Commit only, no push.

### Step 3 — #22 risk section round 2 (SAME folder, on top of #6)
Stay in `/home/openclaw/wt-allcmd` (still on `feat/allcmd`), run discover scoped to `todo/all-risk-section-v2.md`, native, **3 agents**, review-then-build. Build + test + commit. Commit only, no push.
(#22 MUST come after #6 — they edit the same files: `narrator.py`, `quality_bar.py`, `output_filter.py`.)

### Step 4 — merge back + go live (after all three are committed)
1. Back in the main workspace (`cd /home/openclaw/.openclaw/workspace`): `git merge feat/serpapi-failover`, then `git merge feat/allcmd`.
2. Regression gate: `python3 -m pytest tests/ -n 2` — zero NEW failures vs `.test-baseline`.
3. Live check: restart `consensus-engine.service`, run a real `!all NVDA` (whitelisted webhook ID 1508945176335482880; result lands in the vault file). **A restart also activates the wolf work — coordinate before restarting.**
4. `git worktree remove /home/openclaw/wt-serpapi` and `/home/openclaw/wt-allcmd`.

## If this session's context fills up partway through
discover saves each run to disk under `.claude/discover/<run-name>/`. Open a fresh session and type `discover: resume <run-name>` to continue that run with a clean slate — no work lost.

## Guardrails
- One run at a time in this session (sequential). discover's own 2–3 agents per run are the parallelism.
- #6 → #22 order is mandatory (same files). #21 is independent (different files).
- The three TODO detail files already hold the verified findings + file:line pointers — read them in discover Pass 0/1, don't re-derive.
