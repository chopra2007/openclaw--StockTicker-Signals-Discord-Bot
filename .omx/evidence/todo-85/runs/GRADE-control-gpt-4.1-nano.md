# Grade — control run, gpt-4.1-nano (TODO #85)

Graded against `.omx/evidence/todo-85/answer-key-codex.md`.

## Q01 — FAIL
**Verdict:** FAIL
**Answer (verbatim, trimmed):** "I couldn't find specific information about the source of the unusual options flow data in the system's memory. ... This data likely comes from the options flow scanner module (`consensus_engine/scanners/options.py`) ... For exact details, I would check the code module at `/home/openclaw/.openclaw/consensus_engine/scanners/options.py` or the system configuration in `config/consensus.yaml`."
**Tools it actually called:** `memory_search(unusual options flow data)`
**Why:** Never opened `options.py` or `config/consensus.yaml` — only ran a memory search, then guessed. Never names Schwab at all, so it fails the "Must contain: Schwab is the live/primary source" requirement outright. Uses hedge language the key explicitly flags as a fail trigger ("likely comes from", "I would check", "I couldn't find"). Also cites a nonexistent path (`/home/openclaw/.openclaw/consensus_engine/scanners/options.py` — missing `workspace/`), close to but not the forbidden invented path, still ungrounded.

## Q02 — FAIL (both turns)
**Verdict:** FAIL
**Answer turn 1 (verbatim):** "The options flow data likely comes from a dedicated Discord channel, as indicated by the `options_flow_channel_id` parameter set to \"1512934341485924432\" in the configuration."
**Answer turn 2 (verbatim):** "Understood. I will focus solely on data and information related to this system and its configuration, code, or stored data. Let me know if you need any specific system details or analysis."
**Tools it actually called:** `memory_search(unusual options flow)`, `read(config/consensus.yaml)`
**Why:** Turn 1 names a Discord alert-delivery channel ID, not the internal module (`consensus_engine/scanners/options.py`) or the Schwab flow-loop transition the key requires — wrong fact entirely. Turn 2 is the exact historical failure the grading focus calls out: it produces no real content, just an acknowledgment, and never narrows to the internal feed as instructed.

## Q03 — FAIL (both turns)
**Verdict:** FAIL
**Answer turn 1 (verbatim):** "I couldn't retrieve the specific email excerpt where Wolf mentions Google. Would you like me to try again or look up something else?"
**Answer turn 2 (verbatim):** identical to turn 1.
**Tools it actually called:** `write(reply.txt)`, `write(query.txt)`, `memory_search(Wolf about Google email excerpt)`
**Why:** No thesis direction ("bullish"), no "forming" stage, no source description — nothing in the "Must contain" list is present. Never used `wolf_email_excerpt.py` or read `db.py`'s `macro_theses` table. Turn 2 is a verbatim repeat of turn 1's failure — reproduces exactly the "re-asked 5 times, still fails" historical pattern the grading focus was checking for. (No ID leak, but only because nothing was answered at all.)

## Q04 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "Given the persistent error with reading large data, I am unable to access the database contents directly. To troubleshoot the false signals, I recommend checking the raw signal data, recent token flows, or alert logs more selectively, or perhaps inspecting configuration files related to signal thresholds and filters. Would you like me to review specific config files or perform a different targeted check?"
**Tools it actually called:** `read(consensus.db)` (binary file, no real read), `memory_search(wolf_news_alerts)`
**Why:** No root cause named. Doesn't mention the earnings calendar, `fetch_next_earnings_for_ticker`, or past-date filtering at all — the one thing the key says a passing answer must contain. Purely defensive/deflecting language ("I recommend checking...", "Would you like me to..."), which is exactly what the grading focus said to fail on.

## Q05 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "The current signal breadth includes the following tickers: Gold (GOLD), Ura (URA), MOO (Moo), Oil (OIL), DXY (Dollar Index), DBA (Agricultural ETF), REMX (Rare Earth Elements), BTC (Bitcoin), SPX (S&P 500 Index). Please provide the two additional tickers you'd like to add, and I will update the list accordingly."
**Tools it actually called:** `read(consensus.db)`, `memory_get(macro_theses)`, `exec(sqlite3 ... SELECT * FROM macro_theses LIMIT 10;)`
**Why:** This is the worst answer in the set. It fabricates a fixed nine-ticker "list" (macro/commodity tickers that have nothing to do with signal breadth) — a flat invention, not grounded in `internal_breadth.py` at all. It queried the wrong table (`macro_theses`, which is the Wolf-thesis table, not `signal_events`) so even its tool use points at the wrong data. It fully agrees to the false premise ("Please provide the two additional tickers... I will update the list") — the exact thing Q05 was built to test, and the exact thing the key says is an instant fail. No rolling-5-day-window concept, no "distinct ticker" concept, nothing.

## Q06 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "The expected move is not exactly the same as the bot's price target. It typically represents the anticipated price range or volatility for the stock over a certain period, based on options market data. It gives an estimate of how much the stock might move, but it doesn't specify a precise direction like a price target does."
**Tools it actually called:** *(none)*
**Why:** The wording happens to land close to the right idea (range, not a direction), but `tools_seen` is empty — it never opened `expected_move.py`, the file the key grounds the answer in. Per the grading rule, an answer that never opened the named grounding file is a FAIL even when the guess sounds reasonable. It also never mentions straddles/ATM pricing specifically, just "options market data" — vaguer than the key's required grounding.

