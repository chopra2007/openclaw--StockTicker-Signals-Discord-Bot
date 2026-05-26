# Discord narrative `fallback_data_only` shipped to users in production

**Status:** DONE 2026-05-22.
**Created:** 2026-05-22

**Layperson:** When the LLM chain is exhausted (see openrouter-chain-reliability.md), the bot renders a "Narrative auto-redacted; structured signal below." embed with just the trade plan — no thesis, no catalysts, no risk section. Users see this from Discord. Recently observed:

- 2026-05-19 09:21 NVDA `iter10-nvda-bot.txt` — fallback only
- 2026-05-18 15:19 NVDA — fallback (production log)
- 2026-05-16 00:12-00:25 NVDA + TSLA + AMD all fallback (production log)
- 2026-05-19 12:13 (this session) — repeated stub tests showed the chain exhausted before completing

**What the user sees:**
```
$NVDA — Full Analysis
🟢 BULLISH
_(Narrative auto-redacted; structured signal below.)_
**Direction:** BULLISH · **Confidence:** LOW · **Score:** 46
... (structured fields only)
```

**Why this is worse than failure:** the user doesn't know if it's a transient LLM hiccup or a permanent quality regression. The trade plan still renders so it looks ~OK but they're missing all the substance.

## Fix options

1. **Add Groq as a more-reliable fallback** (covered by openrouter-chain-reliability.md).
2. **Detect `fallback_data_only` status and explicitly tell the user** ("LLM provider temporarily unavailable — structured signal only this time, try again in a minute"). Better than the current ambiguous "redacted" wording.
3. **Background-retry on fallback**: if first call exhausts the chain, queue a 30s-delayed retry that posts a follow-up edit when it succeeds.

**Where the fallback is rendered:** `consensus_engine/alerts/all_command/output_filter.py` `render_data_only_fallback`. Trigger: `narrator.synthesize_narrative` returns `("", "fallback_data_only")` when `call_with_fallback` exhausts the chain.

**Severity:** high. This is the user-visible quality regression that defeats most of the catalyst-mining + horizon-coherence + anti-influencer work the session shipped. Without the chain reliability fix, those features can't reach the user.
