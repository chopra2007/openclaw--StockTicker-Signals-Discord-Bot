# Claude Code Memory Refactor Prompt

You are running inside the target repository. Refactor the Claude Code auto-memory area so it matches Anthropic’s intended memory model and preserves every existing fact.

## Authoritative memory model to follow

Treat these as the operating assumptions for this migration:

1. `CLAUDE.md` is for persistent project/workflow instructions and conventions that should be loaded every session.
2. Claude Code auto memory uses a memory directory containing `MEMORY.md` plus optional topic files.
3. `MEMORY.md` is the entrypoint/index for that memory directory. It must stay concise because only the first 200 lines or first 25KB, whichever comes first, are loaded at the start of a conversation.
4. Topic files are for detailed notes. They are not startup-loaded by default; Claude reads them on demand.
5. Do not treat YAML frontmatter in memory topic files as an Anthropic requirement. Use frontmatter only if the existing memory directory already uses it or if it helps this project’s own organization.

## Critical safety constraints

- Do not use `git stash`, `git reset`, `git checkout -- .`, or other destructive cleanup commands.
- Do not delete old memory topic files during this migration. Preserve them unless a file is provably empty or a duplicate and you have already copied its contents into a replacement.
- Do not rewrite unrelated sections of `CLAUDE.md`.
- This prompt explicitly authorizes editing `CLAUDE.md` only for the narrow purpose of adding or merging a concise behavioral/execution rules section. Do not edit `comm-check.md`.
- Preserve all data. The goal is refactor/route/compress the index, not erase history.
- Prefer scripts/grep for mechanical bulk moves and link checks instead of many manual edits.
- Do not commit unless the user separately asked for a commit.

## Step 0: Locate and snapshot the real files

Before editing anything:

1. Find the active memory index file:
   - Prefer `.claude/memory/MEMORY.md` if it exists and contains `# Memory Index`.
   - Also check Claude Code’s auto-memory default location under `~/.claude/projects/<project>/memory/MEMORY.md` if present.
   - If multiple plausible files exist, inspect them and choose the one matching the large current index. Record which path you chose.
2. Locate `CLAUDE.md` at the repo root, if present.
3. Create a timestamped backup directory inside the memory directory, for example:
   - `.claude/memory/_migration_backup_YYYYMMDD_HHMMSS/`
4. Copy the original `MEMORY.md` and any sub-memory files you plan to edit into that backup directory.
5. Record baseline metrics:
   - `wc -l -c MEMORY.md`
   - count of links in `MEMORY.md`
   - list of existing topic files

## Step 1: Classify existing index bullets

Read the current `MEMORY.md` and classify every existing bullet into one of these destinations.

### Destination A: `CLAUDE.md` behavioral/execution rules

Move only stable instructions, triggers, and execution boundaries here. Examples:

- No “shall I proceed?” confirmation loops; execute the requested task.
- Do not suggest per-turn communication-style hooks.
- Do not edit `CLAUDE.md` or `comm-check.md` unless explicitly authorized in the current request.
- Classify instructions/triggers into `CLAUDE.md`; facts, incidents, and lessons into memory topic files.
- Answer direct questions directly when recent evidence already answers them.
- Do not offer to start work during a planning/review phase.
- Diagnose before blaming providers or transient outages.
- Verify before claiming done.
- Do not fabricate “actual/real/verified” claims without looking at the source.
- Do not use `git stash` in shared trees.
- Do not use real secrets as test fixtures.
- Log promised follow-ups before declaring work done.
- Surface deferred features clearly at done milestones.
- When real-world tests hit errors, diagnose, fix, and try alternatives before punting to the user.

Keep this section concise and action-oriented. Use headings and bullets. Do not paste long incident stories into `CLAUDE.md`.

### Destination B: memory topic files

Move factual history, incidents, technical state, research findings, project milestones, and environment quirks into topic files. These are not behavioral rules by themselves; they are evidence and context.

Use the target topic-file set below unless you discover that an additional file is necessary to avoid forcing unrelated material into the wrong category.

## Step 2: Create or update consolidated topic files

Create or update these files in the same memory directory as `MEMORY.md`.

Use this frontmatter pattern for newly created consolidated files if the repo’s memory files already use frontmatter or if you are introducing a consistent local convention:

```yaml
---
name: unique_snake_case_identifier
description: One-sentence summary
type: reference | project | history | user | feedback
---
```

