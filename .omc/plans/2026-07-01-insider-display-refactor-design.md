# Insider-trade display refactor — Design

**Date:** 2026-07-01
**Commands affected:** `!sec`, `!all`, `!scan`, and the automatic alert cards
**Status:** Design — awaiting user review before implementation plan

---

## Plain-language summary

Right now, when an insider (like a company CEO) sells stock, a single sale
often files as dozens of tiny "fills" at slightly different prices. The bot
shows every one of those rows, with no dates and no dollar value. Example:
Micron's CEO sold 40,000 shares on June 26 — but it showed up as **49
repetitive rows** with no date and no total.

This refactor collapses those rows into **one clean block per insider, per
day, per direction (buy/sell)**, showing who, how many shares, the average
price they got, the total dollar value, the date, and how many fills it took.
The same format is used in every place insiders appear, so it never looks
different from one command to the next.

---

## The locked display format

This code-block form is used by **`!sec` and the Score card**. The `!all` card
uses a cleaner plain-text form instead (see surface 3 below) — same numbers,
different presentation to fit that card's look.

One block per insider per day. Real Micron example:

```
🔴 Sanjay Mehrotra — CEO
─────────────────────────
    Shares   40,000
    Avg      $1,158
    Value    ~$46.3M
    Date     Jun 26 · 49 fills
```

Rules for the block:

- **Direction dot:** 🔴 = sold, 🟢 = bought. (Chosen over a text label so
  direction pops at a glance.)
- **Header:** `<dot> <Name> — <Role>`, with an underline the width of the
  header text + 3 characters.
- **Shares:** total shares in the group (sum of all fills), thousands-separated.
- **Avg:** average price per share = total value ÷ total shares. Whole dollars
  at/above $100 (`$1,158`); two decimals below $100 (`$17.35`) so cheap stocks
  keep precision.
- **Value:** total dollar value, compact — `~$46.3M`, `~$190K`, `~$4,200`.
- **Date:** the actual **transaction date** (when the trade happened), not the
  filing date. Format `Jun 26`. Followed by `· N fills` (singular `1 fill`).
- **Routine transactions** (stock awards, option exercises, tax withholding,
  gifts) are NOT conviction trades — they collapse to one italic line below the
  block: `+6 routine award / option transactions`.
- **No key/legend anywhere.** Everything is spelled out inline.

Sorting: insider blocks ordered by total dollar value, largest first.

### Aggregation rule

