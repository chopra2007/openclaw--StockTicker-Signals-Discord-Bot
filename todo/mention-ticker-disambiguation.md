# Teach the @-mention/!ask answers that bare tickers mean stocks (WEN ≠ haircare)

**Status:** OPEN
**Created:** 2026-06-10

## What happened
User asked the bot about WEN in #chat (2026-06-10 ~13:19 PT). The bot answered about
**WEN haircare products** instead of **Wendy's (NASDAQ: WEN)**. User correction in #chat:
"WEN is Wendy's stock. you gave me information on WEN haircare instead."

## Why (suspected — verify before fixing)
The @-mention/!ask path is the agentic lane: `_handle_mention` in
`consensus_engine/scanners/discord_tweetshift.py` → `openclaw agent --local` → web search
via the SearXNG plugin (localhost:8888). A bare "WEN" web search ranks the haircare brand
above the stock; nothing in the agent's instructions anchors a ticker-shaped token to its
stock meaning. The `!all` lane is NOT affected (it validates tickers and pulls market data
directly) — this is only the conversational answer path.

## Possible next steps (priority-ordered)
1. **Anchor the search context.** In the mention-prompt assembly (where the user's message
   is wrapped before handing to the agent), detect ticker-shaped tokens (1-5 uppercase
   letters, or $-prefixed) and tell the agent: "this is a stock-bot channel — treat
   ticker-like tokens as stock symbols; resolve <TOKEN> to its company via the ticker
   validation path / Finnhub before web-searching, and search '<TOKEN> stock <company>'."
2. Cheap deterministic assist: pre-resolve the token via the existing ticker validation /
   Finnhub `/quote` + company-name lookup, and inject "WEN = The Wendy's Company" into the
   prompt context so the agent can't wander to haircare.
3. A/B with the real failure: ask the restored bot "tell me about WEN" and verify the
   answer is Wendy's (and that a genuinely non-ticker word like "WEN router config" still
   answers normally — don't over-trigger).

## Files / code involved
- `consensus_engine/scanners/discord_tweetshift.py` — `_handle_mention` (prompt assembly)
- openclaw agent config (`/home/openclaw/.openclaw/openclaw.json`, agents.defaults) — if
  the fix belongs in the agent's standing instructions instead
- Ticker validation: `is_valid_ticker` / Finnhub company lookup (grep for the !all path's
  validator to reuse)

## Open questions
- Should EVERY mention-lane answer pre-resolve ticker-shaped tokens, or only when the
  message is short/ambiguous? (Over-triggering on common words like ALL/IT/ON is the risk —
  the indicator-name exclusion list in tweet_parser may help.)