If existing topic files do not use frontmatter, plain markdown is acceptable. Do not claim frontmatter is required by Anthropic.

### Required consolidated files

#### `user_profile.md`
Keep the user/environment profile, including Windows PC, Linux VPS, Debian target, akash@, and PT timezone.

#### `feedback_execution_protocols.md`
Store execution-style feedback and durable lessons about task handling, including:
- no confirmations
- no per-turn style hook
- do not offer to start
- direct answers
- investigate before fixing
- diagnose before blaming providers
- diagnose/explore alternatives before punting
- verify Codex file access before dispatching review
- do not launch deferred work in the current session when user scoped it to a future/new session
- any other execution-protocol feedback currently in the index

#### `feedback_workspace_management.md`
Store workspace/data-management lessons, including:
- specs and plans co-location
- bulk edit efficiency
- bulk block moves
- prompt example placeholders
- memory vs CLAUDE.md classification
- CI silent unless fail
- deliver promised confirmations
- log follow-ups before done
- surface deferred features
- no LLM patch in `!all` probes
- no git stash in shared tree
- no real secrets in test data
- max_tokens chain floor
- any related workspace-management feedback currently in the index

#### `feedback_verification_testing.md`
Store verification/testing expectations and lessons, including:
- verify before claiming done
- real-world testing
- live output before go-live
- prove during execution
- scanner ready before webhook ping
- no fabrication as fact
- thin-sample rate claims
- format-match comparison prompts
- grep producer→consumer path before explaining failures
- any other testing/verification feedback currently in the index

#### `history_comm_check_may.md`
Move all granular May 2026 `comm-check fail` bullets here, preserving dates, section numbers, root causes, and lessons.

#### `history_comm_check_june.md`
Move all granular June 2026 `comm-check fail` bullets here, preserving dates, section numbers, root causes, and lessons.

#### `reference_ownership_traps.md`
Group ownership, permission, service-env, and worktree-isolation references:
- `openclaw.json` ownership trap
- service `.env` ownership trap
- gateway state ownership trap
- service env file behavior
- worktree isolation broken by symlink
- related EACCES/root-vs-openclaw incidents

#### `reference_api_states.md`
Group integration/auth/channel state:
- Codex auth state
- Discord webhook and file sending
- external API key locations without exposing secret values
- drift alert channel
- Gmail token expiry
- SearXNG/web search state
- TweetShift/Discord gateway details that are reference state rather than project milestone narrative

#### `reference_provider_quirks.md`
Group provider/platform quirks:
- no `web-search-plus-plugin-v2`
- Gemini video model behavior and Gemini CLI headless notes
- YouTube VPS IP blacklist and dead methods
- Stocktwits Cloudflare blocks aiohttp
- yfinance options reference
- conftest flag-default-off
- any provider/rate-limit/quota quirks not better suited to model research

#### `reference_model_research.md`
Group model-selection and benchmark findings:
- Nemotron free retest
- 2026-06-15 model bake-off
- model-chain notes
- known hidden-reasoning/free-model limitations
- vol-indicator source/model-cost decisions only if they are about model/provider choice rather than project outcome

#### `project_legacy_shipping.md`
Group older project/milestone history through April–May 2026:
- Scanner architecture
- TweetShift integration
- SEC alert fix and hardening
- FinalYTplan
- Vault/Atlas/Alfred
- Signal engine audit
- Milestone 0 and Milestone 1
- Discover run / Pass 5
- VPS consolidation and gateway flap fix
- memory promoter patch
- todo-1456 verify
- F3/F1 YouTube chain
- blind compare
- discover stage3
- web search fix
- options flow shipped
- `!all` levers shipped
- other April–May project milestones not better suited elsewhere

#### `project_wolf_engine.md`
Group all Wolf/Gmail/#news engine state:
- Gmail/Wolf connected
- Wolf macro-brain direction
- wolf-news-brain discover run
- Wolf phase 1–4 live/built milestones
- Wolf email excerpt tool
- Wolf go-live and extraction-accuracy fixes
- deep-dive 2026-06-08 Pass 5
- Wolf-specific deferred follow-ups

