# Show insider trades with dates and dollar values

**Status:** DONE 2026-07-01
**Created:** 2026-07-01

## Goal

Refactor how insider (Form 4) trades are shown so the user can see WHEN the
selling happened and HOW MUCH it was worth — everywhere insiders appear, in one
consistent look. Driven by a real case: Micron's CEO sold 40,000 shares on one
day, but the bot showed it as 49 repetitive rows with no date and no total.

## What shipped (commit 0151a22)

One shared module — `consensus_engine/alerts/insider_display.py` — so the format
is defined once and can't drift between commands:
- `aggregate_insiders(txs)` collapses the many tiny "fills" of one open-market
  sale into ONE block per (insider, transaction date, direction): name, role,
  total shares, average price, total value, date, fill count. Routine
  awards/option-exercises/tax-withholding are counted, not listed.
- `render_cards` → **!sec** (now an embed, was plain text) and the **Score card /
  auto alerts** (`cross_reference._format_named_insiders`). Code-block card,
  🔴 sold / 🟢 bought. Shows every insider (no top-N cap); spills to a 2nd embed.
- `render_all_field` → the **!all** card's new 🏛️ Insider Activity field (clean
  bold, no code block), placed directly below Sector Strength.
- `render_evidence` → the LLM evidence text fed to the !all write-up (so the
  write-up quotes the accurate aggregate, not a single cherry-picked fill).

## Verification

- 424 tests pass across every affected suite (new tests/test_insider_display.py,
  !all command suite, cross_reference, command dispatch, e2e). No regressions.
- Live SEC pull through the real code: AVGO Chief Legal officer sold 25,000 sh /
  ~$9.7M / Jun 25 rendered correctly on all surfaces; NVDA's 9 routine award
  filings correctly collapsed to nothing.
- Removed 3 helpers my change orphaned (_fmt_security, _fmt_insider_shares/_price).

## Notes / live-facing

- Auto-alert flag `sec_watcher.named_insiders_in_alert` is ON, so the next real
  alert's Score card uses the new card format. Format change only — nothing about
  WHEN alerts fire changed.
- Design doc: `.omc/plans/2026-07-01-insider-display-refactor-design.md`.
- To change how insiders look anywhere, edit `insider_display.py` only.

## Possible follow-ups (not requested)

- Show the low–high fill price range (kept internally as price_lo/price_hi) if the
  user ever wants it back — currently omitted per the "state it once" decision.
