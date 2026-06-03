# Show Wolf trade ideas (entry → target + stop) instead of raw levels

**Status:** DONE
**Created:** 2026-06-03

Marked complete — re-open if the behavior or limitations below need changing.

## Goal

On #news Wolf alerts, when Wolf actually lays out a trade, show a concise
**Trade idea** instead of a confusing list of same-role levels. When he only
gives levels, relabel them sensibly (a broken support → resistance, the downside
level → target). Origin: a BTC alert showed `70000 (support), 74192 (support)`
— two "supports" that were really a broken pivot (resistance) and a downside
target.

## What it does (the agreed spec)

- **Trade idea present** (Wolf framed a trade) → one field, two lines, no separate
  levels line:
  ```
  Trade idea
  short a re-test of $74,192 → $70k
  SL above $74,200
  ```
- **Levels only** (no trade framed) → relabeled, shown high→low:
  ```
  Key levels
  74,192 (resistance) · 70,000 (target)
  ```
- Number style: entry/stop exact with commas (`$74,192`), target abbreviated
  (`$70k`); levels comma-grouped, ` · ` separator.
- Stop = just beyond the entry on the risk side (above for short, below for long),
  rounded out to a clean step (`74,192 → 74,200`).
- **Only fires when Wolf actually frames a trade** — never inferred from a passing
  mention (same discipline as the GOOG over-call fix, item #20 work).

## What works

- **Cross-email assembly** (verified end-to-end with a 2-email simulation through
  `wolf_theses.ingest` + render): the framed setup is saved on the thesis and
  persists; a later email that adds no setup does NOT erase it (`_KEEP` sentinel);
  levels accumulate; at display time a missing entry/target is filled from the
  accumulated levels by direction (short: entry = highest level, target = lowest).
  Example proven: email A "short → 130" + email B adds the 162 level →
  `short a re-test of $162 → $130, SL above $163`.
- Applies to BOTH embed builders (`build_embed` and the live `format_confluence_alert`)
  via a shared helper, so confluence alerts and phase-1 alerts both get it.
- 17 unit tests in `tests/test_wolf_trade_idea.py`; full suite green (1707 passed).

## Limitations (know these before changing anything)

1. **At least one email must frame a trade** — an action word (short/long) PLUS at
   least one price IN THAT SAME EMAIL. A bare "I'd short this" with no number is
   dropped (`_coerce_thesis` requires entry or target). If Wolf only ever lists
   levels, you get relabeled "Key levels," not a trade idea — by design.
2. **Level-fallback picks the extreme** (highest/lowest) when filling a missing
   entry/target. Clean for a 2–3 level thesis; if many levels pile up over weeks,
   the extreme may not be the exact one Wolf meant.
3. **Action must agree with direction** (bear→short, bull→long) or the setup is
   dropped (anti-contradiction).
4. **Only future theses** capture setups automatically. Theses created before the
   deploy won't get one retroactively unless a new Wolf email frames a trade on
   that still-active thesis.
5. **Extraction is LLM-based** (Wolf email parser, `gpt-oss-120b` lead chain) — it
   can miss a setup Wolf stated, or rarely mis-capture. Not deterministic.
6. **Relabel only touches ambiguous 'support' roles** by position; explicit
   resistance/target roles Wolf gave are kept. Single-level theses are unchanged.

## Files / code involved

- `consensus_engine/analysis/wolf_email_parser.py` — `_EXTRACTION_USER_TMPL` adds a
  `setup` field; `_coerce_thesis` validates it (`setup` = `{action, entry, target}`).
- `consensus_engine/db.py` — new `macro_theses.trade_setup_json` column (migration);
  `insert_thesis` / `update_thesis` thread it; `_KEEP` sentinel = leave untouched.
- `consensus_engine/analysis/wolf_theses.py` — `_collapse_theses` carries `setup`;
  `ingest` persists it (latest-framed wins, `_KEEP` preserves on no-setup emails).
- `consensus_engine/alerts/wolf_news.py` — helpers `_money`, `_money_k`,
  `_stop_from_entry`, `_setup_from_row`, `_trade_idea_value`, `_relabel_levels`,
  `_levels_field` (the chooser used by both embed builders).
- `tests/test_wolf_trade_idea.py` — 17 tests.
- Commit: `297aa09` (pushed to master 2026-06-03).

## Manual data note

The existing BTC thesis (`macro_theses` id 64) was set by hand (user-authorized)
to `{"action":"short","entry":74192,"target":70000}` so it displays the trade
idea now; it predated the feature so wasn't auto-captured.

## Possible next steps (if re-opened)

- Smarter entry/target selection when many levels accumulate (nearest level to
  current price, not just the extreme) — would need a price lookup (note: crypto
  like BTC isn't on the finnhub free quote endpoint; yfinance `BTC-USD` works).
- Optionally capture/show a stop Wolf states explicitly, instead of always deriving.
- Backfill setups for older active theses by re-reading their source emails.
