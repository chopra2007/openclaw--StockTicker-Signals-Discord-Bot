# Build the discover plugin rebuild (Workflow-engine edition)

**Status:** SHIPPED — v1.1.0 LIVE on `chopra2007/claude-discover` (pushed 2026-07-02, commit e975d23)
**Created:** 2026-07-02

**CURRENT STATUS (2026-07-02) — SHIPPED & LIVE:** The rebuilt discover plugin (**v1.1.0**) is pushed to the public repo and is being beta-tested from real projects. Tasks 1–10 built the whole plugin (Workflow-engine script with all 6 passes, stub harness 4/4 green, SKILL.md + references + README rewritten, tmux fully removed). Validated by THREE real runs through the actual Workflow engine on a toy project: (1) full Light 0→4 hands-off — 21 agents, 794k tokens, 18→3 survivors, high-quality artifacts (Pass-0 names real files, drops-log coded+evidenced, kill report labels single-family, final-plan has all 8 sections + a live_probe per feature); (2) budget-cap — clean partial-return at pass boundary + resumable on-disk state; (3) disk-resume `from_pass:4` — reparse-from-markdown + Pass-4 re-run works. Total test spend ~1.47M tokens, zero bugs beyond the one fixed. **One load-bearing bug caught & fixed:** the engine delivers `args` as a JSON string, so the plan's verbatim `const A = args` crashed instantly — fixed with a parse-guard (`typeof args==='string'?JSON.parse:args`). Evidence log: `tests/e2e-evidence.md` in the plugin repo.

**Deferred — run ONLY if beta surfaces a bug (recipes in the plan's Task 12):** B1 checkpoint-edit override · B2 kill+override · B4 mid-burst crash-resume · B5 broken booster · B6 vanilla-user (no boosters) · B7 outcome read-back · B8 old-run-dir message · B9 per-pass budget calibration (needs Standard/Deep runs; Light measured at 794k total, envelope validated). Also Task 13 independent verifier + Task 11 Pass-5 interactive build were not run — the SKILL.md front-of-house is instructions-to-a-session (not runnable code), so it surfaces naturally in real beta use. Deep dial budgets still extrapolated; Windows untested (README says so). Budget-gate unit note: `budget.spent()` meters output tokens while `passEst` was sized against total spend — mechanism correct, exact trip point is a calibration nicety.

**Key paths:** plugin repo `/root/work/claude-discover-publish/repo/` (branch `main`); script `skills/discover/workflows/discover-pipeline.js`; toy test project `/root/work/discover-toy/`.

**History:** 2026-07-02 — design + implementation plan complete and approved; execution Tasks 1–11 + subset of 12; shipped v1.1.0 same day.

## Goal

Rebuild the public `/discover` plugin so its research→plan passes run on Claude Code's built-in Workflow engine (clean memory, reliable hand-offs, crash-proof resume) with the smarter pipeline the user approved (evidence-rule kill-test, plan tournament, outcome memory), working for anyone on paid Claude Code ≥ 2.1.154, boosters optional. Ship as v1.0.0 to `chopra2007/claude-discover`.

## The three governing documents (read in this order)

1. **Plan (execute this):** `docs/superpowers/plans/2026-07-02-discover-rebuild.md` — 14 tasks with complete code, exact paths, per-task verification. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
2. **Spec (the authority on any ambiguity):** `docs/superpowers/specs/2026-07-02-discover-rebuild-design.md`.
3. **Design history (why decisions are what they are):** `todo/kickoffs/discover-rebuild.md` (local-only) + raw pressure-test findings `.omc/research/discover-rebuild-pressure-test-2026-07-01.json`.

## What's done

- Full brainstorm (2026-07-01→02): 26-agent adversarial pressure-test, 4 locked-decision amendments + recommendation package adopted, Piece 4 (testing) approved, spec written and user-approved, implementation plan written and self-reviewed.

## What's left (= the plan's 14 tasks)

Tasks 1–6 build the workflow script; 7 a stub harness; 8–9 rewrite SKILL.md; 10 README+manifests (v1.0.0); 11–12 real toy-project end-to-end + 8 branch tests + budget calibration; 13 independent verifier; 14 release (push needs user OK) + bookkeeping.

## Key constraints (full list in the plan's Global Constraints)

- Edit the source-of-truth repo only: `/root/work/claude-discover-publish/repo/`. Never edit the installed cache except the Task-11 sync.
- No prose fallback pipeline. No majority-vote kills. Disk artifacts beat the engine journal. Every drop logged.
- Commit per task in the plugin repo; push only at Task 14 with user confirmation.

## Open questions / expected residual gaps

- Budget numbers are CALIBRATE placeholders until Task 12 B9 (measured from real toy runs; Deep extrapolated).
- B2 (kill+override) and B6 (vanilla-user simulation) may end with an honestly-recorded residual gap — acceptable per spec §14, must be named in the final report.
- Windows untested (no machine) — README states it.
