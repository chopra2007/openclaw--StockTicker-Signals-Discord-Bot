# Progressive / 2-stage / interim embed for !all — WONTFIX (KILLED by user 2026-06-06)

The user explicitly killed this feature on 2026-06-06.

**The idea (so you recognize it if it comes back):** on a `!all <TICKER>` cache miss, post the
structured numbers (direction, price, levels, max-pain, P/C-OI, R:R) first in ~5-20s, then edit that
same Discord message in place with the written analysis once the slow AI step finishes. Also referred to
as "2-stage embed", "two-stage embed", "interim embed", "progressive embed", or an `on_interim` callback /
`all_command.progressive_embed_enabled` config flag.

**Do NOT:**
- build it
- propose it
- add a `progressive_embed_enabled` (or similarly named) config flag
- add an `on_interim` / leader-follower callback to `single_flight_get` or the `!all` aggregator

**For any future audit / discover / quality / latency pass:** if you rediscover "show `!all` numbers first,
then edit the narrative in", treat it as **out of scope** — it is a settled decision, not an open gap.

**Why this file exists:** the idea is genuinely tempting (it's a real perceived-speed win) and kept getting
re-surfaced by every audit and latency pass, so it would otherwise be re-suggested again. This tombstone is
the record that the user already decided against it.
