# Next-session backlog — `!all` quality levers + peer/sector overhaul

Single entry point for a fresh **discover** run. The work: two `!all` quality levers (max-pain, peer comparison), the sector-map overhaul that peer comparison needs, and the two leftover YouTube items (B2/B3).

## Approach (read first — this governs HOW you work, and overrides blind plan-following)

1. **The plan below is a starting point, not gospel — find the BEST way.** For each item, before writing code, ask: *is there a better way to hit the user-observable goal than what's written here?* If yes, do that instead and note why. If the written approach really is best, proceed with it. Don't follow it blindly; don't change it just to change it. The author of this file may have missed a simpler/stronger path or gotten a detail wrong.
2. **Verify everything — never assume.** Every claim in this file (and every claim you're about to make about code, data, APIs, file paths, behavior) gets checked against reality first — grep/read the actual code, probe the actual API, query the actual DB. The plan's descriptions are leads to confirm, not facts to build on. If you can't verify it, say so; don't assert it.
3. **Run live tests — assume you CAN, not that you can't.** Default to "there is a way to test this for real from here," because there almost always is. If the first attempt is blocked, work the ladder: diagnose the real cause → fix the request/params → try an alternative path (different endpoint, different auth, process a real video, hit the real chain) → only then consider it untestable, and even then say exactly what you tried. "I don't think I can live-test this" is usually wrong — push past it. (See CLAUDE.md "Real-World Testing" + "Diagnose + explore alternatives.")

## Completion standard (read first)
Work autonomously through the whole backlog. **Nothing is "done" until its user-observable outcome is proven with real output** — not "code runs," not "tests pass." For each item: build → verify → **real-world / live test** → show the actual output (a real `!all <TICKER>` embed showing the new field; a real before/after). Follow repo DoD (CLAUDE.md): test the whole `!all` feature you touch, run always-on health checks after every restart, keep author/verify separate, push code through the pre-push gate (doc-only → `--no-verify`). Do the research/diagnosis FIRST for peer comparison + max-pain, and surface the genuine user decisions (listed per item) rather than guessing. FREE data only (yfinance is already in hand). Per the #6 execution discipline: name the crisp user-observable outcome before writing code; pre-flight any external source (these use yfinance, already proven).

---

## Already shipped this session (do NOT redo)
- **#18 options flow** — DONE + live (autonomous watcher + `!all` feed; yfinance ~15-min). See `.claude/discover/backlog-2026-05-29/`.
- **#3 A2** chart-numbers→`youtube_levels` pipe; **#3 A1/A3/A4** (cron honest); **#17 B1/C1/C2**. All pushed, verified.
- Dead duplicate Form-4 functions removed from `main.py`.

---

## The backlog (suggested order)

### 1. Max-pain lever (#6) — cheapest win, data already in hand
- **Goal/observable:** `!all NVDA` shows a **max-pain price** (the strike where the most open options expire worthless — acts like a price magnet near expiry).
- **How:** compute from the option chain — sum (open-interest × payout) across strikes, find the price with the lowest total payout. The yfinance option-chain access is ALREADY built for the options-flow scanner (`scanners/options.py:_fetch_flow_chains`). No scraping.
- **Plug-in points:** `alerts/all_command/aggregator.py` (fetch + compute), `narrator.py` / `structured_fields.py` / embed (display).
- **User decision to surface:** show max-pain in the embed field, in the narrator thesis, or both? Which expiry (nearest, or nearest monthly)?

### 2. Peer comparison lever (#6) — relative strength
- **Goal/observable:** `!all NVDA` shows something like *"NVDA +10% vs Semiconductors +5% → outperforming (bullish)."*
- **Signal (user-confirmed):** it's **relative strength**, not just "is the move sector-wide." Sector +5% but NVDA +10% = NVDA outperforming = legit bullish. Compute the stock's move minus its peers' average; outperform = bullish, underperform = bearish.
- **Needs item 3** (the sub-industry peer layer).
- **User decisions to surface:** benchmark = a narrow sub-industry **ETF** (simple, one number, e.g. SMH for semis) vs a curated **peer-stock list** averaged (more precise, more upkeep)? Over what window (1-day, 5-day)?

### 3. Sector-map overhaul (supports #2) — make it finer + more complete, REGRESSION-SAFE
- **Current state (verified this session):** `consensus_engine/data/sector_map.yaml` = **63 tickers → 10 broad sector ETFs** (XLK has 28 names: NVDA, Apple, Microsoft, Salesforce all lumped together). It maps ticker→sector-ETF, not ticker→peers.
- **Problems for peer comparison:** (a) too coarse — NVDA's real peers are semis (AMD, AVGO, INTC, TSM), not Apple; comparing to all-of-XLK dilutes the signal; (b) only 63 tickers — the bot alerts on far more; unmapped tickers get no comparison.
- **HARD CONSTRAINT — do NOT mutate the existing map.** `consensus_engine/analysis/sector_confirmation.py` uses it as a **live alert gate** (the A4 sector-confirmation gate). Changing its structure/values risks breaking that gate. **ADD a separate sub-industry / peer layer** (new file or new keys) for peer comparison; leave the ETF gate map untouched.
- **Make more complete:** broaden coverage beyond 63 tickers AND add a **dynamic fallback** — for an unmapped ticker, pull its sector/industry from yfinance `.info` (`sector` / `industry`) at runtime, cache it. Curated map = fast path; dynamic = catch-all.
- **Mapping model (user-confirmed):** stocks in the same group SHARE the group label; each stock's peer set = the others in that group (itself excluded). NVDA/AMD/INTC all → "Semiconductors"; NVDA's peers = {AMD, INTC, ...}.

### 4. B2 (#17) — before/after chart-numbers demo
- **Goal/observable:** run `!all <TICKER>` on a stock with fresh video coverage, show the alert WITH vs WITHOUT the chart numbers Gemini read — the genuine quality proof for the #3 A2 / #17 Task C work.
- **How (corrected this session):** NOT blocked. Process a fresh **chart-heavy** video from a followed channel through Gemini — one run creates BOTH the signal (`youtube.py:281`) and the visual chart numbers, so attribution works (`get_youtube_visual_evidence_for_ticker` joins them). The old DB videos with chart data (e.g. `2UUTK-lntus`, 44 chart rows) have NO signal row, which is why they don't surface — a quirk of those rows, not a block.
- **Caveats:** costs a Gemini call (free tier ~3-4 videos/key/day); pick a genuinely chart-heavy video so there's a visible before/after; Gemini's visual capture varies run-to-run.

### 5. B3 (#17, optional) — per-number ticker tagging
- Today all of a video's chart numbers attach to the video's TOP ticker. B3 = have Gemini tag EACH number with its own stock. **Only build if B2 shows multi-stock videos losing numbers.** Risk: forcing a ticker per number invites hallucination — must allow "unlabeled."

---

## Suggested order
**1 (max-pain) → 3 (sector layer) → 2 (peer comparison) → 4 (B2) → 5 (B3 if needed).**
Max-pain is independent and cheap. Sector layer unblocks peer comparison. B2/B3 are the YouTube tail.

## Key file pointers
- `consensus_engine/analysis/sector_confirmation.py` + `data/sector_map.yaml` — existing ETF gate map (DON'T mutate).
- `consensus_engine/scanners/options.py` — yfinance option-chain access (reuse for max-pain).
- `consensus_engine/alerts/all_command/{aggregator,narrator,structured_fields}.py` + embed — where levers plug in.
- `todo/all-command-quality.md` — the #6 lever menu + full `!all` architecture map.
- `.claude/discover/backlog-2026-05-29/` — this session's options-flow run (reference for yfinance patterns).

Establish a test baseline (`make test-baseline`) before the big builds.
