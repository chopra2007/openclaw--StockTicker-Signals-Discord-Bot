# Next-session backlog — handoff from 2026-05-29

Single entry point for a fresh session. Kickoff trigger for the user to type:
**"read todo/NEXT-SESSION-2026-05-29.md and proceed"**

Everything below is NOT started — only documented. Do it all in the new session, in roughly the suggested order. Each item notes effort and where the detail lives.

## Completion standard (read first)
Work autonomously through the WHOLE backlog. **Nothing is "done" until its goal is actually met and proven with evidence** — not "code runs," not "tests pass," not "service started." For every item: build → verify → **real-world / live test** the user-observable outcome → show the actual output. Follow the repo DoD (CLAUDE.md): test the whole feature you changed, run the always-on health checks after every restart, keep author/verify as separate passes, and push code through the pre-push gate (doc-only → `--no-verify`). Don't stop at the first plausible finish; force "what else?" For the two big builds (A2 chart→levels pipe, E options flow), do the research/diagnosis FIRST and surface the genuine user decisions (e.g. pay vs free for real-time options) rather than guessing. If a real blocker or a true design fork appears, surface it; otherwise keep going to completion.

---

## Already shipped + live this session (do NOT redo)
- **#2 (alert speed)** — DONE. Most was already built; notes corrected, dead config removed, Phase 2.2 won't-do. (`TODO.md` #2 marked done.)
- **#17 Task B (the Gemini limit)** — DONE + LIVE. `gemini-2.5-flash-lite`/`flash` 503 for video; switched to **`gemini-flash-latest`** + **fps 0.5** + 503 model-fallback + finish_reason capture; chain reordered so **Gemini video is primary, captions the fallback**. Engine restarted, running. See memory `reference-gemini-video-models`.
- **#17 Task A (two-call split)** — SHELVED (no output-cap; not the fix).
- **#17 Task C Phase 1 + 2** — DONE + LIVE. Chart numbers attach to a video's top ticker and reach the `!all` alert AI (Phase 1); a ±10% price-band filter drops gridline/cross-ticker noise (Phase 2). Verified via real `!all USCI`.
- **#3 (video-eval cron)** — ROOT CAUSE FIXED. Was testing a dead captions path; now tests Gemini (4/7, up from 1/7); false-failures removed.
- **Confirmed Gemini reads charts:** the DB holds real drawn levels (fib levels, price bubbles, annotations, option-chain dates, flow-tool rows) — not just gridlines.
- **Webhook:** old #chat webhook was dead; replaced in memory `discord_webhook.md`.

---

## The backlog (suggested order)

### D. Cleanup (do first — trivial, clears the decks)
- **D1.** Delete the throwaway probe/demo scripts in `.claude/discover/todo-2-3-17/` (`gemini_probe*.py`, `seed_and_verify_taskc.py`, `render_all_usci.py`, `live_test_parser.py`). They were one-off verification; safe to remove.
- **D2.** Soak-close in `TODO.md`: #2 (done), and consider closing #17 Task B. Tidy the index.

### A. Finish #3 — the chart-numbers → "levels" pipe (the real payoff)
Detail: `todo/gemini-video-eval-assertions.md` + `todo/youtube_vision_upgrade.md`.
- **A1 (quick — do before A2).** Find out WHY the forced-Gemini run produced 0 levels: read the eval video `4mSyMr8PGLI`'s transcript and run the level-finder on it. Determines whether the levels are *spoken* (classifier tuning) or *chart-only* (needs the new pipe). Don't guess — verify.
- **A2 (big — highest value).** Build the missing connection: take the chart price levels Gemini already reads (e.g. `381.61 = 61.8%` fib) and file them into the `youtube_levels`/`setups`/`catalysts` tables — applying the Phase-2 price-band filter so gridlines (0,10,20) aren't filed. This makes chart levels usable system-wide (scoring/cross-reference, not just the alert text) AND makes #3's A1–A3 pass. `classify_evidence` (video_classifier.py:714) currently reads only spoken spans; this adds a visual→levels path. Do NOT change the shared `get_youtube_evidence_for_ticker` return shape (cross_reference.py:233 hard-checks `=="setup"`).
- **A3 (medium).** Re-point #3's A1–A3 to assert "the chart levels Gemini reads get filed," not stale exact values (NDX 26165, MSFT Apr 29).
- **A4 (quick).** Make the cron's pass/fail honest — distinguish "Gemini reading works" from "levels-filing not built" instead of a blanket red.

### B. Polish #17 Task C
Detail: `todo/youtube_vision_upgrade.md`.
- **B1 (quick).** Strip leftover label noise from the alert — title cards ("The Stock Market"), promo codes ("WICKED50"), bare tickers still reach the narrator. Surface only useful items (price levels, fib levels, annotations, flow rows).
- **B2 (quick, once a fresh chart-heavy video lands).** Real before/after: run `!all` on a ticker with recent video coverage, show the alert with vs without chart numbers — the genuine quality proof.
- **B3 (big, maybe skip).** Task C Phase 3 — Gemini tags EACH number with its own stock (vs whole-video top-ticker). Only build if B2 shows multi-stock videos losing numbers. Risk: forcing a ticker per number invites hallucination — must allow "unlabeled."

### C. Robustness / monitoring (quick wins)
- **C1.** Coverage counter: log daily how many videos got the full Gemini read vs fell back to captions (free tier ≈ 3–4 videos/key/day), so chart-reading coverage is visible.
- **C2.** Persist the Gemini "why it stopped" signal (finish_reason) as a real telemetry field, so the next Gemini hiccup is visible immediately (today's diagnosis took ~12h).

### E. NEW FEATURE — near-real-time unusual options flow
Detail: **`todo/options-flow-realtime.md`** (= TODO #18). Research the data source FIRST (yfinance delayed chains / Firecrawl-scrape / Polygon / Tradier / paid flow feeds), reuse the DORMANT `scan_unusual_options_market` + the existing instant-trigger alert policy, define "unusual" thresholds, then build + verify. Central user decision: pay for true real-time vs accept ~15-min-delayed free.

### F. Unrelated open TODO
- **#6** — improve `!all` quality (one lever per session: max-pain, peer comp, options flow — note this overlaps with E). Detail: `todo/all-command-quality.md`.

---

## Suggested order
**D (cleanup) → A1 (verify) → A2 (the pipe) → B1 (strip noise) → C1/C2 (monitoring) → E (#18 options flow, the big new build) → A3/A4, B2/B3, F as time allows.**

A2 and E are the two big builds. E (options flow) is the user's new priority — give it real research before coding. Establish a test baseline (`make test-baseline`) before the big builds, and push code through the pre-push gate (doc-only → `--no-verify`).
