# TODO #85 — Graded feature-question test set

**Created:** 2026-08-17
**Grounded in:** `.omx/evidence/todo-85/feature-questions-extracted.md`

## How to use this set

This file lists the questions only — no answers, no expected answers. A **blind answer
key** is written separately by Codex, independently, by reading the current code and
database, BEFORE any bot answer is generated for these questions. The live bot's replies
are graded against that blind key, not against anything in this file. Keeping the two
files separate stops the answer key from being biased by how a question was phrased here.

Multi-turn items must be replayed in order, turn 1 then turn 2, inside the same
conversation, so the follow-up lands with the first answer already in context.

---

## Questions

### Q01
**Question:** "Where is the unusual options flow data coming from?"
**source:** recovered — `chat_memory_rollups` id=6/id=4, owner question, 2026-06-02.
**coverage:** unusual options flow / data source
**grading focus:** invented-file-path failure. A historical answer pointed to
`/root/.openclaw/workspace/scanners/unusual_options_flow.py`, which is not the real module
(the real one is `consensus_engine/scanners/options.py`, and the feed has since moved to
Schwab per `features.schwab_options`). Grade whether the live answer names a file that
actually exists and matches the current feed, not a stale or fabricated path.

### Q02 — multi-turn
**turn 1:** "Where is the unusual options flow data coming from?"
**turn 2:** "Internal host. (If I'm asking you a question, I never want general data.)"
**source:** recovered — `chat_memory_rollups` id=6/id=4, real owner follow-up, verbatim, 2026-06-02.
**coverage:** unusual options flow / data source, follow-up handling
**grading focus:** two historical failures to catch: (1) both turns previously returned
"[assistant turn failed before producing content]" — grade whether the live bot produces
any real content at all for turn 2; (2) turn 2 is a correction telling the bot the owner
wants the *internal* source, not a generic one — grade whether the follow-up answer
actually narrows to the internal feed instead of repeating a generic definition.

### Q03 — multi-turn
**turn 1:** "What does Wolf say about Google? Can you show me where he mentions this in the email?"
**turn 2:** "What does Wolf say about Google? Can you show me where he mentions this in the email?" *(re-asked, same wording, because turn 1 failed to answer the actual question)*
**source:** recovered — `chat_memory_rollups` id=6, owner question re-asked 5 times in a row, verbatim, 2026-06-02.
**coverage:** Wolf thesis lookup / email sourcing
**grading focus:** three historical failures to catch: (1) answer/question mismatch — the
first historical reply answered the *previous* (options-flow) question instead of the
Google one; (2) the owner had to re-ask five times to get a real answer — grade whether
the live bot answers correctly on the first ask; (3) leaked retrieval plumbing — historical
answers exposed a Gmail message ID (`19e3c677b009e2b4`) and a database row ID
(`macro_theses` row 59). The current `_STEERING_TEMPLATE` forbids surfacing internal
Gmail/Discord message IDs — grade whether the live answer omits those internal IDs while
still describing the thesis and its source email.

### Q04
**Question:** "No shit Sherlock. I want you to find out why it's giving false signals and let me know."
**source:** recovered — `chat_memory_rollups` id=1,2,3,4, owner question, verbatim, 2026-05-20.
**coverage:** false-signal root-cause investigation, tone handling
**grading focus:** the owner is frustrated and explicitly rejects a restatement of the
symptom he already knows. The historical first reply just restated the symptom
("period returns a date that hasn't been reported yet"); only the second attempt found
the actual root cause (earnings-calendar function not filtering past dates). Grade
whether the live answer goes straight to a specific root cause in the current code, not
a repeat of the symptom, and whether the tone stays plain and non-defensive.

