# Autonomous kickoff — TODO #6 (`!all` quality) + #19 (YouTube DB score weighting)

You are running this session autonomously. Research, build, fix, and **live-test** improvements
for these two open TODOs. Do not ask permission to start, do not ask "shall I continue."
Assume you have access to every tool, key, site, and service — if something appears blocked,
diagnose and route around it (see the real-world-testing ladder in CLAUDE.md) before ever
concluding it can't be done. Stop ONLY for the three gates listed at the bottom.

## Source of truth — read these first, assume nothing

- `todo/all-command-quality.md` — TODO #6. The architecture map, the lever menu, and the
  **execution discipline** section are non-negotiable. Re-read them; do not work from memory.
- `todo/youtube_db_score_weighting.md` — TODO #19. The four research questions and the
  priority-ordered next steps.
- `CLAUDE.md` — Definition of Done, Regression Gate, Alert Philosophy, Real-World Testing ladder.
- Prior art for #6: `.claude/discover/all-command-rebuild/v2-quality-rebuild/` and any
  `external-feature-audit-*.md` already on disk. Don't redo audits that already exist — extend them.

## Research mandate — find NEW ideas, don't just pick from the existing menu

The documented lever menu in `all-command-quality.md` and any prior audit are a *floor, not a ceiling*.
A real chunk of this session is open-ended discovery: surface features, optimizations, and fixes that
nobody has written down yet. Spend material time here before settling on what to build.

Three tracks — keep them distinct so none gets skipped:

1. **New features** — what do competing tools (TipRanks, Unusual Whales, Finviz, Koyfin, Benzinga,
   TradingView, fintwit, top WSB/r-options DDs) surface on a ticker page that `!all` doesn't? Go past
   the rows already in the audit; look for the gaps nobody's logged. Every candidate gets the
   pre-flight access test before it counts as buildable.
2. **Optimizations** — not new output, but the same output cheaper/faster/more reliably. Profile the
   real `!all` path: where does the 60–180s cold latency actually go? Which LLM calls or web fetches
   dominate token cost? Any redundant fetches, missing caches, serial calls that could be parallel,
   oversized prompts? Measure with real timings, don't theorize. The cache notes in
   `all-command-quality.md` are starting points, not the whole list.
3. **Fixes / latent bugs** — while tracing the code, log anything wrong: silent failures, stale config
   keys (like the `features.serpapi_enabled` bug already found), values that look computed but are
   hardcoded, error paths that swallow exceptions. Small correctness fixes are fair game to ship.

Capture findings from all three tracks as a short ranked list (impact × cost) and fold the buildable
ones into the audit table. THEN pick what to ship per the #6 steps below. For #19, also ask the
research question one level up: beyond "is YouTube weighted," is the whole score breakdown honest and
well-calibrated, or are other sources mis-weighted too? Note anything you spot, even if out of scope.

## Step 0 — baseline before any code (Regression Gate, CLAUDE.md)

1. Confirm `consensus-engine.service` and `openclaw-gateway.service` are both `active`.
2. Confirm `/root/.openclaw` still resolves to `/home/openclaw/.openclaw`.
3. `make test-baseline` (or read `.test-baseline`) so you know which tests were already red.
   No commit may turn a green test red.

## TODO #19 — YouTube DB score weighting (do this one first; it's bounded)

It is a research-then-maybe-implement task with a clear decision gate.

1. **Answer the four questions in the detail file with evidence, not guesses.** Grep the scorer
   (`consensus_engine/scoring/`) for `youtube`. Trace whether `youtube_signals_db` /
   `youtube_levels_db` / `youtube_evidence_db` actually reach the score computation, or are only
   passed to the narrator. Quote the lines you find.
2. **Prove it with a test**, don't infer: monkeypatch a non-empty `youtube_signals_db` and assert
   whether the numeric score moves. Show the actual before/after numbers.
3. **Visibility fix you CAN ship confidently:** if YouTube data is fetched but invisible in the
   `Score: 45 (news=15, ape=10, tech=6, llm=14)` footer, add a `yt=N` term to the breakdown so it's
   honest about what contributed. Live-test it: run a real `!all <ticker>` for a ticker that has
   YouTube signals and show the new footer.
