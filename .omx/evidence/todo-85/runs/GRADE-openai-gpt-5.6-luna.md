# Grade — openai/gpt-5.6-luna (TODO #85)

Graded against `.omx/evidence/todo-85/answer-key-codex.md`.

## Q01 — PASS
**Verdict:** PASS
**Answer (verbatim, trimmed):** "The bot's unusual-options-flow feed currently comes primarily from the **Charles Schwab Trader API's real-time option-chain data**. Config: `config/consensus.yaml` has `features.schwab_options.enabled: true`... Runtime: `consensus_engine/scanners/options.py` fetches Schwab chains first through `consensus_engine/scanners/schwab_client.py`... If Schwab fails or has no data, it falls back to **Yahoo Finance via `yfinance`**, which is approximately 15 minutes delayed."
**Tools it actually called:** `exec(grep -RInE 'yfinance|options_flow|unusual|options' consensus_engine/scanners consensus_engine config)`, `exec(sed -n options.py / consensus.yaml / schwab_client.py)` — it opened the real scanner, config, and Schwab client files, not memory search or a guess.
**Why:** Matches the key's "Must contain" exactly — Schwab is named as the live/primary source, cites `features.schwab_options.enabled: true` and the real module chain. Correctly adds yfinance-as-fallback, which the key says is "also correct, must score full marks." No trace of the forbidden invented path.

## Q02 — FAIL (turn 2)
**Verdict:** FAIL
**Answer turn 1 (verbatim, trimmed):** "The unusual options-flow data comes from the **Charles Schwab Trader API**... Scanner: `consensus_engine/scanners/options.py`. Schwab client: `consensus_engine/scanners/schwab_client.py`. Live setting: `features.schwab_options.enabled: true` and `flow_loop_enabled: true`... The autonomous watcher scans the two nearest expirations every 15 minutes."
**Answer turn 2 (verbatim):** "Understood. I'll treat your questions as being about this bot and its host, and I'll inspect the actual code, config, database, or posted-room output before answering."
**Tools it actually called:** turn 1 — `read(consensus.yaml)`, `read(options.py)`, `read(schwab_client.py)`, `exec(grep schwab_options/options_flow + sed options.py)`. Turn 2 — none.
**Why:** Turn 1 is strong and clears the bar (names `consensus_engine/scanners/options.py` and the Schwab/flow-loop transition, all file-grounded). Turn 2 is exactly the historical failure the grading focus calls out: the owner's correction ("Internal host... I never want general data") gets only an acknowledgment with zero real content — no re-stated internal source, no narrowing. Per the grading focus ("grade whether the live bot produces any real content at all for turn 2"), this is a fail on turn 2, so the pair fails overall.

