# Add a !em command that shows a stock's expected daily move

**Status:** DONE 2026-08-15
**Created:** 2026-06-25

**CURRENT STATUS (2026-08-15):** Extended and re-verified live. `!em <ticker>` is
the daily expected move and the new `!emw <ticker>` is the week ahead; both take
several tickers at once (`!em spy qqq`) and share the horizon. Weekly picks the
LISTED expiry closest to 5 trading sessions out and never invents a date. The
card grew from 4 fields to 7 (both ATM legs now show bid/ask/mid/spread/OI/volume,
plus the exact expiry and real session count) and the chart is dark-themed with a
Pacific-time axis. Accuracy: the displayed 1-sigma band no longer mixes a
calendar-annualised implied vol with a trading-day clock — on 677 stored
one-session records the old band covered 70.6% overall but only 55.8% of the 86
weekend-crossing ones, the corrected band covers 66.8% and 67.4%. Day counting now
uses the real NYSE calendar (holidays + early closes + the fraction of the current
session) instead of weekdays. Crossed books are rejected; the strike can't wander
further than 5% of spot or one strike step. 3318 tests pass, 0 fail. Evidence:
`.omc/plans/em-command-upgrade-findings.md`. Commits b21cabf, ffb8adb.

## Goal
Let a user type `!em SPY` (or any optionable ticker) in Discord and get the options
market's implied **expected move** for the day — the up/down range the market is
pricing in — as a clean embed plus a candlestick chart. Shows *today's* expected
move while the market is open; once the market has closed, shows the *next
session's*.

## What was built (all LIVE as of 2026-06-25)

- **`consensus_engine/scanners/expected_move.py`** (new) — the whole feature:
  - Async option-chain fetch via `run_in_executor` (yfinance is blocking), same
    pattern as `scanners/options.py`.
  - Expected-move math ported from the standalone exemplar
    `daily_expected_move_spy_qqq.py`: raw ATM straddle (headline), 0.85-adjusted
    straddle, IV×√(1/252) 1-SD band, straddle-implied-IV cross-check.
  - **Expiration selection** is market-hours aware: today's expiry if the NYSE
    regular session is open (and >~30 min left), else the next listed
    expiration. Uses the holiday/early-close-aware NYSE calendar via
    `utils/time_context.nyse_open_now()` (added this session).
  - **Liquidity guard (no allowlist):** works on any optionable ticker; the ATM
    strike must clear an open-interest floor (`expected_move.min_atm_open_interest`,
    default 100) and a spread sanity check, else a friendly "too illiquid" / "no
    options" message. (Allowlist removed per user, 2026-06-25.)
  - **Chart:** matplotlib/mplfinance candlesticks (5-min/5-day, falls back to
    15-min then daily), rendered to PNG **bytes** (lazy import), with EM band,
    spot line, and right-side price labels.
  - **Embed:** compact, non-directional (neutral yellow). NO "⚠ delayed / not a
    forecast" line (user asked to remove it); provenance kept quiet in the
    footer: `yfinance · quotes H:MM PM ET · delayed`.
- **`consensus_engine/alerts/discord.py`** — added `send_command_embed_with_image()`:
  aiohttp **multipart** upload (`payload_json` + `files[0]`, embed references
  `attachment://<file>`). The engine had never attached an image before; mirrors
  `_safe_send`'s dry-run/token/allowed-mentions/429-retry. Falls back to an
  image-less embed if the upload fails.
- **`consensus_engine/alerts/commands.py`** — `elif command == "em"` branch +
  `_handle_em` / `_em_and_reply`; `!em` added to the module docstring and the
  `!help` embed (Ticker Intel section); footer count 30 → 31.
- **`consensus_engine/utils/time_context.py`** — added reusable `nyse_open_now()`.
- **`config/consensus.yaml`** — new `expected_move:` block (allowed_tickers,
  min_atm_open_interest=100, multiplier=0.85).
- **`requirements.txt`** — added matplotlib + mplfinance (already installed in the
  engine's `/usr/bin/python3`).
- **`tests/test_expected_move.py`** — 14 tests (allowlist, expiration selection,
  ATM selection incl. illiquid step-out, EM math, embed shape, disallowed guard).
- **`daily_expected_move_spy_qqq.py`** (repo root) — the original standalone
  research script / exemplar the engine module was ported from.

## Verification done
- 14 new unit tests pass; **476 tests pass** across all touched-module test files
  (commands, discord, time_context, options, all_command) — no regressions.
- **Live in #chat** via the real handler: `!em SPY` and `!em AAPL` posted correct
  embeds with attached charts (confirmed by fetching the messages back — embed
  image resolved to a real Discord CDN URL); `!em F` returned the friendly
  allowlist rejection.
- Engine restarted clean; both services active; symlink intact.
- Fixed a pre-existing ownership trap surfaced by the restart: `openclaw.json`
  was `root:root` (since 2026-06-24) → boot drift check couldn't read it →
  chowned back to `openclaw:openclaw`; re-ran `boot_drift_check()` → "gateway
  chain matches consensus.yaml", stale drift state cleared.

## Limitations / notes for a cold pickup
- Data is **yfinance, ~15-min delayed**. Yahoo's per-leg IV is unreliable
  (understates vs the straddle-implied IV by ~15-17%; QQQ's put IV violated
  put-call parity by ~7 vol pts) — that's *why* the raw straddle (actual market
  price, model-free) is the headline number, not the IV figure.
