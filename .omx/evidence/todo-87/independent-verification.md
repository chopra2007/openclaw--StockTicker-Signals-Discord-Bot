# TODO #87 — independent adversarial verification

Read-only on source. All numbers below were re-run by me from
`consensus_engine/briefing/alfred.py` and the raw JSON, not copied from the evidence files.

## A. Section completeness — PASS

Ran `_render_briefing` with `_llm_synthesize` monkeypatched (and the level filter stubbed) for all
five paths, then fed each result through `_sections_from_text` -> `_build_briefing_embed`:

| path | fields | any field >1024 | embed total |
|---|---|---|---|
| good AI JSON | 5 | none | 191 |
| malformed JSON (`not json at all {{{`) | 5 | none | 254 |
| AI raises `RuntimeError` | 5 | none | 254 |
| AI returns `"9:30 ET"` | 5 | none | 254 |
| completely empty input data | 5 | none | 254 |

Five fields on every path. Empty ones render the explicit placeholder, so "nothing happened" stays
distinguishable from "the brief broke".

## B. No silent truncation — PASS, with one over-limit escape (see D-1)

- `content[:1990]` is gone from `alfred.py`. `grep -rn "content\[:" consensus_engine/` leaves hits
  only in `health.py:463` and `wolf_news.py:668` — different modules, out of scope here.
- `_trim_to_limit` fuzzed at limits 10 / 60 / 1024 against unbroken text, word text and line text:
  every result is `<= limit` and every result ends in `…`. No input produced a marker-less cut.
- 5,000-char section -> field trimmed to 1024 with `…`. All five sections at 5,000 chars ->
  embed total 5,237, no field over 1024, no unmarked cut.

## C. Deterministic clock — PASS on the AI path, **FAIL on the fallback path**

`_clock_line()` (alfred.py:171-173) reads `datetime.now(tz=_PT)` only; the AI never supplies a time.
The `$ET` ticker is correctly preserved — `_has_forbidden_timezone_label("$ET rallied today.")`
returns False, while `9:30 ET`, `Eastern Time`, `EST close`, `EDT` all return True, and `et al.`,
`GET set`, `BUCKET` correctly return False.

**But the guard only ever runs on the AI's reply.** `_render_briefing:388` checks
`_has_forbidden_timezone_label(raw)`; nothing checks `_fallback_sections`, which copies
`alerts[].catalyst`, `macro.summary` and analyst text straight out of the database. Reproduced:

    alerts=[{"ticker":"AAPL","confidence_score":90,
             "catalyst":"Fed presser at 2:00 PM ET drove the move"}]
    -> card line: "• **AAPL** (90/100) — Fed presser at 2:00 PM ET drove the move"
    -> _has_forbidden_timezone_label(output) == True

So the exact failure the guard exists to prevent reaches the card whenever the AI is down and a
stored catalyst/summary/analyst string contains "ET" or "Eastern" — and those strings are themselves
LLM-written or scraped from YouTube, which is precisely where "9:30 ET" comes from. The live-test
file's "No 'ET'/'Eastern' anywhere" is true of that one run, not of the code.

## D. Chart reuse — PASS

`grep -n "straddle\|sqrt\|0.798\|primary_em\|\*\*0.5"` over alfred.py returns only field reads on the
`compute_em` result (lines 428, 431, 439, 440). No second expected-move calculation exists; the card
calls `expected_move.compute_em` / `render_chart` and nothing else.

Weekly is strictly best-effort: `_spy_expected_move` (408-424) swallows exceptions from both
`compute_em` and `render_chart` and returns `(None, None)`; `_build_briefing_payload` then records
`meta["weekly"] = {"error": "unavailable"}` and simply appends no second embed. I forced the weekly
path to raise and the post still built the main card plus the daily chart. Daily is
required-when-available in the same shape — a daily failure degrades to numbers-only, it does not
block. One caveat: the `try` covers `compute_em`/`render_chart` but **not** `_em_meta` or
`_em_summary_line`, which call `round(result.spot, 4)` unguarded — a result object with a `None`
spot would raise out of `_build_briefing_payload` and abort the whole post. I did not find a way to
make `compute_em` return that, so I am recording it as a latent sharp edge, not a confirmed bug.

