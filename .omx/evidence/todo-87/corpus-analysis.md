# TODO #87 — what the 79 archived briefs actually show

**Corpus:** 79 archived `briefing_runs` rows that carry rendered text.

## 1. The truncation is real, and it is common

- Brief length: min **480**, median **1874**, max **2795** characters.
- `_send_discord_briefing` posts `content[:1990]`.
- **27 of 79 briefs (34%) are longer than 1990 characters**, so their
  tail is cut off with no marker. Because the sections are ordered Overnight -> Levels ->
  High-Conviction -> Macro -> Top Tickers, the sections that disappear are the LAST ones:
  Macro and Top Tickers.

## 2. The AI's headings drift day to day

Counting heading variants across the corpus (this is why the sections need to be parsed and
validated rather than trusted as free-form markdown):

| heading seen | briefs |
|---|---|
| levels to watch | 66 |
| macro | 62 |
| overnight | 62 |
| top tickers | 50 |
| high-conviction analyst calls | 14 |
| high-conviction calls | 11 |
| top tickers to watch | 5 |
| overnight highlights | 4 |
| top tickers (quick glance) | 4 |
| levels | 3 |
| macro pulse | 3 |
| macro snapshot | 3 |
| overnight alerts | 2 |
| levels to watch (spy) | 2 |
| top tickers (quick take) | 2 |
| top tickers snapshot | 2 |

36 distinct heading spellings for five sections.

## 3. Section presence across the corpus

| section | briefs containing it | missing |
|---|---|---|
| Overnight | 79 of 79 | 0 |
| Levels to Watch | 79 of 79 | 0 |
| High-Conviction Calls | 25 of 79 | 54 |
| Macro | 79 of 79 | 0 |
| Top Tickers | 79 of 79 | 0 |

A missing section today is indistinguishable from a section that was cut off, which is
exactly the failure the new card has to remove: an empty section must say so explicitly.

## 4. Honest limits of this corpus

- `briefing_runs` stored the RENDERED TEXT only. The source rows that produced each brief
  (that day's alerts, levels, analyst calls) were not archived with it. So this corpus can
  verify FORMATTING, SIZE and SECTION SURVIVAL, but it cannot support a claim that the new
  builder would have reproduced a given day's facts from its original inputs. No such claim
  is made here.
- Weekly option chains were never snapshotted either, so a multi-date weekly expected-move
  replay is impossible. The weekly chart is verified against the same live chain `!emw` uses.
