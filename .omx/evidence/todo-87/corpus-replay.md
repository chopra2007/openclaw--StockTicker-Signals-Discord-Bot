# TODO #87 — all 79 archived briefs replayed through the new card builder

Each archived `rendered_content` was parsed with `_sections_from_text` and rebuilt into the new
embed with `_build_briefing_embed`, then measured against Discord's real limits. This tests
FORMATTING, SIZE and SECTION SURVIVAL — see the limits at the end for what it cannot test.

## A finding this replay produced (before it could produce anything else)

The first attempt returned an empty card for **every one of the 79 briefs** — 395 empty
placeholder fields. Cause: the section parser matched headings by exact title, and the archived
briefs use a dozen spellings ('## 🌙 Overnight', '**Overnight Highlights**', 'Macro Pulse',
'Top Tickers (quick glance)'). That is also a live bug, not just a replay artifact: a brief
stored as `pending` and retried after any heading change would have reposted an EMPTY card.
Fixed by matching on the heading's words with emoji, markdown and punctuation stripped
(`_section_key_for_heading`). Numbers below are from after that fix.

## Results

- briefs replayed: **79**; briefs from which at least one section parsed: **53**
- every rebuilt card has exactly **5 fields** (asserted on all 79) — a section cannot vanish
- embed total: min **254**, median **1201**, max **2690** (Discord limit 6000)
- cards over the 6000 embed limit: **0**
- fields over the 1024 field limit: **0**
- fields trimmed, each ending in a visible `…`: **0** — nothing is cut silently
- genuinely empty sections shown with an explicit placeholder: **133**

**Why 53 and not 79:** the other 26 briefs predate structured rendering entirely and use no
markdown headings at all — their sections are bold lines like `**📈 Overnight**`. They are shown
correctly as empty-with-placeholder rather than being silently mangled, which is the required
behaviour. Nothing going forward can be in that shape: the new writer always emits `### <title>`,
and the parser is only asked to re-read what it wrote.

### Which sections were recoverable from the archive

| section | briefs where it parsed |
|---|---|
| 🌙  Overnight | 50 of 79 |
| 📊  Levels to Watch (SPY) | 53 of 79 |
| 🚀  High-Conviction Calls | 53 of 79 |
| 📈  Macro | 53 of 79 |
| 🔝  Top Tickers | 53 of 79 |

### Largest five rebuilt cards

| session | original text | rebuilt embed total |
|---|---|---|
| 2026-07-23 | 2795 chars | 2690 |
| 2026-07-16 | 2679 chars | 2602 |
| 2026-06-12 | 2560 chars | 2479 |
| 2026-05-12 | 2551 chars | 2409 |
| 2026-06-22 | 2416 chars | 2383 |

## The comparison that matters

- OLD sender: **27 of 79** of these briefs exceeded the `content[:1990]` slice and
  lost their tail — the Macro and Top Tickers sections — with no marker at all.
- NEW builder: **0 of 79** lose a section. All five always render; over-long text is cut
  at a line or sentence boundary and marked with `…`.

## What this replay does NOT prove

- `briefing_runs` archived the RENDERED TEXT only. The alerts, levels and analyst rows that
  produced each brief were never stored with it, so this cannot show the new builder would
  reproduce a given day's FACTS from its original inputs. No such claim is made — section text
  is compared to section text.
- Weekly option chains were never snapshotted, so a multi-date weekly expected-move replay is
  impossible. The weekly chart is verified only against the live chain `!emw` reads.
