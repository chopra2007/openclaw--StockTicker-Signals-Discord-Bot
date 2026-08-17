# TODO #86 — INDEPENDENT adversarial verification (second pass, read-only)

**Run:** 2026-08-17 · **Verifier:** separate pass, did not author the code.
**Method:** recomputed every number from the raw `vvix`/`vix` closes in
`.omx/evidence/todo-86/precomputed-lead-streak.json` in my own python, then ran the real
`compute_vvix_lead_streak` and diffed. Nothing below is taken from the existing report.

---

## A. Rules match? — **PASS (with one edge-case FAIL, see H / Discrepancy 1)**

`consensus_engine/alerts/commands.py`

| Rule | Line | Code | OK |
|---|---|---|---|
| up-lead = both > 0 and vvix bigger | 2126 | `if vvix_pct > 0 and vix_pct > 0 and vvix_pct > vix_pct:` | yes |
| down-lead = both < 0 and vvix loss bigger | 2128 | `elif vvix_pct < 0 and vix_pct < 0 and vvix_pct < vix_pct:` | yes (`<` on signed pct = bigger loss) |
| mixed → neither streak | 2130-2131 | `else: return result` (direction stays None, streak 0) | yes |
| exact tie → neither streak | 2126/2128 | strict `>` / `<`, no epsilon | **see Discrepancy 1** |
| gap 1..5 continues, 6+ stops | 2109-2110 | `if gap_days < 1 or gap_days > 5: return None` | yes — 5 allowed, 6 rejected, no off-by-one |
| lead = vvix% − vix% in points | 2124 | `result["lead_pts"] = vvix_pct - vix_pct` | yes |
| streak walk continues in same direction only | 2135-2145 | `for i in range(1, len(rows)-1)` with the same two tests, `break` on first failure | yes, indices correct (compares rows[i] vs rows[i+1]) |

Comparison operators and the gap bounds are correct. No off-by-one found in the loop:
with 23 rows the loop can reach the oldest pair, and it stops on `None` (bad value / bad gap).

## B. Recompute the replay — **PASS**

I recomputed all 22 pairs myself as `(new-old)/old*100` and ran the function on the
newest-first window ending at each date. Sample arithmetic:

- **2026-08-14 (Fri, gap 1):** vvix 89.41999816894531 → 87.4800033569336 = **−2.1695%**;
  vix 14.630000114440918 → 14.25 = **−2.5974%**; lead = −2.1695 − (−2.5974) = **+0.4279 pts**.
  Both fell, but VVIX fell LESS → not a down-lead → direction None, streak 0. Code agrees.
- **2026-08-13 (Thu, gap 1):** vvix 88.5 → 89.4199 = **+1.0395%**; vix 14.55 → 14.63 = **+0.5498%**;
  lead **+0.4897** → up-lead, streak 1. Code agrees.
- **2026-07-20 (Mon, gap 3 — after a weekend):** vvix −1.9548%, vix −0.6393%, lead **−1.3155**
  → both fell, VVIX fell more → down-lead, streak 1. The 3-day calendar gap did NOT break it. Code agrees.
- **2026-08-10 (Mon, gap 3 — after a weekend):** vvix +2.3114%, vix +3.7584%, lead **−1.4470**
  → both rose but VIX led → no lead. Code agrees.
- **2026-08-03 (Mon, gap 3):** vvix −0.9057%, vix −0.8130%, lead **−0.0927** → down-lead, streak 1. Code agrees.
- **2026-07-16 (first computable day):** vvix +5.9445%, vix +6.7645%, lead **−0.8200** → no lead. Code agrees.

Full 22-row diff: **0 mismatches** against my own arithmetic AND against the stored
`lead_pts` / `streak_direction` / `streak_len` in the JSON.
The report's "22 dates checked, 0 mismatches" is **credible and reproduced** (23 rows → 22 pairs).

## C. Zero-streak claim — **PASS**

My independent tally over the 22 computable days:
- no same-direction lead: **17**
- up-lead days: **1** (2026-08-13), streak length 1
- down-lead days: **4** (2026-07-20, 2026-07-24, 2026-08-03, 2026-08-11), each streak length 1
- three-day up streaks: **0** · two-day down streaks: **0** · longest streak of any kind: **1 day**

Identical to the report. True.

## D. No predictive wording — **PASS**

