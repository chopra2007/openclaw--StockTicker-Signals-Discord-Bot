# Add a !em command that shows a stock's expected daily move

**Status:** DONE 2026-06-25
**Created:** 2026-06-25

## Goal
Let a user type `!em SPY` (or any allowed ticker) in Discord and get the options
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
  - **Allowlist + liquidity guard:** only the ETFs/large-caps in
    `config/consensus.yaml > expected_move.allowed_tickers` (editable); the ATM
    strike must clear an open-interest floor and a spread sanity check, else a
    friendly "too illiquid" message.
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
- Allowlist is curated (ETFs + ~25 large caps). Add tickers by editing
  `expected_move.allowed_tickers` in consensus.yaml — no code change, picked up
  on next engine restart.
- `!em` is not feature-flag-gated (shipped live like `!all`/`!options`, since it
  is a read-only command that does not touch the live alert path).
- The chart PNGs `SPY_daily_em.png` / `QQQ_daily_em.png` at repo root are sample
  outputs from the first research task; harmless but could be gitignored/removed.

## Possible next steps (optional)
- Swap yfinance for a real-time feed (Tradier/Polygon) by implementing a new
  provider — the math/embed/chart layers are feed-agnostic.
- Add a holiday calendar populate for `alfred.market_holidays` (currently empty)
  if other parts of the engine want holiday awareness too.
