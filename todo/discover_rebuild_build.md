# Build the discover plugin rebuild (Workflow-engine edition)

**Status:** OPEN
**Created:** 2026-07-02

**CURRENT STATUS (2026-07-02):** Design + implementation plan COMPLETE and approved; zero code written yet. Next concrete step: execute the plan, Task 1.

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
