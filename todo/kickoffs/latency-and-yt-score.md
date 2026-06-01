# Kickoff: discover-driven research→plan→review→execute for #6 latency + #19 YT-score

**You (the human) do ONE thing:** in a fresh session, paste this exact line (no `discover:` prefix — that would misfire on this file):

    run todo/kickoffs/latency-and-yt-score.md

Then answer discover's short setup questions when they pop up (recommended answers below). Everything else here is for the orchestrating session to execute.

**Orchestrator note:** for EACH of the two tasks, invoke the full `discover` skill (Skill tool, `skill: discover`) — the complete 5-pass flow IS the "research → plan → review → execute" the user asked for (Pass 0 existing-system analysis, Pass 1 external research, Pass 2 filter/prioritize, Pass 3 adversarial + ccg cross-model review, Pass 4 ralplan implementation plan, Pass 5 autonomous execute + verify). Running this kickoff IS the authorization to use discover. Do NOT do an ad-hoc build instead, and do NOT run discover on this kickoff file itself.

## Recommended answers when discover asks (each run)
- Run name → confirm the suggested one
- Layout → **native**
- Agents → **3** (Task A latency) / **2** (Task B yt-score)
- Mode → **autonomous**
- Execution handoff → **review-then-build**
- Pushing is OFF (commit only; push happens at session close)

## Step 0 — isolation (run once)
Only needed if another session is sharing this tree (e.g. the Wolf session). If the tree is yours alone, SKIP this and work on master with frequent commits.
```
git worktree add /home/openclaw/wt-latency -b feat/latency
git worktree add /home/openclaw/wt-ytscore -b feat/yt-score
```
External paths isolate correctly; NEVER use the Agent tool's `isolation:"worktree"` — it's broken by the `/root/.openclaw` symlink (memory `reference_worktree_isolation_broken`).

## Task A — #6 slow-response fix (in wt-latency, 3 agents) — DO THIS FIRST
**Problem:** the `!all` narrative takes 60–240s because the synthesis LLM chain walks models SERIALLY — each model gets a full timeout before the next is tried. Context: `todo/all-command-quality.md` (the "biggest optimization" note) and the chain probes in `.omc/research/llm-chain-2026-05-16/` (`probe_llm_chain.py`, `live_test_all.py`). The chain runs through `consensus_engine/llm_client.py:call_with_fallback` (used by `consensus_engine/alerts/all_command/narrator.py`).

discover should research and weigh the options in Pass 2/3, then build the best by impact × risk:
- (a) **race** the chain models concurrently, take the first good response;
- (b) **short per-model timeout** + fast failover;
- (c) **2-stage embed** — post the deterministic fields (~5s), then edit in the narrative when ready.

**HARD REQUIREMENT — put this in the plan's verification checklist:** faster WITHOUT quality loss. Measure real `!all` wall-clock before vs after on 3 tickers (e.g. NVDA / AMD / a mid-cap), AND confirm the narrative is equal-or-better (Layer-C blind-compare vs Gemini, or the chain probe). Speed that degrades the writeup FAILS the task.

**TRIPWIRE:** this touches shared LLM files (`llm_client.py`, `narrator.py`). Per CLAUDE.md, test EVERY feature that uses them — all of `!all` AND `@mention`/`!ask` (they share `llm_client`). Build + test + commit to `feat/latency`. Commit only, no push.

## Task B — #19 YouTube DB score weighting (in wt-ytscore, 2 agents)
**Research FIRST.** Context: `todo/youtube_db_score_weighting.md`.
Pass 0/1 must ANSWER, with quoted code evidence: do YouTube DB signals (video mentions, extracted levels) currently feed the `!all`/alert SCORE (`score_breakdown`), or only the narrator prose? Find and quote the scorer.

Then a real decision point: only implement weighting if the evidence shows it's missing AND worth adding. A well-evidenced "already weighted — here's where" OR "shouldn't be weighted — here's why" is a VALID DONE. Do NOT force-build a feature the research says isn't warranted.

If building: put it behind a config flag, calibrate it, and prove NO score regression on existing tickers (the alert philosophy bar still holds). Build + test + commit to `feat/yt-score`. Commit only, no push.

## Step 1 — order
Task A first (heaviest/riskiest, wants fresh context), then Task B. One discover run at a time in this session; discover's own 2–3 agents per run are the parallelism.

## Step 2 — merge + go live (after both are committed)
1. `cd /home/openclaw/.openclaw/workspace`; `git merge feat/latency`; then `git merge feat/yt-score` (resolve any overlap).
2. Regression gate: `python3 -m pytest tests/ -n 2` — zero NEW failures vs `.test-baseline`.
3. Live check: restart `consensus-engine.service`, run a real `!all NVDA` — **time it** to confirm it's faster, and confirm the writeup is still good; if #19 shipped, confirm the score now reflects YouTube signals. Coordinate the restart if another session is live.
4. `git worktree remove /home/openclaw/wt-latency` and `/home/openclaw/wt-ytscore`.

## If context fills mid-run
discover saves each run under `.claude/discover/<run-name>/`. Open a fresh session and type `discover: resume <run-name>` to continue with a clean slate.

## Guardrails
- One run at a time (sequential). #6 and #19 touch different areas (LLM-call path vs the scorer) so they're independent — but Task A's tripwire files are shared bot-wide; test broadly.
- The two TODO detail files already hold the verified context — read them in Pass 0/1, don't re-derive.
- Don't touch TODO #20 (Wolf) — that's a separate session's lane.
