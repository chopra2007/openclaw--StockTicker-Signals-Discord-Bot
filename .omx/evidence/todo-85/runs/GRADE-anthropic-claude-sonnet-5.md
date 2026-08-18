# Grade — anthropic/claude-sonnet-5 (TODO #85)

Graded against `.omx/evidence/todo-85/answer-key-codex.md`.

## Q01 — PASS
**Verdict:** PASS
**Answer (verbatim, trimmed to the load-bearing part):** "Unusual options flow is primary-sourced from **Schwab's real-time option-chain API** (`consensus_engine/scanners/schwab_client.py`, called via `_schwab_flow_chains`/`_schwab_unusual_chains` in `consensus_engine/scanners/options.py`) — real-time, native greeks/IV, no delay. That's confirmed live in `config/consensus.yaml`: `features.schwab_options: { enabled: true, flow_loop_enabled: true }`... If a Schwab fetch fails for any reason, the code falls back to **yfinance** option chains (~15-min delayed) as a safety net — same file, `_fetch()`/`_f()` blocks..."
**Tools it actually called:** `exec(find ... options.py)`, `read(consensus_engine/scanners/options.py)`, `exec(grep -n "schwab_options" config/consensus.yaml)`
**Why:** Names Schwab as the live/primary source and correctly names the real internal module (`options.py`, `schwab_client.py`) — matches "Must contain." States yfinance as fallback, which the key explicitly says is "also correct, do NOT mark down." No invented path (`/root/.openclaw/workspace/scanners/unusual_options_flow.py` never appears). Answer is grounded in an actual `read()` of `options.py` plus a `grep` of the exact config line the key cites — not a guess.

## Q02 — FAIL (turn 2)
**Verdict:** FAIL
**Answer turn 1 (verbatim, trimmed):** "Unusual options flow ... is primary-sourced from **Schwab's real-time option chain API** (`consensus_engine/scanners/schwab_client.py`), gated by `features.schwab_options.enabled: true` in `config/consensus.yaml`... flipped on 2026-07-02 per that config comment. If Schwab fails ... `consensus_engine/scanners/options.py` falls back to **yfinance**..."
**Answer turn 2 (verbatim):** "(agent returned no content)"
**Tools it actually called:** `exec(find ... options.py)`, `read(consensus_engine/scanners/options.py)`, `exec(grep -n "schwab_options" config/consensus.yaml)` — turn 2 called nothing further.
**Why:** Turn 1 alone would pass — it names the specific internal module (`consensus_engine/scanners/options.py`) and the flow-loop/Schwab transition, satisfying Q02's "Must contain." But turn 2 is the deliverable the question is built to test (grading focus #1: "grade whether the live bot produces any real content at all for turn 2") and it produced literally none — reproducing the exact historical failure ("[assistant turn failed before producing content]") the test set exists to catch. A turn that returns nothing cannot be scored as narrowing to the internal feed, so the pair fails.

## Q03 — FAIL (both turns)
**Verdict:** FAIL
**Answer turn 1 (verbatim, trimmed):** "That thesis is marked `stale_review`, not `active`... **No.** There's no active Wolf newsletter thesis on GOOG/GOOGL specifically ... The closest match is a **HYPERSCALERS** group thesis (bear, imminent), ... currently marked `stale_review`... last live snippet: *'the hyperscalers have diverged more meaningfully and rolled over more sharply in June'* ... Wolf hasn't put out a dedicated Google call that's currently active."
**Answer turn 2 (verbatim, trimmed):** Same conclusion — no active GOOG thesis, HYPERSCALERS group is bear/imminent/stale_review, same June snippet, "no standalone, currently-active Google call I can pull an email excerpt for."
**Tools it actually called:** heavy real digging — `exec(wolf_email_excerpt --ticker GOOG)`, `--ticker GOOGL`, `--ticker HYPERSCALERS`, multiple `sqlite3 consensus.db "SELECT ... FROM macro_theses"` queries by `scope_key`, direction, stage, evidence_log_json. This is genuine tool use, not a guess.
**Why:** Directly contradicts the key on the two load-bearing facts. Key: **bullish**, stage **"forming"**, sourced from a specific Wolf newsletter email. Live answer: **bear**, stage **"imminent"** → **"stale_review"**, and explicitly denies there is any active/current Google thesis at all. This is a wrong-fact failure on both direction and stage — not a hedge, not a missing detail, but the opposite conclusion, delivered with confidence and heavy (real) tool evidence behind it. No internal ID leak (correctly avoids row/message IDs, matching "Must NOT contain"), but that doesn't rescue a wrong core fact. Turn 2 repeats turn 1's wrong answer rather than correcting it — it does not reproduce the *historical* mismatch bug (answering the previous question) or the ID-leak bug, but it fails on the primary content requirement both times.

