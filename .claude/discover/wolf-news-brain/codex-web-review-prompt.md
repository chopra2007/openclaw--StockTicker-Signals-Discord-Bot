# Paste this into Codex on the web (then append the two plan files below it)

You are doing an ADVERSARIAL PLAN REVIEW — do NOT write code. The codebase is the
public repo **github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot** (branch `master`).
Clone/open it and VERIFY every concrete claim the plan makes against the ACTUAL code (cite file:line).

The feature ("Wolf macro-brain"): rebuild a Gmail watcher to read an HTML trading newsletter
("Wolf on Wall Street") + its remote chart images (Gemini vision) + LLM structured extraction;
maintain stateful "theses" (forming→diverging→imminent→acting, active-until-invalidated);
a direction-aware confluence engine matching Wolf vs YouTube/options/Twitter/SEC at
market/sector/stock/asset scope; proactive #news Discord alerts (@-ping on critical) + scheduled
digests; beneficiary inference; Gmail backfill. It must run SEPARATE from the existing fast
ticker-alert pipeline. NOTE: the plan was already revised to a THIN phase-1 (reader→thesis→#news);
confluence/digests/beneficiary/backfill are deferred to phase 2+.

Already-found issues you do NOT need to re-report (they're in the PASS-3 section pasted below):
ticker_signals pollution, weekend pause, contradiction_index-is-live, monotonic-stage,
analyst crowding/Wolf-echo, equal-weight staleness, scope matrix, prompt-injection, SSRF, ping DoS,
confluence reading 3 tables not just signal_events, data-file paths, subject-gate dropping Wraps.

Your job — be adversarial and concrete; find what is STILL wrong, missing, risky, or OVER-ENGINEERED
(this is a non-coder's solo project — "simplest thing that works for a first live #news lane" matters):
1. CORRECTNESS vs THIS codebase: verify the integration points the plan names (main.py task list
   ~660-677, stop_event vs combined_stop weekend pause; db.py SCHEMA + _schema_versions=14→15;
   gmail_watcher.py _decode_body / _auth_results_pass / subject gate; alfred.py post/synth reuse;
   analysis/consolidation.py SOURCE_CLUSTERS; consensus_engine/data/sector_map.yaml). Flag any named
   function/line that is wrong or missing.
2. NEW gaps the prior reviewers missed.
3. OVER-ENGINEERING: is even the thin phase-1 too much? Anything to cut for a first verifiable lane?
4. SEQUENCING / hidden late risk.
5. PRODUCTION SAFETY: anything that could break the existing engine (shared files:
   gmail_watcher.py, main.py, llm_client.py, config.py+config/consensus.yaml, db.py,
   alerts/all_command/narrator.py+aggregator.py), crash the asyncio loop, blow the Gemini free-tier
   budget, or spam Discord.

OUTPUT: a prioritized list — BLOCKER / MAJOR / MINOR / SIMPLIFY — each with the concrete issue +
file:line evidence + a specific fix or simplification. End with one line:
VERDICT: BUILD-READY  or  VERDICT: REVISE (must-fix: ...).

---
## ↓↓↓ PASTE THE FULL CONTENTS OF THESE TWO FILES BELOW THIS LINE ↓↓↓
1. `.claude/discover/wolf-news-brain/final-plan.md`   (THE PLAN — includes a "PLAN REVISION" section at the bottom that supersedes earlier scope)
2. `.claude/discover/wolf-news-brain/pass-3-stress-tested.md`   (the already-found issues — context so Codex doesn't repeat them)