## F. The corpus-replay claim — PASS, every number reproduces

Re-ran the replay myself over all 79 rows of `briefing_runs.json`:

| claim in corpus-replay.md | my re-run |
|---|---|
| 79 briefs, 53 parse at least one section | 79, **53** |
| every card has exactly 5 fields | field-counts seen: **{5}** |
| cards over the 6000 limit: 0 | **0** |
| fields over the 1024 limit: 0 | **0** |
| fields trimmed with `…`: 0 | **0** |
| explicit empty placeholders: 133 | **133** |
| embed totals min/median/max 254 / 1201 / 2690 | **254 / 1201 / 2690** |
| 27 of 79 exceed 1990 chars (old silent cut) | **27** |
| brief lengths 480 / 1874 / 2795 (corpus-analysis.md) | **480 / 1874 / 2795** |

Per-section recovery also matches: overnight 50/79, levels/calls/macro/top_tickers 53/79 each.

## G. The heading-drift fix — PASS on real data, **over-matches on constructed input**

86 distinct markdown headings exist across the corpus. `_section_key_for_heading` maps all the real
section spellings correctly, including the unicode-hyphen variant `High‑Conviction Analyst Calls`
(x17) that a plain ASCII match would have missed, `📊 Levels to Watch`, `🌙 Overnight`, `MACRO`,
`**🔝 Top Tickers**` and `Top Tickers (quick glance)`.

Ways I broke it:

- **False positives.** Matching is `text.startswith(alias)` with no word boundary, so
  `"Overnighter Corp news"` -> `overnight`, `"Macrohard Inc"` -> `macro`, and
  `"Levels the market ignored"` -> `levels`. A heading that should not map, does.
- **False negatives.** `"Key Levels"`, `"Watch List"`, `"Calls"`, `"🚀 Trade Ideas"` map to nothing.
  The archive's own unmapped headings are `📊 Quick Take`, `📺 YT Signals Watch`, `🔥 Top Story`,
  `📈 Most Important Story` and four `Morning Briefing – Pre-Market` title variants.

Severity is low **only because** the writer now emits the five fixed `### <title>` headings and the
parser is asked to re-read what it wrote. It is not a general-purpose heading matcher, and the
comment at line 269 ("matched on the words alone") overstates what it does — it matches on a prefix.

## J. Adversarial inputs I constructed

| input | result |
|---|---|
| AI returns valid JSON with five empty strings | 5 placeholder fields, total 254 — correct |
| section containing only an image link | rendered verbatim, no crash |
| 10,000 characters of one unbroken word | trimmed to 1024 ending in `…` — the `sp >= floor` guard falls through to the hard cut, still marked |
| brief with no headings at all | all five placeholders — see D-2 below |
| 20,000-char `top_story` + 5,000-char `⚠️` footnote | **embed total 6,543 — over Discord's limit** |

## Discrepancies

### D-1 (HIGH) — forbidden "ET"/"Eastern" reaches the card on the deterministic fallback path
`consensus_engine/briefing/alfred.py:388` (guard) vs `:176-210` (`_fallback_sections`, unguarded).
The timezone check is applied to the AI's reply only. Every string `_fallback_sections` copies out of
the database — `catalyst`, `macro.summary`, analyst content — is unchecked, and I reproduced a card
reading "Fed presser at 2:00 PM ET". This violates the project's hard PDT-only rule on exactly the
path (AI outage) the fallback exists to serve.