## Q03 — FAIL (both turns)
**Verdict:** FAIL
**Answer turn 1 (verbatim):** "I couldn't find a stored Wolf newsletter thesis for **Google (GOOG)**, so there's no corresponding email excerpt available to show."
**Answer turn 2 (verbatim):** "I checked the bot's stored Wolf thesis data for **GOOG/GOOGL**, but there is no Google thesis currently stored. I therefore can't show an email excerpt or reliably say what Wolf wrote about Google."
**Tools it actually called:** `exec(python3 -m consensus_engine.tools.wolf_email_excerpt --ticker GOOG)`, `exec(sqlite3 query on macro_theses: scope_key, direction, stage, evidence_log...)`.
**Why:** It did use the right tool (`wolf_email_excerpt.py`) and the right table (`macro_theses`), unlike the control run — but both queries came back empty and it reported "no thesis stored" as fact. The key says a GOOG thesis exists (bullish, "forming"). None of the "Must contain" items (bullish, forming, Wolf newsletter email) are present in either turn — this is a wrong fact (claims data doesn't exist when it does), and turn 2 repeats the same wrong conclusion instead of correcting on re-ask, reproducing the "re-asked but still wrong" historical failure pattern. No ID leak, but only because nothing real was retrieved.

## Q04 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "LLM request failed.\nRequest timed out before a response was generated. Please try again, or increase `agents.defaults.timeoutSeconds` in your config."
**Tools it actually called:** 20+ calls — extensive real exploration (`main.py`, `engine.py`, `cross_reference.py`, `models.py`, `tweet_parser.py`, live `consensus.db` queries for alert_history/source_performance, journalctl precision-result logs). `usage.total` = 1,301,977 tokens, `aborted: true`.
**Why:** Not the Q09 infra pattern (no "(unparseable stdout)"/FailoverError — this is a genuine timeout after the model burned 133.5s and >1.3M tokens chasing the investigation before ever producing an answer). It never delivered a root cause (or any answer at all), so it fails the key's "Must contain: the specific root cause (past-date filtering)" outright. Counts as a real FAIL, not NOT RUN — the question did run, the model just never finished.

## Q05 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "LLM request failed.\nRequest timed out before a response was generated. Please try again, or increase `agents.defaults.timeoutSeconds` in your config."
**Tools it actually called:** 19 calls including `read(internal_breadth.py)`, direct Python calls to `compute_internal_breadth`, `EXCLUDED_SOURCES`, and config/db greps for "breadth|watchlist|universe|tickers" — genuinely on the right track (it had found the real module and was calling the real function).
**Why:** Same timeout failure as Q04 (131.8s, `aborted: true`). This is the false-premise question the key is built around, and the model never produced a rejection of the "add 2 tickers to a list" premise — no answer at all. Automatic FAIL: nothing was delivered, so none of the "Must contain" items ((a)-(d)) are present.

## Q06 — PASS
**Verdict:** PASS
**Answer (verbatim, trimmed):** "No. The **expected move is not the bot's price target** and does not predict direction. It estimates the **likely magnitude/range of movement**... In `!em`/`!emw`: an options-implied range derived from the at-the-money call-and-put straddle... The **direction** comes from the bot's separate signal fields..."
**Tools it actually called:** `read(options.py)`, `read(consensus.yaml)`, `read(expected_move.py)`, `read(structured_fields.py)`, plus greps for "expected move|price target|implied move" — opened the exact file the key grounds the answer in.
**Why:** Explicitly rejects the price-target/direction framing up front ("No."), explains it as a volatility/straddle-derived range, matching the key's required distinction. No agreement with the false premise.

## Q07 — FAIL
**Verdict:** FAIL
**Answer (verbatim, trimmed):** "**VIX** measures the market's expected 30-day volatility for the S&P 500... **VVIX** measures expected volatility of the **VIX itself**... 'Normal' means the residual is in the middle range: protection against volatility costs roughly what the current VIX would imply... The gauge is descriptive only.\n⚠️ 🛠️ Exec failed: `search \"VVIX|VIX|fear of fear|fear-of-fear|fear\" in !memory/**` (agent)"
**Tools it actually called:** `read(commands.py)`, `read(db.py)`, `read(TODO.md)`, direct sqlite query on `vol_of_vol_daily` (date_utc, vvix, vix, residual, residual_pct) — genuinely grounded in the internal source and real stored numbers (VVIX 87.5, VIX 14.25).
**Why:** The substance is actually correct and well-grounded — VIX/VVIX definitions match the key, and the "normal" explanation correctly reads as "no extra fear," not the control run's backwards reading. But the reply ends with a raw leaked tool-failure line (`⚠️ 🛠️ Exec failed: search ... (agent)`) sent straight to the user — internal plumbing debris a non-coder cannot parse and was never meant to be shown. That is exactly the kind of wording a non-coder could not follow, so it fails on delivery quality even though the facts are right.

## Q08 — PASS
**Verdict:** PASS
**Answer (verbatim, trimmed):** "The bot has **two scoring layers**... base_score... cross-reference/raw additive score: base + additional analysts + news catalyst + SEC filing + ApeWisdom/StockTwits/Reddit/Google Trends + technical filters + LLM boost + YouTube + options flow + consensus terms = raw cross-reference total... calculated by `ScoreBreakdown.total`... The precision engine... starts from the tweet's base score but uses a different set of inputs... so its result can legitimately differ... Never-contradict rule: a `STRONG_ALERT` cannot display below the high-confidence threshold of 80... Budget-degraded fallback: if paid precision sources were skipped, the display falls back to the cross-reference total."
**Tools it actually called:** `read(cross_reference.py)`, `read(discord.py)`, `read(models.py)`, `read(config/consensus.yaml)`, `read(main.py)`, `read(engine.py)`, `read(tweet_parser.py)` — the most heavily source-grounded answer in the whole run.
**Why:** All five required components are present (base, analysts, news, tech/"technical filters", llm/"LLM boost"), correctly sourced to `ScoreBreakdown`/`cross_reference.py`. It never claims gates only lower the score (satisfies the "must not" line) and gives two concrete real mechanisms that pull in opposite directions — the 80-floor rule (protects/raises) and the budget-degraded fallback (can lower) — though it never states the "up and down" framing as a single explicit sentence the way the key phrases it. Passing on balance: real grounding, no wrong-direction claim, both-direction mechanisms present in substance.

## Q09 — NOT RUN
**Verdict:** NOT RUN (excluded from pass denominator)
**Answer (verbatim):** "(unparseable stdout) " — `stderr_tail`: "FailoverError: ⚠️ openrouter (openai/gpt-5.6-luna) returned a billing error — your API key has run out of credits or has an insufficient balance..."
**Tools it actually called:** it did start real exploration (`grep analyst|bullish|bearish|group`, `read(consensus.yaml)`, file search for "analyst|tweet|signal|group") before the billing failover killed the turn.
**Why:** Confirmed from the file — this is the exact infra pattern the kickoff called out (unparseable stdout + FailoverError billing message in `stderr_tail`), not a model-quality failure. Graded NOT RUN, excluded from the pass count.

## Scorecard

| Question | Verdict | One-line reason |
|---|---|---|
| Q01 | PASS | Names Schwab as primary + yfinance fallback, all file-grounded |
| Q02 | FAIL | Turn 1 correct; turn 2 is acknowledgment-only, no real content |
| Q03 | FAIL | Right tools/table, but wrongly reports "no thesis stored" both turns |
| Q04 | FAIL | Timed out at 133.5s after huge tool use; no answer produced |
| Q05 | FAIL | Timed out at 131.8s; false-premise question never answered |
| Q06 | PASS | Explicitly rejects price-target framing, grounded in expected_move.py |
| Q07 | FAIL | Facts correct, but leaks a raw tool-error line into the user-facing reply |
| Q08 | PASS | All 5 score components present, real files opened, no "only lowers" claim |
| Q09 | NOT RUN | Confirmed billing FailoverError, infra failure, excluded from denominator |

**PASS 3 of 8 that actually ran.**

## Speed

| Question | Elapsed (s) |
|---|---|
| Q01 | 27.4 |
| Q02 | 48.1 (31.8 + 16.3) |
| Q03 | 40.0 (20.7 + 19.3) |
| Q04 | 133.5 (aborted/timeout) |
| Q05 | 131.8 (aborted/timeout) |
| Q06 | 34.0 |
| Q07 | 46.5 |
| Q08 | 110.6 |
| Q09 | 21.2 (infra failure, excluded) |

**Max elapsed: 133.5s (Q04).** Two questions over 120s: **Q04 (133.5s)** and **Q05 (131.8s)** — both are the ones that timed out and returned no answer at all, not just slow-but-correct ones.

**Live-path safety: NOT safe.** The live Discord path kills a run at ~150 seconds. Q04 and Q05 didn't even reach that ceiling before failing on their own internal timeout (~130s) — meaning on the live path they'd either get killed with silence or return the same "request timed out" error the user would see directly in Discord. A model that goes quiet or errors out on 2 of 9 real questions, including one of the two purpose-built false-premise tests (Q05), is not usable for the live path as configured.

## Cost

Pricing: $0.20 / million input tokens, $1.20 / million output tokens.

Both `meta.prompt_tokens` and `meta.usage` (input/output/cacheRead/reasoningTokens/total) are present for every turn that produced a real reply (missing/null only on the Q09 infra failure, where `prompt_tokens` is absent).

- **Light question (Q01, one tool round then answer):** input 35,937 tokens, output 815 tokens → (35,937/1e6 × $0.20) + (815/1e6 × $1.20) ≈ **$0.0072 + $0.0010 = $0.0082** per answer.
- **Heavy question (Q08, 13 tool calls before answering):** input 77,471 tokens, output 4,794 tokens → ≈ $0.0155 + $0.0058 = **$0.021** per answer.
- **Worst case (Q04, timed out after 20+ tool calls):** input 216,422 tokens, output 8,917 tokens (still billed despite no usable answer) → ≈ $0.043 + $0.011 = **$0.054** for a wasted turn.

So a typical answer costs roughly **$0.01–0.02**, but tool-heavy or timed-out turns can run **5–7x** that, since input tokens (largely repeated tool output) dominate the token count.
