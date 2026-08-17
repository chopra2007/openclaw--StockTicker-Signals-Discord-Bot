# Evidence pack — TODO #86 "Make VVIX leadership and streaks obvious"

Gathered 2026-08-17. Research only — no feature code was written and nothing outside
this folder was touched.

Detail file this supports: `todo/vvix-vix-relative-lead-streak.md`

---

## Headline findings (read these first)

1. **All 23 saved days are there, and they are all contiguous trading days.**
   2026-07-15 through 2026-08-14, Monday–Friday, no missing days, no holiday gaps.
   So the "weekends must not break a streak" rule is real and needed, but the
   "missing day stops the streak" rule has **no example to test against in this data**.
   A test for it has to be a made-up (synthetic) case.

2. **There is not a single 3-day upward VVIX lead in the whole history.**
   The longest same-direction lead streak in 23 days is **1 day**. Counted:
   - 4 one-day downward leads (VVIX fell more than VIX): 07-20, 07-24, 08-03, 08-11
   - 1 one-day upward lead (VVIX rose more than VIX): 08-13
   - 1 one-day divergence (VVIX up while VIX down): 08-07
   - 17 days with no same-direction lead (or the first day, which has no prior)

   Consequence for the task: the "↑ 3 market days may foreshadow higher volatility"
   wording **cannot be backed by this data at all**. There are zero cases, not
   "too few". The detail file asks to measure what VIX did in the next 1 and 5
   sessions after each qualifying streak — that measurement has **no cases to run on**.
   The card must stay purely descriptive.

3. **The one recoverable live card matches the database exactly.**
   The 2026-08-14 `!market` card printed `VVIX 87.5 (−2.2% today) vs VIX 14.2 (−2.6% today)`
   and "higher than 42% of the past year's readings". The stored row gives
   −2.1695% / −2.5974% and residual_pct 0.42063. Date, signs and rounding all agree.
   No stale date, no wrong sign.

---

## Files in this folder

| File | What it is | Why it matters |
|---|---|---|
| `vol_of_vol_daily.json` | Every row of the `vol_of_vol_daily` table, oldest first (23 rows). Raw dump from `consensus.db`. | The raw input. Any future implementation must reproduce numbers from exactly these values. |
| `precomputed-lead-streak.json` | Hand-computed reference table: for each date the VVIX % change, VIX % change, the percentage-point lead, the lead direction, and the streak length. Plus the next-1-session and next-5-session VIX % change for each day. | This is the **ground truth to check the future implementation against**. It was computed by a throwaway script directly from the raw dump, not by any repo code, so it is an independent check. Not a feature file. |
| `chat-vvix-mentions.txt` | The Discord `#chat` search results plus a line-by-line cross-check against the matching database row. | Proves the currently-shipped card agrees with stored data. |
| `commands.py.vvix-excerpt.txt` | Excerpts of `consensus_engine/alerts/commands.py` — lines 2055-2110 (the daily-change helper), 2218-2270 (the "Fear of fear" field text), 2575-2610 (where `!market` loads the rows). | The exact code the new lead/streak line has to slot into. |
| `db.py.vol_of_vol_daily-excerpt.txt` | `consensus_engine/db.py` lines 1292-1307 (the table shape), plus the writer in `scripts/market_daily.py` and the reader in `consensus_engine/analysis/market_panel.py`. | Shows the whole read/write path. Note: `db.py` itself has no functions for this table — only the table definition. |
| `test_vvix_residual.py.txt` | Full copy of `tests/test_vvix_residual.py`. | The existing test coverage the new streak tests must extend without breaking. |
| `vvix-vix-daily-change.md.txt` | Full copy of `todo/vvix-vix-daily-change.md`, the completed prior step (TODO #81). | Contains the "safe omission" rules (when to leave the numbers off) that the new line must keep obeying. |

---

## How the reference table was computed

Rules applied, taken from the detail file:

- **Upward lead** on a day: both VVIX and VIX rose, and VVIX's percent gain was larger.
- **Downward lead**: both fell, and VVIX's percent loss was larger in size.
- **Mixed** (one up, one down) extends neither streak. Recorded separately as a
  one-day divergence.
- **Lead size** = VVIX % change minus VIX % change, in percentage **points**
  (not a percent of a percent).
- **Streak** = count of back-to-back stored trading days with the same lead direction.
  A break in the run of trading days resets it to zero. Saturday and Sunday are not
  counted as breaks.

Each row in `precomputed-lead-streak.json` also records `business_days_gap` (how many
weekdays passed since the prior stored row). Every row in this data has a gap of
exactly 1, i.e. no gaps at all.

---

## Gaps and limits — read before making any claim

- **Only 23 days of data, one month.** Nothing here supports a rate, a percentage,
  or a hit-rate of any kind.
- **Zero 3-day upward leads.** The house rule is: show raw counts before rates, and
  claim no predictive value from fewer than 10 resolved cases. Here there are **0**
  cases, so no forecast wording of any kind is defensible. If a future version wants
  to say a 3-day lead "may foreshadow higher volatility", that sentence has no
  support in this database and should not ship as a claim.
- **Forward VIX moves were still recorded** in the reference table (`vix_fwd_1sess_pct`,
  `vix_fwd_5sess_pct`) for every day, so the measurement can be re-run cheaply once
  more history accumulates. Right now it has nothing to filter on.
- **No holiday in the window.** The 07-15 to 08-14 range contains no market holiday,
  so holiday behaviour is untested by real data.
- **Only one historical card was recoverable** — the last 100 `#chat` messages contain
  exactly one `!market` output with a "Fear of fear" section (2026-08-14). Older cards
  are past the 100-message window. One match is not a broad audit; it is one confirmed
  agreement between card and database.
- **The reference table's first row (2026-07-15) has no prior day**, so its changes are
  blank by design, matching how the live code omits the numbers when there is no
  previous row.