Group a filing set's transactions by `(insider name, transaction date,
direction)`. Only **open-market** buys/sales get a full block; routine types
are counted, not listed. For each group compute: total shares, total value,
average price, fill count, and (kept internally) min/max fill price.

---

## Where it applies — all four surfaces, identical format

1. **`!sec <TICKER>`** — converts from plain text to an **embed**.
   - Title: `📄 SEC Filings — $MU · last 72h`.
   - Shows **every** insider block (no "top N" cap). If the content exceeds
     Discord's embed limits, it spills into a second embed rather than
     truncating.
   - Non-Form-4 filings (8-K, 13D, 10-Q…) listed below the insider blocks, as
     today.

2. **The Score card** (`cross_reference` — used by typed `!scan` AND the
   engine's automatic alerts) — the `SEC Filings` field uses the same block
   format. The old "14 rows + plus 35 more insider(s)" collapses to one block
   with the date. Kept within the 1024-char embed-field cap; if more insiders
   than fit, a trailing `+N more insiders` line (blocks, not fills, so this is
   now rare).

3. **`!all` "Full Analysis" card** — gains a **deterministic** `🏛️ Insider
   Activity` field. This card does NOT use the code-block table (it would clash
   with the card's clean narrative look). Instead it uses a plain-text field
   matching the card's other fields (Snapshot, Retail): bold name — role on one
   line, then a labeled detail line:

   ```
   🔴 Sanjay Mehrotra — CEO
   Shares 40,000 · Avg $1,158 · Value ~$46.3M · Jun 26 · 49 fills
   ```

   (Bold on the name and the Shares/Avg/Value numbers.) Placed **directly below
   the Sector Strength field** so its top gap matches the normal field spacing
   (no blank spacer row). Today insider detail only appears if the AI happens
   to mention it — this guarantees it shows, and the write-up's insider mention
   is fed the accurate aggregate (not a single cherry-picked fill).

4. **The AI evidence text** (fed to the `!all` write-up) — same aggregated
   numbers in a plain-text form (no code block), so the write-up is accurate.

---

## Architecture

One shared module so the format is defined once and cannot drift:

**`consensus_engine/alerts/insider_display.py`** (new)

- `aggregate_insiders(fetched) -> (list[InsiderSummary], routine_count)`
  Pure. Groups open-market fills; returns summaries sorted by value desc.
- `render_cards(summaries, routine_count) -> str`
  The code-block labeled-stack string — used by `!sec` and the Score card
  (surfaces 1–2 only).
- `render_all_field(summaries, routine_count) -> str`
  The clean plain-text form for the `!all` card (surface 3): bold name — role,
  then a labeled `Shares · Avg · Value · Date · fills` line. NO code block.
- `render_evidence(summaries, routine_count, notable) -> list[str]`
  Plain-text lines for the LLM (surface 4). Preserves the existing NOTABLE
  flag (aggregate open-market value clears the configured buy/sell floor).
- Helpers: `_abbrev_title`, `_compact_dollar`, `_fmt_avg`, `_fmt_date`.

`InsiderSummary`: name, role, direction, shares, avg_price, value, date,
n_fills, price_lo, price_hi.

**Rewired call sites:**

- `cross_reference.py::_render_named_insider_block` → call `aggregate_insiders`
  + `render_cards` (with the field cap).
- `commands.py::_sec_and_reply` → rewrite to build an embed via `render_cards`,
  send with `send_command_embed_reply`; spill to a second embed if needed.
- `aggregator.py::_format_insider_section` / `_format_sec_evidence_block` →
  use `aggregate_insiders` + `render_evidence`.
- `all_command/embed.py::build_embed` → accept insider block text and render the
  new `🏛️ Insider Activity` field; `aggregator.handle_all` passes it through.

**Title abbreviation** (`_abbrev_title`): conservative map for common SEC
titles — `President and CEO`→`CEO`, `Chief Financial Officer`→`CFO`,
`Chief Legal & Corp Affairs Ofc`→`Chief Legal`, `VP, Chief Accounting Officer`
→`CAO`, `Director`, `General Counsel`, `10% Owner`, etc. Unknown titles: use
the raw title trimmed to ~16 chars (never guess).

---

## Edge cases

- **No open-market trades:** keep existing message — "Recent Form 4 filings
  were routine awards / option exercises — no open-market conviction trades."
- **Fetch timeout / partial:** preserve existing partial-data messaging.
- **Buys and sells, same insider, same day:** two blocks (one 🔴, one 🟢).
- **Single fill:** `Date  Jun 26 · 1 fill` (no range needed).
- **Many insiders:** `!sec` spills to a 2nd embed; Score-card field shows
  `+N more insiders` if over the 1024-char cap.
- **Low-priced stock:** avg shows cents (`$17.35`).

---

## Testing

New `tests/test_insider_display.py`:

- Aggregation: MU 49 fills → 1 block (40,000 sh, $46.3M, avg $1,158, 49 fills);
  AVGO → 2 blocks + 6 routine; buys+sells same insider → 2 blocks; single fill;
  all-routine → routine message.
- Formatting: compact-dollar boundaries; avg cents boundary at $100; date
  format; `1 fill` vs `N fills`; title abbreviation fallbacks.

Update existing tests to the new format:
- `tests/test_all_command_sec_insider.py`
- `tests/test_cross_reference.py`

Regression gate: no currently-passing test may start failing.

---

## Out of scope

- SEC fetch limits/logic, scoring, alert thresholds — unchanged.
- No new alert triggers; this is display-only.
- The wider-embed variants (explored and rejected) — not pursued.
