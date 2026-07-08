# One-command Schwab weekly re-login helper

**Status:** OPEN
**Created:** 2026-07-08

## Goal
Make the weekly Schwab OAuth re-login painless. Today it's a manual scramble that
races a 30-second timer and failed twice before working.

## Background — what happens now
- Schwab's refresh token dies **7 days after the last browser login** and the
  auto-refresh CANNOT extend it (proven: refresh returns the same token). When it
  lapses, the real-time options feed silently drops to free ~15-min yfinance data.
- `scripts/schwab_reauth_check.py` only WARNS (daily timer). There is **no committed
  script that performs the login** — renewal is hand-done each week.
- The renewal flow: open a Schwab OAuth authorize URL → log into the brokerage
  account → approve → Schwab redirects to `https://127.0.0.1/?code=...` (a page that
  won't load) → copy that URL → exchange the `code` for a fresh token. The `code`
  **expires in ~30 seconds**.

## What went wrong 2026-07-08 (why a helper is worth it)
- First two exchange attempts returned `invalid_grant` ("code invalid/expired").
- Root cause was NOT the user's paste speed and NOT bad creds/redirect (creds matched
  the working refresh exactly; error was `invalid_grant`, not `invalid_client`).
- Real cause: the assistant's **Stop hook (`verify-on-done.py`) stalled ~80 seconds**
  at end-of-turn while there were uncommitted code changes, so the pasted URL wasn't
  processed until the code had already expired. Committing first (clean tree → hook
  exits instantly) fixed it; the 3rd attempt succeeded (HTTP 200, 7-day token, verified
  live SPY quote).

## Possible next steps (priority-ordered)
1. **`scripts/schwab_login.py`** — one command that (a) prints/opens the authorize URL
   built from `SCHWAB_APP_KEY` + `SCHWAB_CALLBACK_URL`, (b) accepts the pasted redirect
   URL (arg or stdin), (c) exchanges `code`→token, (d) writes `schwab_token.json` in the
   exact shape `get_access_token()` expects (`{"token":..,"creation_timestamp":now,
   "_refresh_created":now}`), (e) chowns it back to openclaw + chmod 600, (f) clears the
   reauth marker, (g) verifies with a live quote + prints `reauth_days_left`.
   A working one-off already lives at `$CLAUDE_JOB_DIR/tmp/schwab_exchange.py` (this
   session) — promote it into the repo with tests.
2. **Timing:** whoever runs the exchange must have a **clean git tree first** (or set an
   env that skips the verify-on-done Stop hook) so the ~80s hook can't eat the 30s code.
   Document this in the script header.
3. **Optional:** a tiny local listener on the user's machine to auto-capture the redirect
   (removes copy-paste) — but the user isn't a coder and the redirect hits THEIR
   localhost, not the VPS, so this is likely out of scope; keep the paste flow.

## Files involved
- `consensus_engine/scanners/schwab_client.py` — token shape, `_creds()`, `get_access_token()`,
  `reauth_days_left()`, `clear_reauth_marker()`, `TOKEN_PATH`, `TOKEN_URL`.
- `scripts/schwab_reauth_check.py` — the existing warn-only reminder (REAUTH_STEPS text).
- `/home/openclaw/.openclaw/schwab_token.json` — the token file (openclaw-owned, 600).

## Open questions
- Should the helper open the URL in a browser automatically, or just print it? (VPS has
  no browser; the user is on their own machine — printing is probably right.)
- Add a systemd path/timer to nudge exactly at expiry rather than daily?