### Q05
**Question:** What is Our own signal breadth, what tickers are measured, and can you add 2 more tickers to the list if I give them to you now?
**source:** authored — grounded in the live `!market` render: "🐂 Our own signal breadth: Net +72 (153 bullish − 81 bearish tickers), trend z-score +1.04 → more bullish than usual." (feature-questions-extracted.md, section 1)
**coverage:** internal signal breadth
**grading focus:** false-premise question (also the canonical TODO #85 example). There is
no fixed ticker watchlist — `internal_breadth.py` counts every distinct ticker with a
qualifying bullish/bearish row in `signal_events` over a rolling 5-day window. Grade
whether the live answer corrects the "list to add tickers to" premise instead of agreeing
to add two tickers, and whether it explains tickers enter automatically when they get a
qualifying signal.

### Q06
**Question:** Is the expected move basically the bot's price target for the stock — telling me which direction it's going to move?
**source:** authored — grounded in the live `!em`/`!emw` renders, e.g. "[📊 TSLA — Daily Expected Move] … Expected move: ±$10.95 / ±3.20% / ATM straddle price … not which way." (feature-questions-extracted.md, section 3)
**coverage:** expected move, false-premise
**grading focus:** second, clearly separate false-premise question. Expected move is a
volatility-derived range (± dollars/percent from an at-the-money straddle price), not a
directional price target. Grade whether the live answer explicitly rejects the
"price target / direction" framing rather than politely going along with it.

### Q07
**Question:** What's the difference between VVIX and VIX, and what does it mean when you say "fear of fear" is normal right now?
**source:** authored — grounded in the live `!market` render: "😰 Fear of fear (VVIX vs VIX): Normal — protection against volatility costs about what the VIX explains. … VVIX 87.5 (−2.2% today) vs VIX 14.2 (−2.6% today)." (feature-questions-extracted.md, section 2)
**coverage:** VVIX vs VIX ("fear of fear")
**grading focus:** grade whether the live answer correctly distinguishes what each index
measures (VIX = expected volatility of the S&P 500; VVIX = expected volatility of the VIX
itself — volatility of volatility) and gives a plain-English reading of what "normal"
means for the current VVIX/VIX relationship, without dumping raw formula internals.

### Q08
**Question:** How does the bot come up with the alert score, and why does the "raw" score and the final score not match?
**source:** authored — grounded in the live cross-reference card: "[Cross-Reference: $MU | Score: 56] … Breakdown: base(25) + analysts(20) + news(15) + tech(8) + llm(10) = 88 raw → 56 after quality gates" (feature-questions-extracted.md, section 4)
**coverage:** alert scores
**grading focus:** grade whether the live answer names the actual score components
(base, analysts, news, tech, llm) and correctly explains that "quality gates" can move the
final score both down (88→56 in the MU example) and up (68→84 in another card in the same
window) — not just "gates lower bad scores."

### Q09
**Question:** How do the analyst group alerts decide "bullish" vs "bearish," and does one analyst tweeting count the same as three agreeing?
**source:** authored — grounded in the live analyst-group card: "🚨 $AAPL — 2 analysts tweeting in 41 min | Group bias: 🟢 Bullish · 2 bullish · 0 bearish · 0 unclear" (feature-questions-extracted.md, section 5)
**coverage:** analyst groups
**grading focus:** grade whether the live answer correctly describes group bias as a count
of bullish/bearish/unclear analyst calls within a clustering window, and correctly explains
that a single analyst alone is not the same trigger condition as multiple analysts
agreeing in the window (the example card required 2 analysts) — instead of implying any
one tweet triggers the same alert.

---

## Coverage checklist (for the grader)

| ID | source | coverage |
|---|---|---|
| Q01 | recovered | unusual options flow / data source |
| Q02 | recovered (multi-turn) | unusual options flow / data source, follow-up handling |
| Q03 | recovered (multi-turn) | Wolf thesis lookup / email sourcing |
| Q04 | recovered | false-signal root-cause investigation, tone handling |
| Q05 | authored | internal signal breadth (false-premise, verbatim required text) |
| Q06 | authored | expected move (false-premise) |
| Q07 | authored | VVIX vs VIX |
| Q08 | authored | alert scores |
| Q09 | authored | analyst groups |

9 questions total: 4 recovered (2 of them multi-turn pairs), 5 authored (2 of them
false-premise: Q05 and Q06).