### D-2 (MEDIUM) — `_fit_embed` can return an embed that is still over 6,000 chars
`consensus_engine/briefing/alfred.py:478-485`. The `break` at line 483 gives up once every field is
at the 60-char floor, so a large description plus a large footer exits the loop over budget.
Measured: **6,543 chars**. Reachable from AI output alone, because `_parse_sections:238-239` applies
**no length cap to `top_story`** (I fed it 50,000 chars and it was accepted, versus
`_MAX_SECTION_CHARS = 3000` for the five sections), and the `⚠️` footnote is lifted out of the AI's
`top_tickers` text by `_sections_from_text:309` and capped only at 2048. Discord answers 400, the run
stays `pending`, and the retry rebuilds byte-identical content — a permanent failure loop, not a
transient one.

### D-3 (MEDIUM) — the 6,000-char budget is computed per-embed, not per-message
`_fit_embed` takes a single dict, but Discord's 6,000 limit is the sum across **all** embeds in a
message, and `_build_briefing_payload:517-523` adds a second (weekly) embed worth roughly 150 chars
after `_fit_embed` has already run. A main card fitted to exactly 6,000 ships at ~6,150 and is
rejected. Today's cards top out at 2,690 so nothing is failing in production — but the headroom is
not what the code believes it is.

### D-4 (MEDIUM) — a successful send whose status write fails will double-post
`consensus_engine/briefing/alfred.py:655-660`. `send_briefing_message` returns a message id, then
`db.upsert_briefing_run(..., status="posted")` runs. If that write raises, the exception unwinds
through `post_briefing` to `alfred_loop:701`, which logs and leaves the run `pending` — the next
60-second tick posts the whole brief again. There is no message-id-first write and no
already-sent check.

Same shape, one line up: `_post_briefing_json:600` returns `str(resp.json().get("id", ""))`. A 200
response without an `id` yields `""`, which `post_briefing:656` reads as failure and leaves pending —
so a message that did land gets posted a second time.

The rest of E is sound: an `archived` run short-circuits at line 631-633, a `None` return from
`send_briefing_message` leaves the run `pending` and retryable, and a retry rebuilds from stored
`rendered_content` rather than re-calling the AI.

### D-5 (LOW) — a retry stamps the card with the retry's date, not the brief's
`_build_briefing_embed:450` calls `_clock_line()` at build time. The archived text keeps the original
timestamp, so a brief rendered at 05:55 and retried after midnight posts a card whose date line
disagrees with the vault copy of the same brief.

### D-6 (LOW) — `_section_key_for_heading` prefix-matches
See G. `"Macrohard Inc"` maps to `macro`. Contained today by the fixed writer, but the code comment
claims word matching and delivers prefix matching.

### D-7 (LOW, honesty) — "0 silent cuts" is scoped narrower than it reads
`corpus-replay.md` reports "fields trimmed, each ending in a visible `…`: **0** — nothing is cut
silently", which I confirm for trimming. Separately, text that lands in the preamble is dropped with
no marker at all: for the 26 briefs with no markdown headings the **entire** body is discarded
(worst case `2026-05-22`, all 2,230 characters, producing a five-placeholder card), and even among
the 53 that parse, 97-584 characters per brief (median 180) are dropped as preamble. The evidence
file does call the 26 "shown correctly as empty-with-placeholder rather than being silently mangled",
which is a defensible reading, but "nothing is cut silently" and "2,230 characters discarded with no
marker" sit uneasily in the same document. Worth one clarifying sentence.

## H. Reference comparison — the claim is honest

