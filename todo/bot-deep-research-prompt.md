# Run the deep-research prompt for new bot features and fixes

**Status:** DONE 2026-07-09
**Created:** 2026-07-05

**CURRENT STATUS (2026-07-09) — DONE.** The last open dependency, #62's two forward-loggers, landed today. #63/#64/#65 were already done. The autonomous readiness-and-flip engine now has real data on both of its registered switches and re-tests itself every 2 days; `analyst_accuracy_promote` currently reports n=99, Wilson-LB 0.418 (not ready — correctly). Nothing further for a human to do.

## What this is

A ready-to-run research prompt asking a top-tier AI model to do a full architecture/design review
of the stock-signal Discord bot — find free, buildable-today improvements, brand-new feature ideas,
and fixes to existing reliability gaps, grounded in deep research (GitHub repos, papers, comparable
open-source projects), not just brainstorming from memory.

**The prompt file:** `todo/kickoffs/bot-research-and-build.md` (v2, 2026-07-05 — the one to run)

**To run it, paste this into a fresh session:**
`ultracode — read todo/kickoffs/bot-research-and-build.md and execute it end to end`

v2 supersedes `todo/kickoffs/bot-deep-research-merged.md` (kept as a paste-ready variant for an
outside model like Codex/Gemini that can't see this machine). What changed: v2 is written for a
Claude Code session running on this VPS, so it (a) verifies every architecture claim against the
real code, logs, and database before researching ("Phase 0 — ground truth"); (b) runs the full
six-lens deep research through the installed /deep-research plugin with citations, one run per
lens; (c) has the draft findings adversarially attacked by Codex and a critic agent before the
ranking is final; (d) stops and asks the user to pick what gets built (plain-English choices);
(e) builds the picks in the same run under the project's normal rules — dark flags, real-data
testing, regression baseline, separate verifier, flip-ON-by-default; and (f) hard-gates any
Wolf-extractor change on an eval set that includes the IGV incident and the 3 emails that broke
the last attempt.

The older merged file combined two drafts: my original grounded brief (this codebase's actual
architecture, data sources, and backlog) merged with Codex's more rigorous review structure (six
expert lenses — architect, quant researcher, AI systems designer, performance engineer, UX
reviewer, reliability engineer — plus a strict per-recommendation format requiring citations,
effort/impact/risk, and a "kill list" of backlog items worth abandoning). All of that content
carried forward into v2.

## What worked so far

- Two research forks (this session, 2026-07-05) grounded the prompt in real specifics rather than
  vague asks: a full inventory of free/buildable-today backlog items (the `!all` command's
  remaining levers, forward-data-logging gaps, the never-attempted 3-model-race latency fix), and a
  deep dive into the Wolf-newsletter false-signal history (real incidents, what was fixed, what's
  still an open gap).
- The user corrected an important nuance mid-session: the bot's real unsolved problem with Wolf's
  newsletter is not "Wolf changing his mind" — it's that a counter-trend rally (price going UP) can
  itself be the bearish signal ("short at the top of the counter-trend rally"), and the bot doesn't
  reliably tell that apart from a genuine bullish breakout. This is now the lead framing in the
  merged prompt's AI Systems Designer section, with the real IGV incident as grounding.
- Codex's restructuring added real value (multi-expert lenses, forced citations, explicit
  abandon-list ask) — folding it in produced a stronger prompt than either draft alone.

## Next step

**Run v2** — paste into a fresh session:
`ultracode — read todo/kickoffs/bot-research-and-build.md and execute it end to end`

The run handles everything end to end: research → a committed report at
`plans/bot-research-build-2026-07.md` → it pauses and asks you (plain-English choices) which
improvements to build → builds and verifies your picks → updates this TODO. Your only job during
the run is answering the mid-run questions. No obligation to pick everything it proposes.

## Files involved

- `todo/kickoffs/bot-research-and-build.md` — **v2, the prompt to run** (research → pick → build)
- `todo/kickoffs/bot-deep-research-merged.md` — v1, paste-ready variant for an outside model only

## Open questions

- None blocking — v2 is finished and ready to run. It stops mid-run for the user's build picks;
  that's the designed checkpoint, not a failure.

## Session notes — 2026-07-05 (prompt v2)

- User decisions captured this session: one run doing research → user picks → build (not
  report-only); runs as a Claude Code session on this VPS (not an outside model); research depth =
  full exhaustive across all six lenses.
- Claude decided the plugin routing inside the prompt: /deep-research per lens, SearXNG + firecrawl
  for fetching, Workflow engine for fan-out, Codex + critic agent as adversarial reviewers of the
  draft report, context7 for docs during build, AskUserQuestion for the checkpoint.
- Grounding facts verified against the repo before writing: Wolf pipeline lives in
  `consensus_engine/analysis/wolf_*.py`, the `!all` pipeline in
  `consensus_engine/alerts/all_command/` (13 files), flag-count claim "~89" is unverified (a quick
  grep found 61 `*enabled*` keys — v2 makes the run recount), and `GO-LIVE-LIST.md` no longer
  exists at the workspace root (v2 doesn't reference it).

## Session notes — 2026-07-05 (v2 RUN EXECUTED end to end)

Ran the full research→pick→build. Report: `plans/bot-research-build-2026-07.md`. Per-lens cited
research + verified facts + the Wolf eval corpus: `.omc/plans/bot-research-build/`.

**Headline finding (measured on the bot's own DB, adversarially re-verified):** the score has ~no
predictive edge — score→prob map is at the base-rate Brier floor, `final_score` AUC ~0.507 at 24h,
per-signal |IC|<0.03. Fired alerts (`alert_history`) go up 52.7% at 24h (barely above coin flip;
the "43.8% below coin flip" a reviewer reported was a NULL-as-failure artifact I corrected). 20d
score is anti-predictive (AUC 0.41). The 5 display signals + per-analyst outcomes are logged
NOWHERE, so "fold signals in" / "analyst retest" are forward-collection-blocked (→ #62).

**SHIPPED + LIVE this session:** (1) DB backup/integrity timer; (2) circuit-breaker persisted-OPEN
reload on startup (verified live); (3) `consensus_engine/eval/` measurement module (30 tests);
(4) holiday-aware price label + non-ASCII ticker reject; (5) `!all` loud-on-degraded banner;
(6) autonomous readiness-and-flip engine (`auto_flip_check.py` + timer every 2 days, next Tue
07-07 09:00 PDT; guardrails + verified flip round-trip). Commits 57f8179/3b65180/fbd3ae6/c9e3fbd
+ infra in /root/task_system.

**User decisions:** picked all Groups 1-3; parked market top/bottom predictor; stop multi-day score
use; kept "add more !all fields". Corrections after user pushback: MU really ~$1,150 (the "$1154
bug" pick dropped); social-dedup smaller than pitched.

**DEFERRED (new TODOs):** #62 forward-loggers, #63 honest decision-first alerts, #64 Wolf rebuild,
#65 social-dedup + idempotency. #61 stays OPEN until these land.