Actual rendered strings, `commands.py:2309-2318`:

```
VVIX leading higher by {abs(lead_pts):.1f} pts today · ↑ {streak_days} {market day|market days}
VVIX leading lower by {abs(lead_pts):.1f} pts today · ↓ {streak_days} {market day|market days}
No same-direction VVIX lead today
```

Formats match the required strings exactly, including the `·` separator, the ↑/↓ arrows,
one decimal on the points, and the singular "market day" at streak 1 (2310, 2314).
No "may foreshadow", "signals", "suggests", "expect", "watch for", or any other forecasting
verb anywhere in the block. Statement of fact only.

## E. Card vs database — **PASS**

Newest stored row `2026-08-14`: vvix **87.4800033569336**, vix **14.25**, residual_pct **0.42063**.
Card shows VVIX **87.5**, VIX **14.2** (`:.1f` rounding — correct), −2.2% / −2.6% (my recompute:
−2.1695% and −2.5974%, rounds to −2.2 / −2.6 — correct), and "higher than **42%**" (0.42063 → 42 — correct).
Date is the newest row, not stale; the code also stale-gates on `computed_at` at `commands.py:2665`.

**Why "No same-direction VVIX lead today" is right even though BOTH fell:** a down-lead needs
VVIX to fall *harder* than VIX. VVIX fell 2.17%, VIX fell 2.60% — VIX fell more, so VVIX is the
*laggard*, not the leader. The lead is +0.43 pts, i.e. pointing the other way. No lead. Correct.

No stale date, no sign error, no card/database disagreement.

*(Two cosmetic notes on the pasted card excerpt — not defects in the code: the code renders a
Unicode minus `−` via `_fmt_daily_change` (2153), not the ASCII `-` shown in the paste, and the
paste omits the trailing `(2026-08-14 close).` and the `_Descriptive only…_` line that the code
always appends at 2318-2330. Assumed excerpt trimming.)*

## F. Display-only — **PASS**

Only caller anywhere in the repo: `consensus_engine/alerts/commands.py:2669`, inside
`_handle_market` (the `!market` dashboard), gated on `features.vvix_residual.enabled`.
`lead_pts` / `streak_days` / `direction` are read at exactly one place — the render block at
2305-2318 — and nowhere else outside tests. `scripts/market_daily.py` only *writes* the table;
`market_panel.py` only lists it. **No scoring path and no alert path reads any of it.**

## G. Ordering — **PASS**

Code order inside the field value: label + gloss (2304) → **lead line (2306-2318)** → trailing-year
percentile (2319-2320) → raw VVIX/VIX levels (2321-2329) → "_Descriptive only — it never moves a
score or fires an alert._" (2330). Comparison line is before the raw levels. Both the percentile
line and the descriptive-only warning survive. The real card shows the same order.

## H. Try to break it — **one real defect found**

| Adversarial input | Result |
|---|---|
| **Exact tie, +1% both** (vvix 100→101, vix 10.0→10.1) | **`direction='up', streak_days=1, lead_pts=3.7e-15`** — renders "VVIX leading higher by 0.0 pts today · ↑ 1 market day". **WRONG** |
| **Exact tie, −1% both** (vvix 100→99, vix 20→19.8) | **`direction='down', streak_days=1`** — renders "VVIX leading lower by 0.0 pts today · ↓ 1 market day". **WRONG** |
| Exact tie, +10% both (100→110 / 20→22) | `direction=None, streak 0` — correct (this pair happens to be exactly representable in binary) |
| 6-day hole mid-streak | streak stops at 1 — correct, no crash |
| `None` prior vvix | `{None, None, 0}` — no crash |
| Prior vix = 0 | `{None, None, 0}` — no crash (divide-by-zero guarded at 2114) |
| Rows out of order (oldest first) | `{None, None, 0}` — negative gap rejected, no crash, no nonsense streak |
| Malformed date `"not-a-date"` | `{None, None, 0}` — caught by `except ValueError`, no crash |
| Missing `date_utc` key | `{None, None, 0}` — caught by `except KeyError`, no crash |
| Two rows with the same date (gap 0) | `{None, None, 0}` — correct |
| Numbers stored as strings `"103"` | works (`float()` coercion), streak 1 |
| Negative vvix value | no lead, no crash |
| Real 3-day up streak across a weekend | `streak_days=3` — correct |
| 5-day gap | continues (allowed) · 6-day gap | stops — boundary exactly as specified |

