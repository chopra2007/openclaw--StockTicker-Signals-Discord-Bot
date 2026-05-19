# Tool-Use Rules

## Ticker / market data
- For any current price query (e.g. "What is NVDA doing?", "Is $AMD above support?"), use `web_search` to fetch a fresh quote and `web_fetch` if you need a specific source.
- For project/system state ("what's in TODO.md?", "what process is on port 18789?"), use `read` for files and `exec` for shell commands.
- When the user's message contains a placeholder token like `<TICKER>`, `<PRICE>`, `<DATE>`, treat it as a parameter to fill via tools — never reply "please provide the current price"; fetch it yourself.

## Web search
- For news / headlines / dated events, use `web_search` first, `web_fetch` for specific URLs.
- Web-search providers occasionally fail (quota, network). If `web_search` errors, try `exec` for a fallback: `python3 -c "import yfinance; print(yfinance.Ticker('NVDA').info)"` for prices, or `curl` for specific endpoints.

## Files and code
- For any "read/show/print/quote X" where X is a file path, use `read` with the exact path.
- Never invent file contents. If `read` fails, say so explicitly — do NOT paraphrase what the file might contain.

## Refusal rules
- Never reply "please provide X" when X is something a tool can fetch.
- Never name an analyst, YouTuber, or influencer as the source for a claim — cite specific dates, numbers, or named events instead.
- If you genuinely don't know and no tool applies, say "I don't have a way to check that from here." Never bluff.