The July 30 reference Overnight groups tickers with scores into one sentence; the new card's real
output ("SNDK (82/100) and APO (55/100) show strength; GE (25/100), VIST (58/100), and DIS (52/100)
under pressure...") is the same shape at the same density. Section order and emoji anchors are
identical. "At least as quick to scan while preserving the underlying facts" holds, and the file
earns credibility by recording that v1 *failed* this bar (raw bullet dump with dangling dashes) and
saying so plainly rather than quietly shipping v2 as if it were the first attempt.

## I. Honesty audit — the stated limits are accurate

The "what this does NOT prove" statements in `corpus-analysis.md`, `corpus-replay.md` and
`spy-snapshot-check.md` are correct and I found nothing elsewhere in those files contradicting them.
The corpus genuinely stores rendered text only, so a facts-level replay genuinely is impossible; no
weekly chains were snapshotted, and the weekly chart is described only as verified against the live
chain. `spy-snapshot-check.md` is careful in the right way — it says a straddle-implied vol and a
quoted vol "are not required to be identical" and reports the ratio spread (median 1.15, max 1.88)
instead of claiming agreement.

Two overclaims, both already itemised above: the live-test file's "No 'ET'/'Eastern' anywhere"
generalises a single run into a property the code does not have (D-1), and "nothing is cut silently"
does not cover preamble discard (D-7).

## VERDICT

Discrepancies found — 7:

1. **D-1 (HIGH)** — `alfred.py:388` / `:176-210`: forbidden "ET"/"Eastern" reaches the card on the deterministic fallback path; guard covers the AI reply only.
2. **D-2 (MEDIUM)** — `alfred.py:478-485` with `:238-239`: `_fit_embed` can exit at 6,543 chars because `top_story` is uncapped; Discord 400s and the retry is byte-identical, so it loops forever.
3. **D-3 (MEDIUM)** — `alfred.py:470` / `:517-523`: the 6,000-char budget is enforced per-embed, but Discord applies it per-message across both embeds.
4. **D-4 (MEDIUM)** — `alfred.py:655-660` and `:600`: a send that succeeds but whose status write fails (or that returns 200 with no `id`) leaves the run `pending` and double-posts on retry.
5. **D-5 (LOW)** — `alfred.py:450`: a retry stamps the card with the retry's date, disagreeing with the archived copy.
6. **D-6 (LOW)** — `alfred.py:268-279`: prefix matching, not word matching; `"Macrohard Inc"` maps to `macro`.
7. **D-7 (LOW, honesty)** — `corpus-replay.md`: "nothing is cut silently" does not cover preamble discard (up to 2,230 chars dropped unmarked).

A, B, D, F, H and I pass. C passes on the AI path and fails on the fallback path. G passes on real
data and over-matches on constructed input. Nothing here contradicts the core claim that the new card
removes the `content[:1990]` silent-truncation failure — that part reproduces exactly, 27 of 79
briefs were being cut before and 0 are now.


---

## Fixes applied (2026-08-17, same session)

All 7 discrepancies addressed in `consensus_engine/briefing/alfred.py`:

- **D-1** `_scrub_timezone_labels()` now runs on the FINAL rendered text and again on any
  stored brief before it is turned into a card. Only the label token is removed, so
  "Cash opens 9:30 ET" becomes "Cash opens 9:30" (never relabelled as Pacific) and the
  `$ET` ticker survives. Test built from the 4 real archived strings.
- **D-2** `top_story` capped at 600 chars, and `_fit_embed` now trims the description once
  the fields are at their floor, so the card can never exceed the budget and retry forever.
- **D-3** the 6,000-char budget is now applied ACROSS the message: the weekly embed is sized
  first and the main card is built with the remainder.
- **D-4** `_posted_id()` returns a sentinel when Discord answers 200 without an id, so a
  successful post always leaves `pending`; a failed status write now logs the message id and
  an explicit do-not-retry line.
- **D-5** the card reuses the clock line stored with the brief (`_clock_from_text`), so a
  retry shows when the brief was BUILT, matching the archive.
- **D-6** `_section_key_for_heading` matches whole words — "Macrohard Inc" no longer maps to
  the macro section.
- **D-7** the "nothing is cut silently" claim in `corpus-replay.md` now states the preamble
  caveat explicitly.

**Re-verified over the real corpus** (all 79 archived `briefing_runs` rows, replayed through the
fixed builder): `tz_label_leaks=0  over_limit=0  missing_fields=0`, with 4 briefs scrubbed
(the 4 that carry "All times EST"). Alfred tests: 40 passed.