Nothing raised an exception. One rule violation (the tie case above).

---

## VERDICT

**1 DISCREPANCY FOUND**

1. **Exact ties can be mis-scored as a lead, because of floating-point noise — `consensus_engine/alerts/commands.py:2126` and `:2128`.**
   The spec says an exact tie extends NEITHER streak, but the comparison is a bare strict
   `vvix_pct > vix_pct` with no tolerance. When the two identical percentage moves are not exactly
   representable in binary, the difference lands at ~1e-15 instead of 0 and the sign decides.
   Reproduced: vvix 100→101 and vix 10.00→10.10 are both exactly +1%, yet the function returns
   `direction='up', streak_days=1`, and the card renders the self-contradicting line
   **"VVIX leading higher by 0.0 pts today · ↑ 1 market day"** — it claims a lead of zero points.
   Same in the down direction with vvix 100→99 / vix 20→19.8.
   *Severity: low in practice* — VVIX and VIX closes carry many decimals, so an exact percentage
   tie is vanishingly unlikely in live data, and it is display-only (see F), so it can never move a
   score or fire an alert. But it is a spec violation and it produces a nonsense card line.
   *Fix:* compare with a tolerance, e.g. `vvix_pct - vix_pct > 1e-9` / `< -1e-9`.

2. **Test-coverage gap that hides #1 — `tests/test_vvix_residual.py:247-256`.**
   `test_lead_streak_exact_tie_is_no_lead` uses vvix 100→105 and vix 100→105, a tie that happens to
   compute to exactly 0.0 in binary floating point, so it passes for the wrong reason and gives false
   confidence that ties are handled. A tie built from different price scales (the 101/10.1 case above)
   fails. The tie test should use unequal price levels.

Everything else checks out: the rules, all 22 replayed dates, the zero-streak claim, the wording,
the live card against the database, the display-only isolation, and the field ordering.
Fresh test run: `python3 -m pytest tests/test_vvix_residual.py -q` → **25 passed** in 2.18s.

---

## Follow-up: both findings FIXED and re-verified (2026-08-17, by the main session)

**Provenance note.** The TODO plan named **Codex** as the independent verifier. Codex was out of
account quota (resets 2026-08-22) and the Gemini CLI then exhausted its free daily quota mid-run, so
this verification was performed by a fresh Claude subagent with no knowledge of the implementer's
reasoning, working only from the files and recomputing every number itself. That is weaker
independence than a different vendor's model, and it is recorded here rather than glossed. It was
still worth doing: it caught a real bug, reproduced below by hand before any fix was made.

**Finding 1 — floating-point tie mis-scored as a lead. FIXED.**
Reproduced independently before fixing:
    vvix 100 -> 101 and vix 10.00 -> 10.10 (both exactly +1%)
    vvix_pct = 1.0, vix_pct = 0.9999999999999963, difference = 3.66e-15
    old code returned {'direction': 'up', 'streak_days': 1}
Fix: `consensus_engine/alerts/commands.py` — added `_LEAD_EPSILON = 1e-9` and a single `_direction()`
helper now used for BOTH today's day and every day of the streak walk (previously the same comparison
was written twice, which is how the two paths could drift). A difference at or below the tolerance is
a tie, and a tie is not a lead.
Post-fix: the up-tie and the down-tie both return `{'direction': None, 'streak_days': 0}`.

**Finding 2 — tie test passed for the wrong reason. FIXED.**
`tests/test_vvix_residual.py::test_lead_streak_exact_tie_is_no_lead` used 100->105 against 100->105,
a same-scale tie that computes to exactly 0.0 and therefore passes with or without the bug. It now
uses different price scales (101/10.10 and 99/19.8, mirroring the real VVIX ~90 / VIX ~14 spread), so
it fails against the old code. A new test `test_lead_streak_tie_mid_streak_stops_it` covers a tie
landing in the middle of a streak.

**Regression check after the fix:**
- `python3 -m pytest tests/test_vvix_residual.py -q` -> **26 passed**
- Historical replay re-run over all 23 rows -> **22 dates checked, 0 mismatches** (unchanged: no real
  date was affected, because a genuine percentage tie has never occurred in the stored data).