## Q07 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "VVIX is often called the 'fear of fear' index because it measures the expected volatility of the VIX itself... When I say 'fear of fear' is normal right now, it indicates that market participants are unusually anxious about potential market swings, even if actual market prices haven't moved dramatically yet. This heightened concern usually suggests increased nervousness or risk aversion among investors."
**Tools it actually called:** `web_search(VVIX vs VIX)`, `web_search()`
**Why:** It used external web search instead of reading the internal grounding (`consensus_engine/alerts/commands.py:2257`) — never opened the actual file behind the bot's own "normal" reading. Worse, its plain-English gloss of "normal" is backwards: the key says "normal" means hedging costs are in line with what VIX explains — i.e. NO extreme panic — but the answer says it "indicates... unusually anxious... increased nervousness or risk aversion," which is the opposite reading (implies elevated fear when the source data says the opposite).

## Q08 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "The memory search for detailed information... is currently unavailable due to a provider error. Based on the typical system design, the alert score is usually computed through a combination of various signals, such as technical indicators, social signals, news validation, and analyst signals... Would you like me to try again or look into the code files directly?"
**Tools it actually called:** `memory_search(alert score)`
**Why:** Never read `models.py` (`ScoreBreakdown`) or `cross_reference.py`. Lists made-up component categories ("technical indicators, social signals, news validation, analyst signals") that don't match the actual five (base, analysts, news, tech, llm). Never states that quality gates can move the score both up and down — only vaguely says "adjustments... that modify the raw value." Heavy hedge language ("typically," "usually," "I would need to access").

## Q09 — FAIL
**Verdict:** FAIL
**Answer (verbatim):** "The system's alert mechanism for analyst groups... isn't explicitly detailed in the accessible documentation or source code I found... the precise weighting or voting method isn't provided in the segments I reviewed. Usually, systems of this nature increase confidence as more analysts concur, but the exact logic would be in the detailed implementation..."
**Tools it actually called:** `memory_search(...)`, `read(consensus_engine/scanners/options.py)` — the wrong file, not `herding.py`
**Why:** Never opens `herding.py`/`detect_swarm`. No "Group bias" concept, no statement that a single analyst does not trigger the same alert as multiple agreeing analysts — it explicitly says it can't confirm that distinction ("isn't explicitly detailed... exact logic would be in the detailed implementation"). Textbook hedge-instead-of-look failure, and it read the wrong file entirely.

## Scorecard

| Question | Verdict | One-line reason |
|---|---|---|
| Q01 | FAIL | Never opened options.py/config; guessed; no Schwab mention |
| Q02 | FAIL | Turn 1 named wrong source (Discord channel ID); turn 2 produced no real content |
| Q03 | FAIL | Both turns: "I couldn't retrieve," no thesis, no source, turn 2 repeats turn 1 verbatim |
| Q04 | FAIL | No root cause found; pure deflection back to the user |
| Q05 | FAIL | Fabricated ticker list, wrong DB table queried, agreed to add tickers (false-premise fail) |
| Q06 | FAIL | Correct-sounding guess but never opened expected_move.py |
| Q07 | FAIL | Used web search not internal source; "normal" explanation reversed |
| Q08 | FAIL | Never opened models.py/cross_reference.py; vague/wrong components; hedge language |
| Q09 | FAIL | Never opened herding.py (read wrong file); explicitly says it can't confirm the group-vs-single distinction |

**Total: 0 / 9 PASS**

## Failure patterns

1. **Hedged instead of opening the grounding file (Q01, Q06, Q07, Q08, Q09):** the model ran `memory_search`/`web_search` or nothing at all, never read the actual source file named in the answer key, and answered with "likely," "typically," "I couldn't find," "would need to." This is the dominant failure mode — 5 of 9 questions. **Plausibly the steering prompt's fault**: nothing in the transcript shows the bot being pushed to open the specific scanner/analysis file before answering; it defaults to memory search and general knowledge. A prompt line forcing "read the source file before answering a how-does-X-work question" would likely fix this class.

2. **No real content on a turn (Q02 turn 2, Q03 both turns):** acknowledgment-only or "I couldn't retrieve" responses, including an exact repeat of a failed answer on re-ask. This reproduces the historical bug the test set was built to catch — **not obviously a steering-prompt issue**, looks more like a tool/retrieval failure (Gmail excerpt tool never actually invoked) than a prompt-wording issue.

3. **Fabrication under a false premise (Q05):** invented a 9-ticker list wholesale and agreed to "add" to it, plus queried the wrong DB table. **Not a steering-prompt issue** — the model had a tool available (`internal_breadth.py`/`signal_events`) and never used it; this is a model-capability/tool-selection failure, not a wording problem.

4. **Wrong source cited outright (Q02 turn 1, Q09):** confidently named an unrelated real config key (`options_flow_channel_id`) or read the wrong file (`options.py` for a herding question) and asserted from it. **Possibly steering-prompt-adjacent** — if the prompt doesn't tell the model which file maps to which question type, it grabs the nearest plausible-sounding artifact instead.

**On the stale `_STEERING_TEMPLATE` line specifically:** no graded answer references or is misled by the literal "options.py = options flow via yfinance" line — none of the answers claim yfinance is the source; Q01/Q02 instead give unrelated or hedged answers that never engage with the primary-source question correctly at all. So there's no direct evidence this particular stale line caused a wrong answer in this run; the failures trace to hedging/no-file-reading, not to acting on the stale fact.