## Q04 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "LLM request failed. Request timed out before a response was generated. Please try again, or increase `agents.defaults.timeoutSeconds` in your config."
**Tools it actually called:** Extensive real digging before the timeout — repeated `sqlite3 consensus.db` schema/data queries (`wolf_call_outcomes`, `signal_events`, `source_performance`, `alert_history`), a `grep` for `price_at_alert`, a read of `consensus_engine/eval/report.py`, and finally an attempted `python3 -c "from consensus_engine.eval import report; report.run(...)"` — then the turn aborted (`aborted: True`, 131.2s elapsed) before producing a reply.
**Why:** No root cause was ever delivered — no mention of `earnings_calendar.py` or `fetch_next_earnings_for_ticker`, and no answer of any kind reached the user. Per the grading rules this is a FAIL: a missing part (the entire answer) is an automatic fail, independent of cause. Unlike Q05-Q09, this is not the pre-authorization FailoverError pattern (no `stderr_tail`, `aborted: True` instead) — it looks like the model's own investigation ran long enough (131.2s, past this test's 120s speed flag) to hit the request timeout, not an infra pre-check refusal. Graded normally per instructions, this counts as a genuine FAIL: the bot investigated real tables but never converged on the earnings-calendar root cause before running out of time.

## Q05 — NOT RUN
**Verdict:** NOT RUN (infrastructure limit, not a quality failure)
**Answer:** "(unparseable stdout)"
**Tools it actually called:** none (`tools_seen: []`) — the request never reached the model.
**Why:** `stderr_tail` shows `FailoverError: ⚠️ openrouter (anthropic/claude-sonnet-5) returned a billing error — your API key has run out of credits or has an insufficient balance.` This is the reserved-128k-output-budget-vs-~110k-preauth ceiling, not a model answer. Not scored against the key.

## Q06 — NOT RUN
**Verdict:** NOT RUN (infrastructure limit, not a quality failure)
**Answer:** "(unparseable stdout)"
**Tools it actually called:** none.
**Why:** Same `FailoverError` billing/pre-authorization failure as Q05 — request never reached the model. Not scored.

## Q07 — NOT RUN
**Verdict:** NOT RUN (infrastructure limit, not a quality failure)
**Answer:** "(unparseable stdout)"
**Tools it actually called:** none.
**Why:** Same `FailoverError` billing/pre-authorization failure as Q05. Not scored.

## Q08 — NOT RUN
**Verdict:** NOT RUN (infrastructure limit, not a quality failure)
**Answer:** "(unparseable stdout)"
**Tools it actually called:** none.
**Why:** Same `FailoverError` billing/pre-authorization failure as Q05. Not scored.

## Q09 — NOT RUN
**Verdict:** NOT RUN (infrastructure limit, not a quality failure)
**Answer:** "(unparseable stdout)"
**Tools it actually called:** none.
**Why:** Same `FailoverError` billing/pre-authorization failure as Q05. Not scored.

## Scorecard

| Question | Verdict | One-line reason |
|---|---|---|
| Q01 | PASS | Schwab-primary/yfinance-fallback, correct real file paths, grounded in actual reads |
| Q02 | FAIL | Turn 1 solid, but turn 2 returned no content (exact historical bug reproduced) |
| Q03 | FAIL | Wrong facts both turns: says GOOG thesis is bear/imminent/stale, key says bullish/forming/active |
| Q04 | FAIL | Real investigation, but request timed out before any root cause was delivered |
| Q05 | NOT RUN | Infrastructure: OpenRouter pre-authorization billing failure before model saw the prompt |
| Q06 | NOT RUN | Same infrastructure failure |
| Q07 | NOT RUN | Same infrastructure failure |
| Q08 | NOT RUN | Same infrastructure failure |
| Q09 | NOT RUN | Same infrastructure failure |

**PASS 1 of 4 questions that actually ran (5 NOT RUN — infrastructure, not quality).**

## Speed

| Question | Elapsed (s) |
|---|---|
| Q01 | 37.7 |
| Q02 turn 1 | 30.1 |
| Q02 turn 2 | 15.2 |
| Q03 turn 1 | 82.3 |
| Q03 turn 2 | 17.2 |
| Q04 | 131.2 (aborted — request timeout) |
| Q05 | 13.5 (no model call) |
| Q06 | 12.6 (no model call) |
| Q07 | 12.2 (no model call) |
| Q08 | 16.7 (no model call) |
| Q09 | 12.5 (no model call) |

**Max elapsed: 131.2s (Q04).** This exceeds both the 120s flag and the ~150s Discord kill window by a thin margin (131.2s < 150s, so it would not have been killed, but it's close and it never even produced an answer — it burned the time and still returned nothing). Q03 turn 1 (82.3s) is the next-highest and stayed well under 120s. No answer that actually contained content took longer than 82.3s.

## Verdict on capability

On the questions that ran, this model demonstrates the task is achievable when it has time to finish: Q01 opened the real `options.py`, grepped the real config line, and gave the Schwab-primary/yfinance-fallback answer verbatim-correct against the key, and Q02's first turn independently reached the same correct, well-grounded answer with the specific internal module name and the flow-loop transition date. That's real evidence the underlying files and tools support a correct answer — a cheap model failing here would not mean the task is impossible. But two of the four questions that ran still failed for reasons a stronger prompt or more budget won't fix by itself: Q02's second turn silently returned nothing (same historical bug this test set exists to catch), and Q03 did extensive real database digging yet landed on the *opposite* of the correct thesis (bear/stale vs. the key's bullish/forming) — a genuine reasoning/retrieval error, not a hedge or a skipped file. And Q04's 131-second investigation timed out before it could state a root cause, which is a real usability ceiling given the live Discord path's ~150s kill window. So: the model is clearly capable of grounding itself correctly when it succeeds, but this run shows real failure modes (silent empty turns, wrong-direction conclusions from real data, and slow investigations that outrun the time budget) that are not just infrastructure noise.
