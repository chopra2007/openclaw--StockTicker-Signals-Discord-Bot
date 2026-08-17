# TODO #87 — live Discord test and comparison to the 2026-07-30 reference

**Run:** 2026-08-17, posted to the live `#chat` channel and read back off the Discord API.
Test messages: `1539043951812542464` (v1) and `1539044550272614492` (v2, final).

## What actually landed in Discord

Read back from `GET /channels/{id}/messages/{id}` — not from local render output:

- **2 embeds in ONE message.** Main card + a second embed carrying the weekly chart.
- **2 PNG attachments**, both accepted and served from Discord's CDN
  (`SPY_em_daily.png` 109,152 bytes, `SPY_em_weekly.png` 87,211 bytes). Both embeds came back
  with a populated `image.proxy_url`, which is Discord confirming it processed and is serving
  the image — not just that we uploaded bytes.
- **All five fields present**, in the reference order, each inside Discord's 1024-char field limit,
  whole card at 3,564 of the 6,000-char embed budget.
- Date line `_Monday, August 17 2026 · 3:53 PM PDT_` — computed in code from
  `ZoneInfo("America/Los_Angeles")`. No "ET"/"Eastern" anywhere.

## Side by side with the owner's 2026-07-30 reference

| | July 30 reference | New card |
|---|---|---|
| Section order | Overnight, Levels to Watch, High-Conviction Calls, Macro, Top Tickers | identical |
| Headings | emoji anchors (🌙 📊 🚀 📈 🔝) | same emoji, now as embed field names |
| Style | compact prose grouping tickers into a sentence | same — see below |
| Format | plain text in a code fence | real Discord embed |
| Charts | none | SPY daily + weekly expected-move charts |
| Truncation risk | cut at 1,990 chars with no marker | fields sized to Discord's limits; any trim ends in a visible `…` |

Reference Overnight:
> MSFT (multiple reports, up to 91/100) beat; focus on cloud & AI strength. AAPL, AMZN, META, ORCL, CROX, SFM, HOOD, SMCI also reported.

New card Overnight (real output):
> SNDK (82/100) and APO (55/100) show strength; GE (25/100), VIST (58/100), and DIS (52/100) under pressure. NVDA (39/100) and PAGP (20/100) lag amid broader weakness.

Same shape: grouped tickers, scores retained, one scannable sentence.

### This took two attempts, and the first one was worse than the reference
The v1 test card rendered Overnight as a raw bullet dump — one line per alert, including empty
entries like `- SNDK (82/100) — ` with a dangling dash, because the prompt fed the model bare input
lines and asked only for "markdown". That was **less** scannable than the July 30 reference, so the
requirement ("at least as quick to scan") was not met. Two fixes, both from looking at the real card:
1. the prompt now asks for compact prose and shows the reference sentence as the example;
2. alert lines with no catalyst no longer carry a trailing dash into the prompt.
v2 above is the result. Recording this because the first render passed every unit test and still
failed the actual goal.

## The open question, decided from the real render

**Two separate chart embeds, not one combined image.** A Discord embed holds a single image, and the
test proves two embeds in one message render cleanly, each with its own caption line
(`±$2.87 (0.37%)` daily, `±$7.50 (0.97%)` weekly) sitting directly above its chart. A combined image
would have forced both horizons into one set of axes with two different price bands and one shared
caption, which is harder to read on a phone, not easier.

## Failure paths exercised for real (not only in tests)

- **AI unavailable:** the OpenRouter key hit its daily cap mid-session, so three of the four chain
  models returned HTTP 403 on every call during this work. The brief still rendered — proving the
  chain fallback and, when forced, the deterministic path.
- **Deterministic fallback forced** by making `_llm_synthesize` raise: produced all five sections
  from the database alone, 3,950 chars, embed total 3,564, no "ET"/"Eastern", both charts still
  attached. An AI outage yields a complete card, not a broken one.
- The fallback was capped to the same 15/10/10/5 item limits the AI prompt uses — before that it
  emitted every one of 72 alerts (~8k chars) and every section after the first came out as a
  trimmed stub.