- No allowlist (user decision 2026-06-25): `!em` works on any optionable ticker;
  the `min_atm_open_interest` floor (100) + spread check is the sole liquidity
  gate. Non-optionable / nonsense tickers get a friendly "no options" reply.
- `!em` is not feature-flag-gated (shipped live like `!all`/`!options`, since it
  is a read-only command that does not touch the live alert path).
- The chart PNGs `SPY_daily_em.png` / `QQQ_daily_em.png` at repo root are sample
  outputs from the first research task; harmless but could be gitignored/removed.

## Possible next steps (optional)
- Swap yfinance for a real-time feed (Tradier/Polygon) by implementing a new
  provider — the math/embed/chart layers are feed-agnostic.
- Add a holiday calendar populate for `alfred.market_holidays` (currently empty)
  if other parts of the engine want holiday awareness too.

---

## Session notes 2026-08-15 — daily/weekly split + accuracy pass

**What changed**

- `!em` is daily, `!emw` is weekly (the user chose two commands over a horizon
  word). Both keep multi-ticker support with one shared horizon. Typing the old
  word syntax (`!em spy weekly`) answers with the other command's usage line,
  because DAILY and WEEKLY are both valid ticker shapes and would otherwise be
  looked up as stocks.
- `compute_em(ticker)` still defaults to daily, so the `!all` vol tag and
  `scripts/iv_snapshot_daily.py` are untouched.
- Weekly expiry = the listed expiration whose remaining-session count is closest
  to `WEEKLY_TARGET_SESSIONS` (5). A monthly-only chain gets its nearest monthly
  and the card states the real session count.
- Time to expiry moved onto the shared NYSE calendar (`utils/time_context.py`
  gained `session_dates()` and `session_bounds()`). 2026-07-02 -> 2026-07-06 is
  now 1 session, not 2 (2026-07-03 is the Independence Day holiday).
- New `iv_em_1sd` key scales implied vol by CALENDAR time to match how the chains
  quote it. `iv_em_to_expiration` deliberately keeps its old trading-day clock —
  `iv_snapshot_daily.py` has stored that exact quantity since 2026-06-29 and
  changing its meaning would break comparison against those 3,268 rows.
- The 1-sigma band is now `Optional`: when implied vol is unusable the card says
  so instead of printing the straddle range under a "~68%" heading.
- Quote guards: crossed books (bid above ask) rejected; strike distance capped at
  5% of spot or one strike step, whichever is larger.

**The accuracy finding (the reason for the clock fix)**

Live on 2026-08-15 Schwab quoted SPY implied vol at 5.8% while SPY's own straddle
implied 7.9% on a trading-day clock. The whole `iv_snapshots` sample shows the
same gap and it tracks calendar days exactly (median straddle-implied / quoted 1σ
= 0.83 at 1 calendar day, 1.52 at 3, 1.63 at 4 — maths predicts 0.83 / 1.44 /
1.66). Coverage on 677 one-session records: 1σ 70.6%, raw straddle 62.8%,
0.85×straddle 54.8%. So the popular "0.85 × straddle = the 68% move" rule is
wrong, and the 68% label belongs only on the 1σ band. The headline stayed the
straddle (a traded price, model-free) and is now labelled as such.

**Verified live** (engine restarted, commands posted into the commands channel
and the posted messages read back through the Discord API): `!em spy qqq` ->
daily card each, expiry 2026-08-17; `!emw spy qqq` -> weekly card each, expiry
2026-08-21, 5 sessions; `!em spy weekly` -> the `!emw` usage line; `!em BGS` ->
honest illiquidity refusal (its $4 call really was quoted 0.05 / 0.10);
`!help` -> both commands listed. Both attached charts downloaded and inspected.

**Not proven by the sample:** weekly calibration (only 353 non-overlapping weekly
observations over seven weeks), and intraday behaviour (every stored snapshot is
captured after the close, so the new fraction-of-session maths is backed by tests
and derivation, not stored outcomes).
