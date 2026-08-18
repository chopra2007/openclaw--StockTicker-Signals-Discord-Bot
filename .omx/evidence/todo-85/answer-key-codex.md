# Blind Answer Key — Discord Bot QA Test (TODO #85)

**Provenance — read this first.** This key was NOT written by Codex. The Codex CLI hit its account
usage limit on 2026-08-17 (`ERROR: You've hit your usage limit … try again at Aug 22nd, 2026`), so the
independent verifier role was filled by the **Gemini CLI** (`gemini --skip-trust -y`) instead — a
different model family from the bot under test, which is what the "independent" requirement is for.
The filename keeps the `-codex` suffix only because the TODO plan named Codex. Gemini read the current
files on disk with its own tools; it saw no bot answers, because none existed when it ran.

**Independently re-verified by Claude against the source** (not taken on trust) on 2026-08-17:
`features.internal_breadth.window` really defaults to **5** (`internal_breadth.py:86,233`); the
exclusions really are ApeWisdom / Form-4 / neutral-NULL (`internal_breadth.py:14-19`); and Schwab
really is tried first with yfinance as the fallback (`options.py:252-256`). The Q01 and Q05 entries
below were tightened by hand after that check.

It contains the facts a passing answer MUST state and identifies the stale or incorrect premises in the test questions.

## Q01
**Correct answer (plain English, as the owner should receive it):** The unusual options flow data is currently coming from the Schwab real-time feed. While the bot used to rely on delayed yfinance data, the `features.schwab_options` setting is now enabled, providing live flow-loop alerts and on-demand scans directly from Schwab.
**Grounded in:** `config/consensus.yaml` (line 956) and `consensus_engine/scanners/options.py` (lines 252, 525).
**Must contain:** That the live/primary source today is the **Schwab** real-time feed (`features.schwab_options.enabled: true`, `consensus_engine/scanners/schwab_client.py`), reached through `consensus_engine/scanners/options.py`.
**Also correct (do NOT mark down):** noting that **yfinance is still the fallback** when the Schwab fetch fails — verified at `options.py:252-256`, where the Schwab path is tried first and the code falls through to the unchanged yfinance block on error. An answer giving Schwab-primary-with-yfinance-fallback is the most accurate answer available and must score full marks.
**Must NOT contain:** References to the non-existent path `/root/.openclaw/workspace/scanners/unusual_options_flow.py`; or a claim that yfinance is the current PRIMARY source.

## Q02
**Correct answer (plain English, as the owner should receive it):** The internal source for this data is the `consensus_engine/scanners/options.py` module, which connects to the Schwab API client. The autonomous flow-loop (which monitors the market for unusual activity) was officially flipped to the live Schwab feed on July 2, 2026.
**Grounded in:** `consensus_engine/scanners/options.py` and `TODO.md` (line 387).
**Must contain:** The specific internal module name `consensus_engine/scanners/options.py` and mention the "flow-loop" or "Schwab" transition.
**Must NOT contain:** Generic definitions of options flow or repetition of the turn 1 answer without narrowing to the internal feed.

## Q03
**CORRECTION (2026-08-18, verified against the live database):** this entry was WRONG. There is no
Google thesis stored at all — `select scope_key from macro_theses` returns 41 keys and none of them
is GOOG or GOOGL (the list is BONDS, BTC, DXY, GOLD, OIL, YIELDS, DJIA, NDX, RUT, SPX, TRANSPORTS,
VIX, IGV, SMH, XLK, AAPL, ABI, COPPER, DBA, GDX, GLW, HYPERSCALERS, KWEB, MAGS, META, MGK, MOO,
MSFT, MSI, MU, NVDA, REMX, SILVER, SNDK, TECHNOLOGY, URA, UVXY, VEGI, VIXY, VVIX, VXX). The
"bullish / forming" answer below was not in the data. A correct answer today says Wolf has no
Google thesis on file and, ideally, names the tickers Wolf does cover. Earlier grades that marked a
"no thesis stored" reply as WRONG were themselves wrong and are corrected in
`model-race-and-live-proof.md`.

**Correct answer (plain English, as the owner should receive it):** Wolf's current thesis on Google (GOOG) is bullish, with the position marked as "forming." This thesis is sourced from a specific Wolf newsletter email, which can be retrieved and excerpted using the internal tool that pulls the text directly from the Gmail record.
**Grounded in:** `consensus_engine/db.py` (macro_theses table) and `consensus_engine/tools/wolf_email_excerpt.py`.
**Must contain:** The "bullish" direction and "forming" stage for Google. It must describe the source as a Wolf newsletter email.
**Must NOT contain:** Internal database row IDs (e.g., "row 59") or Gmail/Discord message IDs (e.g., `19e3c677b009e2b4`).

