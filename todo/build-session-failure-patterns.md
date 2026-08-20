# What went wrong building #85–#87, and how to stop it happening again

**Status:** ONGOING
**Created:** 2026-08-19

**CURRENT STATUS (2026-08-19):** A record, not a task. Everything listed here is already
fixed. It exists so the next feature build starts by reading the five checks at the
bottom instead of rediscovering the same traps. Read it at the START of a build, not
after.

---

## The one that actually cost you money

**File ownership flipped, and a whole live feed died silently for 2.1 days.**
`/home/openclaw/.openclaw/schwab_token.json` became root-owned on 2026-08-17 during an
earlier session. The bot runs as a different user, so every real-time options request
failed from then until 2026-08-19. The `#errors` channel warned twice; nobody read it.

Knock-on effect: the SPY expected-move charts that #87 was built for **never appeared on
a single real brief.** Every morning brief recorded `{"daily":{"error":"unavailable"}}`.
The free Yahoo backup can't cover it either — at 5:51 AM there are no usable option
prices, because the options market doesn't open until 6:30 AM.

Same trap, second instance in one session: 668 repo files were left root-owned and had to
be handed back.

**Prevention:** after any step that runs as root, list what it touched and hand it back.
Memory: `reference_schwab_token_ownership_trap.md`.

## The checks that were supposed to catch it

1. **The 6:15 AM automatic brief check failed the only time it ran.** It couldn't write to
   the notification log (wrong owner), and it broke when started from a different folder.
   Fixed: the log is now writable by the bot's user, and the script finds its own folder.
2. **That same check was reporting a false number.** It said "0 charts" on cards that
   carried both, because it counted the wrong list — Discord moves an uploaded image out
   of the message's attachment list once an embed points at it. Fixed to count the embeds.
   A checker that reports the wrong thing is worse than no checker.
3. **Nobody looked at the output of the feature in the wild.** #87 was declared done on a
   replay of stored briefs. One glance at the real posted card would have shown no charts,
   for two days running.

## Things the owner found, not the build

- **The daily expected-move numbers were in the wrong place** — buried at the top of
  "Levels to Watch", five fields away from the chart they describe, while the weekly pair
  sat together in their own card. Fixed: both horizons now use the same shape.

## Waste and self-inflicted errors

- **The first model race burned the whole $3/day AI budget in one sitting** and left the
  bot unable to answer. The rewrite cost $0.39 for six models: screen on 3 questions,
  full set only for survivors, and a spend meter that stops the run at a budget.
- **The written answer key was partly invented.** It claimed Wolf has a "bullish, forming"
  view on Google. There is no Google thesis at all — 41 stored, none of them Google.
  Models that answered correctly were graded wrong. Check a key against the database
  before grading anything with it.
- **The bot's own prompt was teaching a wrong fact** — it said options flow comes from
  Yahoo, untrue since 2026-07-02.
- **Probes written from memory instead of from the code**: a module that doesn't exist, a
  database column that doesn't exist, arguments in the wrong order, objects treated as
  dictionaries, a search pattern that missed because the file uses `export KEY=`. Five
  wasted round-trips. Read the code first.
- **The same wrong command typed three times in a row** (a database update missing its
  folder change) before stepping back and fixing the script instead.
- A folder change leaked into later commands and broke relative paths.
- A cost figure was written into a record *after* it was saved, so it never saved.
- A quoting mistake killed a push before it started.

## Loose ends left standing (not blocking anything)

- Schwab going down fires **two** alerts for one cause: "login has EXPIRED" (wrong) and
  "can't open its own login file" (right).
- A dead scheduled task from 2026-08-12 (`1786518088_84cd1d`) still sits in the task list;
  it tried to resume a Codex session and Codex is out of quota until 2026-08-22.
- Exa and Brave web search are out of credits, so the engine runs in degraded mode —
  tracked separately as #67.
- One question from the #85 test set is still unanswered by every model tried: why the
  bot gave false earnings signals. It needs a longer investigation than a live chat
  reply allows.

---

## The five checks to run on the next feature build

1. **Watch it work in the wild before calling it done.** A replay of stored data is not
   proof. Read the real posted output, on the real day, at the real time.
2. **Check the time of day the feature actually runs at.** A market feature scheduled
   before the market opens is a different feature. #87's charts worked perfectly at
   every hour except the one that mattered.
3. **Hand files back after running as root.** Every time. It has now silently broken a
   live feed once and the repo once.
4. **Test the checker as hard as the feature.** Prove it reports the right number on a
   known-good case and a known-bad one.
5. **Read the code before writing the probe**, and read `#errors` before assuming things
   are healthy — the outage alerts were correct and sat unread for two days.

## Files involved

- `consensus_engine/briefing/alfred.py` — the brief card
- `consensus_engine/scanners/expected_move.py` — the SPY numbers and charts
- `scripts/check_morning_brief_card.py` — the 6:15 AM verdict
- `scripts/schwab_login.py` — the token file and its owner
- `scripts/qa_feature_questions.py` — the model race and its spend meter