#### `project_signal_volatility.md`
Group signal, analyst, and volatility project state:
- signal-features discover runs
- signal-features Phase 1/2
- analyst tweet register
- todo-sweep
- YouTube pipeline health if tied to signal generation
- volatility indicator Phase 1, Phase 2/3 no-go, free-exhausted notes
- options/volatility notes not already placed in legacy shipping

## Step 3: Preserve existing detailed files

For every old link currently in `MEMORY.md`:

1. Check whether the linked file exists.
2. If it exists and contains useful detail, keep it.
3. In the appropriate consolidated topic file, either:
   - migrate the bullet’s concise content and include a link back to the detailed old file, or
   - merge the full content if the old file is tiny and the consolidation improves clarity.
4. If a link target is missing, record it in a `## Missing legacy links found during migration` section in the best matching consolidated topic file.
5. Do not leave unique content reachable only from the backup directory.

## Step 4: Refactor `MEMORY.md` into a compact routing index

Replace the dense index with this compact structure, adjusting only if Step 2 required an extra file to prevent data loss:

```markdown
# Memory Index

## User
- [User Profile](user_profile.md) — Workspace configuration, PC/VPS environments, and timezone.

## Behavioral Feedback & Execution Lessons
- [Execution Protocols](feedback_execution_protocols.md) — Auto-execution limits, direct-answer rules, multi-agent usage, and diagnosis-before-fix lessons.
- [Workspace & Data Management](feedback_workspace_management.md) — Plan co-location, bulk edits, CI silence, follow-up tracking, and safety fixture rules.
- [Verification & Testing](feedback_verification_testing.md) — E2E validation, live output verification, source-tracing, and sample-rate constraints.

## Technical Reference
- [Infrastructure Ownership Traps](reference_ownership_traps.md) — Root vs openclaw permissions, service env files, and worktree isolation issues.
- [API & Integration State](reference_api_states.md) — Webhook targets, auth states, key locations, Gmail expiry, and channel routing state.
- [Provider Quirks & Constraints](reference_provider_quirks.md) — YouTube VPS blacklists, Stocktwits Cloudflare blocks, Gemini behavior, and source-specific limitations.
- [Model Research](reference_model_research.md) — Nemotron testing, model-chain bake-offs, and current model-selection findings.

## Project State & Milestones
- [Legacy Shipping History](project_legacy_shipping.md) — April–May 2026 scanner, gateway, YouTube, milestone, and `!all` shipping history.
- [Wolf Market Engine](project_wolf_engine.md) — Gmail/Wolf connection, Phase 1–4 deployment state, #news behavior, and extraction-accuracy fixes.
- [Signal & Volatility Tracking](project_signal_volatility.md) — Signal-feature runs, analyst register, YouTube health, and volatility-indicator outcomes.

## Incident & Comm-Check History
- [Comm-Check Failures — May 2026](history_comm_check_may.md) — Root-cause validation failures and lessons from May 2026.
- [Comm-Check Failures — June 2026](history_comm_check_june.md) — Delegation seams, verification misses, and June 2026 comm-check failures.
```

After writing it, confirm:
- `MEMORY.md` is below 25KB.
- Preferably `MEMORY.md` is also below 100 lines.
- Every link in `MEMORY.md` resolves to an existing file.

## Step 5: Verification audit

Run a small verification script or shell pipeline that checks:

1. Every markdown link target in the new `MEMORY.md` exists.
2. Every required consolidated topic file exists.
3. `MEMORY.md` byte count is less than 25,000.
4. No old linked file was deleted.
5. Distinctive strings from the original index are still present somewhere in the memory directory, not just in the backup. At minimum check for these strings:
   - `No confirmations`
   - `No Fix C hook`
   - `Don’t touch CLAUDE.md/comm-check` or `Don't touch CLAUDE.md/comm-check`
   - `comm-check fail 2026-06-13`
   - `openclaw.json ownership trap`
   - `YouTube IP-blacklist dead methods`
   - `Wolf phase-4 LIVE`
   - `vol-indicator Phase-3 NO-GO`
   - `No real secrets in test data`

If any verification fails, fix it before final response.

## Final response format

Do not claim “done” until verification passes.

Return:

1. Chosen memory directory path.
2. Files changed.
3. `MEMORY.md` before/after line and byte counts.
4. Verification results.
5. Any missing legacy link targets or unresolved ambiguities.
6. Whether `CLAUDE.md` was edited, and exactly what section was added/changed.

Keep the final response concise and concrete.
