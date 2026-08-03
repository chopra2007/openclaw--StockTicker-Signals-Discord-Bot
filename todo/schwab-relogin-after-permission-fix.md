# Restore Schwab real-time data (browser re-login)

**Status:** DONE 2026-08-03 — browser login completed; live feed recovered
**Created:** 2026-07-21

**CURRENT STATUS (2026-08-03):** DONE. The browser login was completed. The engine is
refreshing its Schwab token, the saved `schwab_feed` state is `up`, and the recovery
message appeared in `#errors`. Real-time prices are active again.

**Related items from the same session:** this was found while investigating why the bot
hung and could not answer — see **#79** (the four Discord reliability bugs, all fixed) and
**#45** (the repeated-command loop, reopened; still needs a real guard). This item is only
the Schwab half.

## What happened

Discovered while investigating why the bot never posted a "Schwab is back" note (user's
question in #chat, 2026-07-21 06:20 UTC — the same question that hung the bot).

`/home/openclaw/.openclaw/schwab_token.json` was left owned by `root:root` mode 0600 on
2026-07-14 21:05 (the known root-edit ownership trap). The engine runs as `openclaw`, so
**every** Schwab call failed with `PermissionError: [Errno 13] Permission denied` from that
moment on.

Two consequences, both user-visible:

1. Real-time Schwab data has been dead for 7 days, silently, on the delayed fallback.
2. `schwab_health.classify_failure()` had no case for a local permission error, so it fell
   through to `api_down` — whose alert reads *"Schwab's own servers are erroring... you'll get
   a note here when it recovers."* The user was told five times over six days that Schwab was
   down, and the promised recovery note could never arrive, because nothing was wrong at
   Schwab and the condition could not clear itself.

## What was fixed (done, committed)

- `chown openclaw:openclaw /home/openclaw/.openclaw/schwab_token.json` — applied 2026-07-21.
- `consensus_engine/scanners/schwab_health.py` — new `TOKEN_UNREADABLE` failure class,
  checked FIRST in `classify_failure`, with honest copy ("Nothing is wrong at Schwab...
  will NOT clear on its own") and the actual one-line `chown` fix.
- `tests/test_schwab_health_classify.py` — pins that a `PermissionError` is never again
  reported as a Schwab outage, and that every class has title/detail/fix copy.

## Why the login is still needed

With the permission problem gone, the real state surfaced. Verified as the `openclaw` user
on 2026-07-21:

```
SchwabRefreshTokenExpired: Schwab refresh token past its 7-day wall — browser re-login required
```

The refresh token was last written 2026-07-14 and Schwab's wall is 7 days, so it lapsed
while the file was unreadable. That is a genuine `token_lapsed` — only a human with a
browser can clear it.

## After the login

The `#errors` channel should post the "Schwab real-time data is back" recovery note on the
next successful call (`ops_alert` fires on the transition, and `ops_alert_state` currently
holds `schwab_feed = down`, so the transition is armed and will fire).

Worth confirming that note actually appears — it is the exact promise that went unkept for
six days.

## Files involved

- `/home/openclaw/.openclaw/schwab_token.json` (ownership — fixed)
- `scripts/schwab_login.py` (the manual step)
- `consensus_engine/scanners/schwab_health.py` (classification — fixed)
- `consensus_engine/api_adapters.py:382` `_note_schwab()` (reports ok/failure each call)
- `scripts/schwab_reauth_check.py` (the scheduled re-auth watcher)

## Open question

The weekly-login expiry is a standing chore that has now bitten more than once. Worth asking
whether the reauth check should escalate louder as the 7-day wall approaches, rather than
only alerting after the token has already lapsed.