## Q04
**Correct answer (plain English, as the owner should receive it):** The false signals were caused by the earnings calendar function failing to filter out past report dates, which led to the bot returning dates that had already occurred as "next earnings." The code has since been updated to ensure only dates from today forward are returned as upcoming reports.
**Grounded in:** `consensus_engine/scanners/earnings_calendar.py` (specifically the `fetch_next_earnings_for_ticker` function).
**Must contain:** The specific root cause (failure to filter past dates) rather than just a description of the symptom.
**Must NOT contain:** Defensive language or a mere restatement of the "reported date hasn't happened yet" symptom.

## Q05
**Correct answer (plain English, as the owner should receive it):** There is no fixed list of tickers for signal breadth; any stock the bot tracks enters the breadth count automatically if it receives a qualifying bullish or bearish signal within a rolling 5-day window. Because of this, it is not possible to "add" tickers to a list—they are simply included as soon as they generate a signal from an informed source.
**Grounded in:** `consensus_engine/analysis/internal_breadth.py` — docstring lines 3-19 (what counts / what is excluded), `_lean()` line 101, the rolling-window distinct count at lines 183-188, and the window default `features.internal_breadth.window` = **5 calendar days** at lines 86 and 233. Source table: `signal_events`.
**Must contain:** (a) there is NO fixed ticker list / watchlist; (b) it counts **distinct tickers** with a qualifying bullish (`long`) or bearish (`short`) row in `signal_events`; (c) over a **rolling 5-calendar-day** window ending on the reported date, where the same ticker inside the window counts once; (d) it explicitly rejects the "add 2 more tickers to the list" premise and says qualifying tickers enter automatically when their signals arrive.
**May also state (correct, not required):** the excluded rows — raw ApeWisdom (`source_type='apewisdom'`), Form-4 insider rows (`form4`/`sec_form4`), and neutral/NULL directions — all listed in `EXCLUDED_SOURCES` and the module docstring lines 17-19.
**Must NOT contain:** An agreement to add tickers; a description of a static watchlist; a claim that the bot changed code or added the tickers; a wrong window length (anything other than 5 calendar days) stated as fact.

## Q06
**Correct answer (plain English, as the owner should receive it):** The expected move is not a directional price target; it is a volatility-derived range that tells you how far the stock is expected to move (up or down) by a certain date. It is calculated from the price of at-the-money straddles and indicates the market's expected "swing" size rather than predicting which direction the stock will go.
**Grounded in:** `consensus_engine/scanners/expected_move.py` (lines 1-15 and the `ExpectedMoveResult` dataclass).
**Must contain:** The distinction that it is a non-directional range derived from volatility/straddles, not a directional price target.
**Must NOT contain:** Any agreement that it tells the user which way the stock is going.

## Q07
**Correct answer (plain English, as the owner should receive it):** The VIX measures the expected volatility of the S&P 500, while the VVIX measures the volatility of the VIX itself. When the "fear of fear" is described as normal, it means that the cost of hedging against sharp changes in volatility is proportional to what the VIX currently suggests, indicating there is no extreme panic about the VIX spiking unexpectedly.
**Grounded in:** `consensus_engine/alerts/commands.py` (line 2257) and general system documentation for `!market`.
**Must contain:** Definitions for VIX (expected SPX volatility) and VVIX (volatility of VIX). A plain-English explanation of "normal" as protection costs being in line with expectations.
**Must NOT contain:** Raw math formulas or internal code variables.

## Q08
**Correct answer (plain English, as the owner should receive it):** The alert score is built from five main components: the base signal, other analysts, news catalysts, technical filters, and an LLM-derived score. The final score often differs from the raw sum because "quality gates" are applied, which can move the score either up or down depending on how well the signal passes specific verification checks.
**Grounded in:** `consensus_engine/models.py` (ScoreBreakdown) and the `cross_reference` function in `consensus_engine/cross_reference.py`.
**Must contain:** The five components (base, analysts, news, tech, llm) and the fact that quality gates can move the score in both directions (up and down).
**Must NOT contain:** The claim that gates only lower the score.

## Q09
**Correct answer (plain English, as the owner should receive it):** Analyst group alerts are triggered when multiple analysts agree on a direction within a specific timeframe, with the "Group bias" showing the count of bullish vs. bearish views. A single analyst tweeting does not trigger this alert; it requires at least two (or more) distinct analysts to confirm the move within the clustering window to fire.
**Grounded in:** `consensus_engine/analysis/herding.py` (the `detect_swarm` function).
**Must contain:** The concept of "Group bias" as a count of views within a window and the fact that a single analyst is not sufficient to trigger a group alert.
**Must NOT contain:** The implication that any single tweet triggers the same level of alert as a group agreement.

## Stale-prompt finding
In `consensus_engine/main.py`, the `_STEERING_TEMPLATE` constant contains a line stating: `(options.py = options flow via yfinance)`. This statement is now factually **wrong** and should be corrected. Since July 2, 2026, the primary data source for the options scanner and the autonomous flow-loop has been the **Schwab real-time feed**, with yfinance only serving as a secondary fallback. The prompt should be updated to say `(options.py = options flow via Schwab real-time)`.
