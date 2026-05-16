# Ship 1 + Ship 2 — Format & UX Pack + Narrative Pack v1

**Source audit:** `plans/external-feature-audit-2026-05-16.md` (commit `2989eb7`) — §1 Ships 1 and 2.
**Scope:** ONE PR landing both ships together. No new data fetches. Pure rendering + LLM prompting work.
**TODO ref:** `TODO.md` #7 (Optimize !all output quality + feature surface).

---

## Goal (the one user-observable outcome)

After this PR ships, the next `!all NVDA`, `!all AMD`, `!all TSLA` invocations in Discord render with **all 10 changes below visible in the embed**. If any single change is missing from any single ticker, the work is not done.

### Ship 1 — Format & UX Pack (6 sub-changes, all in `embed.py`)

1. **N1 — Cashtag formatting.** Tickers prefixed with `$` everywhere in the embed (title, body, evidence citations). `AAPL` → `$AAPL`.
2. **N2 — Direction emoji.** Title / direction line gains an emoji: 🟢 bullish, 🔴 bearish, ⚪ neutral. (Stretch: ⚡️ next to options-flow callouts, 🚨 next to insider/SEC catalysts, 🎯 next to TP hits.)
3. **N3 — Compact money notation.** All `$N,NNN,NNN` values reformatted as `$2.4M` / `$437K` / `$1.2B`. Apply to: market cap, volume, premium amounts, transaction values in evidence citations.
4. **N4 — Arrow icons on levels.** Stop-loss / TPs rendered with directional arrows: `↑ TP1 $185.20` (above current) / `↓ Stop $178.50` (below current) / `⇄ Buy zone $180.10-181.40` (around current).
5. **N5 — Plain-English one-liner under each metric.** Below each numeric line, a single italic sentence interpreting it. Example: under "Stop $178.50" → *"Below this, the post-earnings flat base breaks — exit."* The narrator can produce these via a separate one-line prompt per field, OR pre-canned templates per field-type.
6. **N7 — Relative date phrasing.** Replace ISO dates with relative ones: "Earnings: 2026-05-19" → "ER in 3 sessions"; "Ex-div: 2026-05-22" → "Ex-div in 6 days". (Depends on TODO #4 time-context — if Gemini eval-cron is still flaky, gate behind a config flag and emit ISO as fallback.)

### Ship 2 — Narrative Pack v1 (4 sub-changes, in `narrator.py` + `quality_bar.py`)

1. **M1 — TL;DR header.** First line of the narrative is a one-sentence thesis: `**TL;DR:** Long $NVDA above $920, target $980, stop $895 — reclaim of post-ER flat base on improving guide.` Narrator prompt must emit this with `**TL;DR:**` exact prefix so `embed.py` can extract it for display.
2. **M2 — Bear Case section.** Explicit titled section: `**What could go wrong:**` followed by 2-4 sentences. **Per critic + cross-model risk:** must be a `quality_bar.py` structured constraint, NOT a free-form prompt. The output is rejected and re-prompted if no `**What could go wrong:**` token is present in the narrative.
3. **M3 — Variant perception line.** A sentence in the body framed as: `Market view: <consensus take>. Our view: <bot's read>. Catalyst: <what makes the difference>.` Single sentence; no new bullets.
4. **M6 — Enumerated risk factors with mitigants.** A bulleted list `**Risks & mitigants:**` with 2-4 items: `- <risk> → <mitigant>`. Mitigants must reference concrete features the trade plan already has (e.g. `→ Trim half at TP1`, `→ Stop at $178.50`). Not vague ("be careful").

---

## Files to touch

| File | Change |
|---|---|
| `consensus_engine/alerts/all_command/embed.py` | Add formatter helpers: `_fmt_cashtag`, `_fmt_money_compact`, `_fmt_relative_date`, `_direction_emoji`, `_arrow_for_level`. Wire into existing `build_embed` / `build_levels_field`. |
| `consensus_engine/alerts/all_command/narrator.py` | Modify `_build_synthesis_prompt` to require the four narrative blocks (TL;DR, Bear Case, Variant Perception line, Risks bullets) in the LLM output. Update the CONSTRAINTS block accordingly. |
| `consensus_engine/alerts/all_command/quality_bar.py` | Add structural check: narrative MUST contain `**TL;DR:**`, `**What could go wrong:**`, and `**Risks & mitigants:**` tokens. Reject + retry if missing. Keep existing checks intact. |
| `tests/all_command/test_embed_format.py` (new) | Unit tests for each new formatter helper. |
| `tests/all_command/test_narrator_pack.py` (new) | Unit tests verifying CONSTRAINTS block contains the four required sections; verify quality_bar check rejects narratives missing them. |

**Explicitly out of scope:**
- `aggregator.py` — no new data fetches
- `levels.py` — no anchor/TP changes
- `structured_fields.py` — no new field computations
- `output_filter.py` — no changes (Bear Case must be reconcile-aware with COMPUTED SIGNAL, but that's a prompt clause, not a new check)

If you find yourself touching any file outside the four above, you've drifted scope. Stop and re-read this spec.

---

## Critical narrator-prompt clauses (bake these in)

Cross-model agreement (Codex + Gemini, both independent) flagged two failure modes in the Narrative Pack:

1. **Contradiction risk** — Bear Case can write something that contradicts COMPUTED SIGNAL (which is supposed to be authoritative per `narrator.py:238`). **Mitigation:** Add this clause to the CONSTRAINTS block: *"The Bear Case must acknowledge the COMPUTED SIGNAL'S direction. If our direction is bullish, the Bear Case enumerates what would invalidate the bullish thesis — not assert the opposite direction."*
2. **Hallucination risk** — LLM may invent negative catalysts for fundamentally strong tickers just to fill the Bear Case slot. **Mitigation:** Add this clause: *"Every Bear Case sentence must cite a specific evidence row from the evidence bundle (news_id, sec_id, twitter_id, etc.) by inline marker [evidence:N]. If no evidence supports a risk, omit it — short Bear Cases are acceptable when evidence is thin."*

---

## Definition of Done (project CLAUDE.md rules apply)

Verification standard from project CLAUDE.md: do not claim done until evidence of working from the user's perspective is produced.

### Phase A — Unit tests (necessary, not sufficient)
- `python3 -m pytest tests/all_command/test_embed_format.py tests/all_command/test_narrator_pack.py -v` → all green
- Full suite `python3 -m pytest tests/ -q` → no regressions vs pre-PR baseline

### Phase B — Real-world test (the actual gate)
- Restart the engine (or trigger code reload) so the changes are live: `sudo systemctl restart consensus-engine`
- **Invalidate xref_cache for the 3 test tickers** so we don't get pre-PR cached output:
  ```bash
  python3 -c "import sqlite3, hashlib; v=open('consensus_engine/__init__.py').read().split('=')[1].strip().strip(chr(34)); prefix='all_v'+hashlib.sha1(v.encode()).hexdigest()[:8]; c=sqlite3.connect('/home/openclaw/.openclaw/workspace/consensus.db'); [c.execute('DELETE FROM xref_cache WHERE ticker LIKE ?', (f'{prefix}:{t}',)) for t in ('NVDA','AMD','TSLA')]; c.commit(); print('cache cleared')"
  ```
- Invoke `!all NVDA`, `!all AMD`, `!all TSLA` via the Discord webhook (see project memory: `reference/discord_webhook.md` — webhook URL hits `#chat` where the bot receives commands)
- Wait up to 180s per ticker (per TODO #7: cache-miss render is 60-180s)
- Read each returned embed back from Discord. For each of the 3 tickers, verify **all 10 sub-changes** above are present in the embed. Use a checklist — score each ticker out of 10.
- Tail engine logs during the test for any `output_filter.py` contradict-retry triggers — these indicate the structured constraint is fighting the LLM, which is a failure mode.

### Phase C — Capture outputs for blind compare
- Save each ticker's full embed text (title + description + all fields, rendered as you would copy them) to:
  - `/home/openclaw/.openclaw/workspace/.omc/plans/ship1-ship2-blind-compare/nvda-bot.txt`
  - `/home/openclaw/.openclaw/workspace/.omc/plans/ship1-ship2-blind-compare/amd-bot.txt`
  - `/home/openclaw/.openclaw/workspace/.omc/plans/ship1-ship2-blind-compare/tsla-bot.txt`
- Also save the user-facing copy/paste Gemini prompt at `/home/openclaw/.openclaw/workspace/.omc/plans/ship1-ship2-blind-compare/GEMINI-PROMPT.txt`, with the exact text:
  ```
  Look at <TICKER> stock and come up with a bullish or bearish thesis, along with a trade plan composed of:
  1. buying level
  2. stop-loss level
  3. take profit level.
  ```
  (This is the canonical blind-compare prompt from TODO #1.)
- Write a one-page user instructions file at `/home/openclaw/.openclaw/workspace/.omc/plans/ship1-ship2-blind-compare/README.md` with:
  - 3-step copy-paste flow for the user: (1) paste GEMINI-PROMPT.txt into gemini.google.com with each ticker substituted, (2) compare Gemini's answer side-by-side with the corresponding `<ticker>-bot.txt`, (3) vote `prefer-bot` / `prefer-gemini` / `tie` per ticker.
  - Acceptance: 3/3 must be `prefer-bot` or `tie` for PR to merge per TODO #1's gate.

### Phase D — Commit (NOT push)
- If Phase B verifies all 10 changes × 3 tickers (≥27/30 acceptable; <27 → loop back to fix), commit locally only with conventional-commit message:
  ```
  feat(all): Ship 1 (format pack) + Ship 2 (narrative pack v1) per audit 2989eb7

  <body summarizing the 10 changes + DoD verification results>
  ```
- **DO NOT push.** User runs blind compare manually (Phase C) and decides whether to push or iterate.

### Phase E — Stop and notify user
- Print to terminal:
  ```
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ Ship 1 + Ship 2 implementation complete.
  ✅ Verified live for NVDA/AMD/TSLA. Score: N/30.
  ✅ Local commit: <sha> (NOT pushed)
  ✅ Blind-compare materials at:
     .omc/plans/ship1-ship2-blind-compare/
  
  NEXT (user action):
  1. Open .omc/plans/ship1-ship2-blind-compare/README.md
  2. Follow the 3-step copy-paste flow into Gemini
  3. Vote prefer-bot/prefer-gemini/tie per ticker
  4. Report back the 3 votes — if 3/3 prefer-bot or tie,
     push the commit. Otherwise iterate.
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ```
- Do not start any new work. Exit.

---

## Failure-mode handbook (skip if not needed)

| If you see... | Do this |
|---|---|
| Pre-PR baseline test suite already has failures | Note the baseline, ensure your changes don't add new failures. Don't try to fix pre-existing red. |
| Cache invalidation script errors (missing sqlite db, version-hash mismatch) | Read `consensus_engine/__init__.py` to verify the version string format, adjust hash computation accordingly. |
| Engine restart fails | Read `/var/log/syslog` for the systemd unit failure, fix the root cause. Do not bypass with `--no-validate` or similar. |
| !all returns from cache anyway (15-min TTL) | Re-run the cache invalidation; verify the prefix matches by SELECT * from xref_cache LIMIT 5. |
| !all times out (>180s) | Check engine logs for LLM chain failures; possibly the new prompt is too long. If structured constraint forces multiple retries, the timeout compounds. |
| Quality bar rejects 3+ retries on the same narrative | The constraint is too strict for the model. Loosen the regex (e.g. allow `## What could go wrong` as well as `**What could go wrong:**`) before forcing the model into doom-loops. |
| One of the 3 tickers fails verification while 2 pass | Investigate the specific ticker's evidence bundle; may be a thin-evidence case where the model couldn't produce a Bear Case with citations. Document and decide: relax constraint or skip ticker. |
| `output_filter.py` triggers a contradict-retry | The Bear Case is contradicting COMPUTED SIGNAL. Re-read clause #1 in "Critical narrator-prompt clauses" — strengthen the wording. |
| Discord webhook fails or returns garbled | Re-read `reference/discord_webhook.md` for the working webhook URL. If still broken, use `python3 -c "...direct invoke aggregator.handle_all..."` as fallback for verification. |
| You finish all 10 changes but score is 15-26/30 | Loop — for each missing change, isolate the ticker/sub-change that failed and either fix the code or strengthen the prompt. Do NOT declare done at partial. |

---

## What you do NOT do

- **Do not push to GitHub.** User explicitly held back the push.
- **Do not commit any of the pre-existing unstaged changes** (`.omc/prd.json`, `TODO.md`, `.omc/plans/yt-chain-next-steps-brief.md`). They predate this PR.
- **Do not edit `aggregator.py` / `levels.py` / `structured_fields.py` / `output_filter.py`** — out of scope.
- **Do not run the blind compare yourself.** The user runs it manually with Gemini.
- **Do not update `TODO.md` to mark TODO #7 done.** The user marks it done only after blind compare passes.
- **Do not add backwards-compat shims or feature flags** for the format changes (per project CLAUDE.md). Just change the code.
- **Do not bypass tests / hooks / verification.** If pre-commit fails, fix the underlying issue.

---

## Reference

- Audit spec source: `plans/external-feature-audit-2026-05-16.md` §1 Ships 1 + 2
- Architecture map: `TODO.md` #7
- Definition of Done: `CLAUDE.md` (project root)
- Blind compare workflow: `TODO.md` #1
- Discord webhook: project memory `reference/discord_webhook.md`
- Engine restart: `sudo systemctl restart consensus-engine` (verify `active` after)
- xref_cache schema: `consensus_engine/alerts/all_command/cache.py`