4. **The actual weight is a behavior change — that's a review gate.** If the answer is "YouTube is
   unweighted and should contribute points," do NOT silently pick a number that changes which alerts
   fire. Build the weighting behind the existing config pattern, show before/after on real tickers
   (including at least one where the new weight would flip a borderline alert), and **pause for review**
   with your recommended starting value (the detail file suggests 5–10 pts, capped — justify whatever
   you land on). Adding visibility ≠ changing alert behavior; ship the first, gate the second.

## TODO #6 — `!all` output quality (open-ended; ship at least one verified lever)

Follow the execution discipline in `all-command-quality.md` verbatim. In order:

1. **Name the user-observable outcome first.** "The embed shows a max-pain field for every ticker,"
   not "max-pain integration is in." If you can't state it crisply, pick a different lever.
2. **External feature audit / refresh.** If a recent `external-feature-audit-*.md` exists, read it and
   pick the highest-leverage unbuilt row (best ratio of "shows up everywhere" to "cheap to build" AND
   pre-flight = worked/N-A). If none exists or it's stale, do the web research pass and produce/update
   the audit table at `.claude/discover/all-command-rebuild/external-feature-audit-<today>.md`.
3. **Pre-flight any external source BEFORE writing integration code.** Actually hit Unusual Whales /
   TipRanks / Finviz / OptionStrat / Koyfin / whatever the lever needs from THIS VPS with
   Firecrawl/WebFetch/curl and confirm you can extract the exact field. Blocked + no workaround →
   record it in the audit and pick a different lever. This prevents building an end-to-end integration
   that dies at live-test time.
4. **Ship one lever end-to-end**, then live-verify it: run a real `!all <ticker>` on 2–3 tickers and
   paste the actual embed/footer output showing the new field. Code-functional or "service started"
   does NOT count (Evidence Standard, CLAUDE.md). Prefer levers that change the actionable numbers
   (`structured_fields.py` / `levels.py`) since the 2026-05-16 test showed all chain models emit the
   same trade-plan numbers — but a verified prose/feature lever is fine too.
5. If time/tokens remain after one verified lever, pick a second. One *verified* lever beats three
   half-built ones.

## Verification — every change, every time (CLAUDE.md Definition of Done)

- Shared-file tripwire: if you touch `llm_client.py`, `config.py`/`consensus.yaml`, `db.py`,
  `narrator.py`, or `aggregator.py`, test EVERY feature that uses them, not just your line.
- Always-on after every restart: both services `active`, no `❌ GATEWAY drift` alert, no LLM-health
  failure alert, symlink intact. Verify AFTER each restart, not before.
- A separate verification pass (fresh agent, not the one that wrote the code) re-runs the full suite
  and diffs `.test-baseline` at the end. Any newly-red test is a regression — fix before declaring done.
- Trace input→output and show the real output for each distinct claim. `!all` commands and
  `@-mention` are different code paths — test each you touched separately.

## Git

- Commit locally after each functional change (imperative messages). Do NOT push mid-session.
- Push + full regression gate happen only at session close ("bye"). Don't mention CI otherwise.

## Update the TODOs as you go

- For each shipped lever on #6: append a dated note to `todo/all-command-quality.md` (commit hash +
  the live-verified outcome). #6 stays OPEN — it's a menu.
- For #19: if you ship the visibility fix and the research is conclusive, append findings + decision
  to `todo/youtube_db_score_weighting.md`. Mark it DONE only if both the research answer is settled
  AND the visibility fix is live-verified. If the weight change is left at the review gate, keep it OPEN
  and note exactly what's pending sign-off.

## Stop ONLY for these three gates

1. An external data source the chosen lever NEEDS is genuinely blocked from this VPS and you've
   exhausted the diagnose → fix → alternative-path ladder with no workaround. Report what you tried.
2. A change to the actual **scoring weight** (TODO #19 step 4) that would alter which alerts fire —
   present before/after evidence and your recommendation, then wait.
3. A genuine ambiguity in intent that you cannot resolve from the code, the TODO files, or sensible
   defaults — surface the specific options, don't pick silently.

Anything else — keep going.
