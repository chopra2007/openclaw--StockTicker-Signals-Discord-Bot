# The test robot cannot tell us when it fails

**Status:** OPEN
**Created:** 2026-08-28

**CURRENT STATUS (2026-08-28):** Found while fixing the remote test run for
TODO #104. GitHub's test robot tried to post its failure notice to Discord and
got back `Unknown Webhook` — the address it has saved points at a Discord
webhook that no longer exists. So when the remote test run fails, **nobody is
told**. Run `33189714617` failed 7 tests and the notice never arrived.

## What is broken

`.github/workflows/regression-gate.yml` lines 82 and 95 read a GitHub secret
called `DISCORD_WEBHOOK_URL`, last set 2026-05-21, and post to it with `curl`.
Discord answers `Unknown Webhook`, which means that webhook was deleted.

The webhook this server uses for its own messages (`CLAUDECODE_WEBHOOK` in
`/root/.openclaw/.env.service`) was checked today and **is alive**. The dead one
is only the copy stored inside GitHub, which cannot be read back from here —
GitHub only lets you overwrite a secret, never read it.

## The fix

Replace the stored secret with a live webhook address:

```
gh secret set DISCORD_WEBHOOK_URL   # then paste a working webhook URL
```

Then push any commit and confirm a message actually lands in the channel. Do
not paste the address into chat, a log, or a commit.

## Why it matters

The whole point of the remote test run is to catch a break that this server
misses. A silent failure notice makes it decorative.
