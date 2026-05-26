# Redesign the CLAUDE.md DoD checklist to be scope-aware

**Status:** DONE 2026-05-22.

**Layperson:** The "Critical paths for this project" list in CLAUDE.md (lines 17-23) was built up incident-by-incident — every time a prior session declared something "done" while something else was broken, that broken thing got added to the list. The result is a "check everything every time" checklist that's mostly unrelated to whatever I'm currently working on, and it creates a perverse incentive: when one of those checks fails for reasons unrelated to my changes, the DoD rules forbid me to call it "pre-existing", so I'd be forced to fix unrelated bugs before claiming my own work is done.

**The problem (concrete):** Today's session shipped yt-chain-fixes work — three new features touching ONLY YouTube ingest code (local_video_ingest.py, captions_llm_parser.py, gemini_video_parser.py for logging, plus tests). The current DoD requires me to verify:
  - `!ask` / `!trend` / `!all <ticker>` Discord commands — these route through Discord/gateway code that I never touched
  - `@-mention <BOT>` — separate agent path, untouched
  - Cron scripts run as openclaw — separate codebase, untouched
  - `/root/.openclaw` symlink — pure VPS-consolidation residue, untouched

None of those share a code surface with the yt-chain work, yet the checklist would have me probe them anyway. If any happens to be flaky for unrelated reasons, I'd be on the hook.

**Current items + where each came from (from session memory):**
  - Services active under systemd ← VPS consolidation (May 11)
  - `!ask`/`!trend`/`!all` reply in Discord ← `!trend` momentum fix + `!all` v2 + `!ask` time-context fix
  - `@-mention <BOT>` replies ← agentic mention feature batch
  - Cron scripts run as openclaw ← VPS consolidation
  - Boot drift check ← gateway/consensus chain alignment work
  - `/root/.openclaw` symlink resolves ← VPS consolidation

## Proposed redesign — scope-aware tagging

Restructure the DoD checklist as a tag→checks map. Each check carries one or more surface tags. Each feature batch (or even individual commit) declares which surfaces it touches, and only the matching tag-bucket of checks runs.

```
# Critical-path checks (scope-aware)

[always]                      # invariants — every batch runs these
  - consensus-engine.service active
  - openclaw-gateway.service active
  - No `❌ GATEWAY drift` Discord alert since restart

[gateway]                     # run if the batch touched gateway / consensus chain config
  - Engine boot logs "boot drift check: gateway chain matches consensus.yaml"

[discord-commands]            # run if the batch touched gateway/commands/alerts paths
  - `!ask`, `!trend`, `!all <ticker>` return coherent replies

[agent-mention]               # run if the batch touched openclaw-agent / mention paths
  - `@-mention <BOT>` returns a coherent reply

[infra]                       # run if the batch touched systemd / paths / VPS layout
  - Cron scripts (check_searxng_health.sh, run_reference_assertions_cron.sh) exit 0
  - /root/.openclaw resolves to /home/openclaw/.openclaw

[ingest]                      # run if the batch touched scanner / video / SEC ingest
  - (no current checks; potential future addition)
```

A feature batch declares its surfaces in the kickoff prompt / discover state.json, OR an LLM auto-detects surfaces from the diff (e.g. via file-path matching: `consensus_engine/scanners/youtube*` → ingest; `consensus_engine/alerts/commands.py` → discord-commands; `openclaw-gateway/` → gateway/agent-mention; etc.).

## Where this lives
- Current list: `/home/openclaw/.openclaw/workspace/CLAUDE.md` lines 17-23
- Related memory entries: `feedback_no_premature_closure.md`, `feedback_verify_before_claiming_done.md`, `feedback_real_world_testing.md` — each documents the incident that added one of the current items
- Past sessions where the issue surfaced: yt-chain-fixes (2026-05-15, this session) — multiple times I had to debate whether to probe Discord commands that had no relationship to my YouTube work

## Acceptance
1. CLAUDE.md "Critical paths" section restructured into tag-keyed buckets like the example above
2. A clear rule for how a batch declares its surfaces — either explicit (e.g. `surfaces: [ingest, infra]` in the EXECUTE.md or commit prefix), or implicit (path-pattern auto-detect)
3. The DoD prose ("pre-existing / out-of-scope NOT valid exemptions") updated so it applies WITHIN the relevant tag-bucket — i.e. a gateway-tagged check failing during an ingest-batch is genuinely pre-existing and out of scope, and saying so is fine.
4. A migration check: run the redesigned DoD against this session's yt-chain-fixes diff — assert it only requires `[always]` and possibly `[ingest]` checks, NOT `[discord-commands]` or `[agent-mention]`.

## Out of scope
- Tagging every existing memory entry / past commit. Just the forward-looking DoD.
- Re-running historical DoD checks against past sessions.
