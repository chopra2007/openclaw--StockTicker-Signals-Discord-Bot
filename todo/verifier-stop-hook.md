# Auto-run a separate verifier when work is claimed done (Stop hook)

**Status:** DONE 2026-07-07 — hook LIVE at `/root/.claude/hooks/verify-on-done.py`, wired into `/root/.claude/settings.json`
**Created:** 2026-07-06

**CURRENT STATUS (2026-07-07) — DONE.** Hook LIVE at /root/.claude/hooks/verify-on-done.py, wired into /root/.claude/settings.json; free/no-LLM, re-runs affected tests on a 'done' claim and blocks regressions.

## Why (context from the 2026-07-06 session)
- Repeated problem: when asked to verify, the SAME agent that did the work also verifies it, and does
  it badly (re-reads its own reasoning instead of independently re-running; biased to pass its own work).
- Best practice (human review + LLM "generator–critic"): a separate agent, with no stake in the answer,
  told to disprove, re-runs the actual behavior. See the global rule already in CLAUDE.md
  ("Never self-approve in the same active context; use code-reviewer or verifier for the approval pass")
  and the project regression-gate rule ("a separate agent, not the one that wrote the code, re-runs the suite").
- Claude Code supports the building blocks (subagents w/ isolated context, custom `.claude/agents/*.md`
  with restricted tools, `/code-review`, hooks) but has **no built-in "auto-verify with a different
  agent" toggle** — you assemble it. A Stop hook is how you make it happen automatically instead of
  hoping the working agent delegates.

## Phase 1 — Web research FIRST (the user's main requirement)
Research how developers using LLM coding agents (Claude Code, Cursor, Aider, etc.) implement hooks well.
Gather concrete, cited patterns on:
- **Context bloat:** keep what the hook feeds back to the model tiny + structured (PASS/FAIL + short
  findings), never dump full logs/test output into the transcript.
- **Effectiveness:** what actually catches defects vs. what's theater; adversarial framing; re-running
  behavior vs. re-reading code.
- **When to run vs. skip (the qualifier):** how others gate so the hook does NOT fire on every turn —
  changed-code detection (git diff), path filters, completion signals, debounce.
- **Avoiding per-turn slowdown:** short-circuit/early-exit cheaply, run heavy work async/background,
  cache, only-on-real-completion; measured latency impact others report.
- **Loop prevention + exit semantics:** `stop_hook_active`, exit 0 (allow) vs exit 2 (block + feed
  stderr back), blocking vs advisory.
- **Anti-patterns others hit:** hooks that spam, block forever, leak tokens, fire redundantly.
- Collect 3–5 real examples (repos/blog posts/docs) and distill a short "do / don't" list before coding.

## Phase 2 — Design (from the research + this session's discussion)
- **Event:** `Stop` (main agent finishing a turn). Consider `SubagentStop` too.
- **Qualifier (decides run vs skip):** only run when the turn left **uncommitted changes to CODE paths**
  (`consensus_engine/`, `scripts/`, `tests/`, `config/`) — skip docs-only and no-change turns. Mirrors
  the doc-only-vs-code split CLAUDE.md already uses. Objective (git diff), not wording-based.
- **Verifier:** a **read-only** agent (`.claude/agents/verifier.md`, `tools: Read, Grep, Glob`, no Write
  — structurally cannot self-approve by editing), adversarially prompted, that **re-runs the affected
  tests / exercises the real behavior**, not just re-reads. (Alt: invoke `/code-review`, or headless
  `claude -p`; research which is leanest.)
- **Enforcement:** exit 2 to block the stop + feed back a concise findings summary so the agent must
  fix; exit 0 to allow. Guard loops with `stop_hook_active`.
- **Keep fed-back output tiny** (structured verdict + top findings only).

## Phase 3 — Implement carefully + test
- Wire in `settings.json` (use the `update-config` skill). Script at `.claude/hooks/verify-on-done.sh`;
  agent at `.claude/agents/verifier.md`.
- Prove all four behaviors on real turns: (a) silent on a docs-only turn, (b) silent on a no-op/Q&A turn,
  (c) fires + blocks on a broken code change, (d) no infinite loop, (e) no noticeable per-turn slowdown.

## Files / paths involved
- `.claude/settings.json` (or `~/.claude/settings.json` if global) — hooks config.
- `.claude/hooks/verify-on-done.sh` — the qualifier + verifier-invocation script.
- `.claude/agents/verifier.md` — the read-only reviewer agent.
- Docs: code.claude.com/docs/en/hooks, /sub-agents, /code-review.

## Open questions
- **Blocking vs advisory:** block (exit 2, force fix) for code changes, or just warn? (research others' take)
- **Which verifier:** local read-only agent vs `/code-review` vs headless `claude -p` — leanest + most effective?
- **Scope:** this project only (`.claude/settings.json`) or all projects (`~/.claude/settings.json`)?
- **Don't duplicate the existing pre-push gate.** `scripts/pre-push` already runs pytest at PUSH time
  (git hook). This Stop hook is complementary — it runs a *reviewer agent* at COMPLETION time. Make sure
  they don't fight or double-run; decide the division of labor.

## Relationship to #68 (discover)
This is the **interactive-session** fix (normal coding work, and discover's Pass 5 build, which runs in
the main session). #68's per-pass checkpoint is the **in-pipeline** analog for discover Passes 0–4 (the
Workflow engine — a Stop hook does NOT reach inside those background passes). Same principle
(separate verification / fail-loud), two mechanisms for two environments.
