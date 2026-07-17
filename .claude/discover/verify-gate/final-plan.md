# TODO #77: Mechanical Verify-Before-Stating Gate — Final Build Plan

## System Overview

The failure (#77, ~7th instance): Claude relays a status/verdict as current fact without probing the primary source; only user pushback triggers a check, and the claim turns out wrong (latest: the SessionStart 'Schwab login EXPIRED' banner, when the token was 21.5h old and a live pull worked). #40 named the mechanism: passive rules (CLAUDE.md 'Verification ladder', comm-check §3, memory) inform but do not INTERRUPT at answer-time, and don't propagate to sub-agents.

Fix = two mechanical layers, both zero standing context:
- **(C3) INPUT-side** — the SessionStart digest tags machine-snapshot banners as UNVERIFIED so the model receives the doubt with the data
- **(C9) DECISION-side** — a Stop/SubagentStop hook that fires ONLY when the final message is claim-shaped AND no verification tool ran this turn AND no citation is present, blocking just that message to demand a probe

C9 is the enforcer; C3 is the nudge that removes the single most common incident class (relayed notification). C4 (a Haiku disambiguation layer over the same claim-shaped subset) is a contingency built only if C9's regex false-fires above 5%, and the go/no-go is measured from a real decision ledger C9 writes, not guessed.

Verified via code.claude.com/docs/en/hooks and the working precedent verify-on-done.py: `last_assistant_message` is delivered directly on both Stop and SubagentStop (no transcript parse needed for the claim text itself), the block/exit-0 contract matches verify-on-done.py exactly, and SubagentStop stdin carries agent_id/agent_type — but the docs do NOT guarantee a distinct agent_transcript_path field, so the verification walk must resolve its transcript defensively (agent_transcript_path if present, else transcript_path, else fail-open allow) rather than assume it.

## Component Architecture

Three touch points, mirroring the existing hook layout under /root/.claude (all files root:root, read by the root-running Claude process):

### 1. NEW /root/.claude/hooks/verify-claim-gate.py (C9)
A deterministic Stop + SubagentStop hook (~140 lines) modeled 1:1 on the structure of verify-on-done.py (read_input / allow() / block() / outer try/except fail-open / stop_hook_active guard / recursion-sentinel env / git-common-dir project gate). No LLM, no per-turn cost on the ~99% of turns with no claim-shape. Writes one JSON decision record per invocation to /root/.claude/hooks/logs/ (same LOG_DIR the precedent already uses).

### 2. EDIT /root/.claude/settings.json
Append verify-claim-gate.py to the existing `Stop[0].hooks` array (which already runs verify-on-done.py at timeout 240; multiple hooks per event are allowed) and add a new sibling `SubagentStop` array pointing at the same script.

### 3. EDIT /root/.claude/hooks/openclaw-digest.sh (C3)
Rewrite Block 1 (lines 11-16) so each notification line is emitted under an 'UNVERIFIED as of <ts> — probe the primary source before repeating' label, ts taken from the line's own embedded `[YYYY-MM-DD HH:MM:SS UTC]` stamp (fallback: file mtime). Pure bash, no new deps.

### 4. NEW /root/.claude/hooks/tests/test_verify_claim_gate.py
A standalone subprocess-driven test file for C9 (not in the trading repo's tests/; the hook lives outside the repo).

### Deferred: C4 contingency
No code this cycle. It is a future fallback branch inside verify-claim-gate.py (a `type` escalation) enabled only after the decision ledger shows a measured false-fire baseline >5%.

### Scope Gate
C9 reuses verify-on-done.py's constant DEFAULT_PROJECT_GIT="/home/openclaw/.openclaw/workspace/.git" and its git_common_dir(cwd) gate so it is active only in this project + its worktrees and silent in every other repo — matching the precedent and avoiding surprise in the user's other work.

## Data Flow Pipeline

### C9 (per finished turn)
Claude ends turn → Claude Code invokes Stop (or SubagentStop for a spawned agent) with stdin JSON.

Stop carries `{session_id, transcript_path, cwd, stop_hook_active, last_assistant_message, ...}`; SubagentStop additionally carries `{agent_id, agent_type}` and MAY carry agent_transcript_path (not guaranteed by the docs fetched this cycle).

Gate steps, all short-circuiting to allow():

1. stop_hook_active==true → allow (honors the 8-block cap / recursion)
2. recursion-sentinel env set → allow
3. git_common_dir(cwd) != project → allow (scope gate)
4. msg = last_assistant_message (read the SAME field on both Stop and SubagentStop); empty/absent → allow
5. **CITATION ESCAPE**: msg matches a file:line, a URL, or a fenced/quoted block → allow (already evidenced)
6. **CLAIM-SHAPE (condition A)**: msg matches the narrow AND-of-subject-and-verb status regex with negative-lookaround guards for hedged/negated clauses (see Data Structures); no match → allow — this excludes 'market is down 2%', 'if the token expired…', and 'the login has NOT expired'
7. **VERIFICATION-THIS-TURN (condition B)**: pick the transcript path = agent_transcript_path if present, else transcript_path, else → allow (fail-open; nothing to walk). Open it, walk to the last real user turn (a user message whose content is NOT solely tool_result), collect tool_use names after it; if any in {Read,Bash,Grep,Glob,WebFetch,WebSearch} → allow. If the chosen transcript is unreadable/empty → allow (fail-open, covers the documented async write-lag)
8. Only if claim-shape AND no verification AND no citation → block() with a probe-first reason; exit 0

Every path (allow or block) appends one JSON record to the day's decision log before exiting, in its own try/except so a log failure never changes the decision.

### C3 (once per session)
SessionStart → openclaw-digest.sh reads /root/task_system/notifications.log; if non-empty, each alert line is printed under the UNVERIFIED label with its own timestamp; the model receives the banner already framed as a snapshot to probe. Digest still writes nothing.

## Data Structures

### In verify-claim-gate.py (module constants)

**DEFAULT_PROJECT_GIT / PROJECT_GIT resolution**: reuse verify-on-done.py's pattern with a VERIFY_CLAIM_GATE_PROJECT_GIT override env for out-of-tree testing.

**LOG_DIR** = '/root/.claude/hooks/logs' (reused).

**SUBJECT** = r'(?:login|token|session|auth(?:entication)?|feed|service|connection|gateway|api|credential|refresh[- ]?token)'

**VERB** = r'(?:expired|down|failed|authenticated|logged[- ]?in|revoked|unreachable)'

**CLAIM_RE** = compiled, re.I, AND-of-subject-and-verb within ~40 chars in either order (SUBJECT.{0,40}VERB | VERB.{0,40}SUBJECT), NOT a bare verb list — kills 'market down' false-fire. **GUARDED by negative lookarounds** so a hedged/conditional/negated clause does not fire: reject when any of {if, would, might, in case, unless, not, n't} appears in the same clause as the subject/verb pair (e.g. 'if the token expired…', 'the login has NOT expired', 'this would fail if…'). Implemented as a clause-scoped negative check around the match, kept conservative (bias to NOT block on ambiguity).

**CITE_RE** = matches https?:// | a file.ext:line token | a ``` fence — evidence escape.

**VERIFY_TOOLS** = {'Read','Bash','Grep','Glob','WebFetch','WebSearch'}.

**Transcript walk** reuses the verified pattern: json.loads each line, msg=d['message']; a user turn is role=='user' with content NOT all tool_result; collect tool_use `name` from assistant blocks after the last user-turn index.

**DECISION RECORD** (one JSON object per invocation, appended to /root/.claude/hooks/logs/claim-gate-YYYYMMDD.log):
```
{
  ts,
  event ('Stop'|'SubagentStop'),
  decision ('allow'|'block'|'allow_escaped'|'allow_noclaim'),
  matched_verb (or null),
  snippet (<=120 chars of last_assistant_message),
  tools_this_turn (list),
  transcript_source ('agent'|'main'|'none')
}
```

This ledger is the ONLY way the C4 go/no-go (false-fire >5%) is measured rather than guessed.

**Stop stdin fields consumed**: last_assistant_message (always, both events), transcript_path, agent_transcript_path (SubagentStop, optional), cwd, stop_hook_active.

**C3 needs no new structure** — reuses the plain-text log line's `[YYYY-MM-DD HH:MM:SS UTC]` prefix.

## Integration Plan

### 1. WRITE /root/.claude/hooks/verify-claim-gate.py (root:root, chmod +x)
Copy the skeleton of verify-on-done.py: same read_input(), allow(), block(reason), git_common_dir(cwd), recursion-sentinel env guard (VERIFY_CLAIM_GATE_ACTIVE), project-git override env (VERIFY_CLAIM_GATE_PROJECT_GIT), and the outer `try: main() except: sys.exit(0)` fail-open.

main() implements the 8-step flow above, reading last_assistant_message on both events and resolving the verification transcript as agent_transcript_path → transcript_path → fail-open.

block() reason (kept to ONE line to avoid a wall of text, since verify-on-done.py may also block the same stop):

> You stated a status/verdict as fact — "<first 80 chars>" — without a verifying probe this turn. Check the primary source (the live API/log/token/feed) and restate with that evidence, or cite the file:line / URL / tool output you already have.

Append the decision record (own try/except) just before every exit.

### 2. WRITE /root/.claude/hooks/tests/test_verify_claim_gate.py
Drives the hook via subprocess with synthetic stdin + fixture transcripts (cases enumerated in Verification Checklist).

### 3. EDIT /root/.claude/settings.json
In `hooks.Stop[0].hooks` append `{"type":"command","command":"python3 $HOME/.claude/hooks/verify-claim-gate.py","timeout":30}`

Add a sibling `hooks.SubagentStop:[{"hooks":[{"type":"command","command":"python3 $HOME/.claude/hooks/verify-claim-gate.py","timeout":30}]}]`

Preserve root ownership; re-validate with `python3 -m json.tool`.

### 4. EDIT /root/.claude/hooks/openclaw-digest.sh Block 1 (lines 11-16)
Keep the loud red banner + the '👉 Summarize…' footer, but replace the bare `cat "$NOTIF"` with a `while IFS= read -r line || [[ -n "$line" ]]; do … done` loop that, per non-empty line, extracts the leading bracketed timestamp (bash ${line%%]*} then strip the leading '[') and prints:

> UNVERIFIED as of <ts> — machine snapshot; probe the primary source before repeating: <line>

Fallback ts = file mtime if no bracket. The `|| [[ -n "$line" ]]` guard prevents a missing trailing newline from aborting under `set -euo pipefail`. No other block changes.

### No edits to CLAUDE.md, comm-check.md, MEMORY.md, or any repo file
The two hard constraints (gate at decision time; no standing injected text) forbid them and this plan meets the ask without them.

## Failure Handling

**Fail-open is absolute (both hooks)**: verify-claim-gate.py wraps main() in try/except → sys.exit(0); any bad JSON, missing/unreadable transcript (including the SubagentStop case where neither agent_transcript_path nor transcript_path is present or readable), regex error, or exception allows the stop. A hook bug can never trap Claude. Matches verify-on-done.py.

**Decision ledger is non-load-bearing**: the per-invocation JSON append to /root/.claude/hooks/logs/claim-gate-YYYYMMDD.log is wrapped in its own try/except, so a full disk or permission error writes nothing and still returns the same allow/block. The ledger only exists to measure the C4 go/no-go later.

**Two Stop hooks now coexist** (verify-on-done.py + verify-claim-gate.py). Both honor stop_hook_active, so across a single stop there is at most one block ROUND total; but if both would block the same stop, Claude Code surfaces both reasons — the claim-gate reason is deliberately kept to one line so the combined feedback isn't a wall of text.

**Async transcript lag** (documented: transcript_path 'may lag the in-memory conversation'): a just-run verification tool might not be flushed, which could cause a false block. Mitigated by biasing condition B to allow (unreadable/empty/absent transcript → allow) and by the citation escape; residual false-fire is exactly what the ledger measures and C4 later absorbs.

**Hedged/negated false-fire**: the negative-lookaround guards on CLAIM_RE keep 'if the token expired…' and 'the login has NOT expired' from firing; the guard is conservative (bias to not block) so a novel phrasing errs toward allow, not toward trapping the agent.

**Recursion / 8-block cap**: step 1 honors stop_hook_active and the recursion-sentinel env; the platform also force-ends after 8 consecutive blocks, so a stuck gate self-releases.

**Scope containment**: git-common-dir gate keeps C9 silent outside this project, so a regex quirk can't affect the user's other repos.

**Ownership trap** (MEMORY: root edits flipping owner): settings.json and the hooks are already root:root and read by the root-running Claude process; edits must preserve root ownership (chown root:root back if a non-root tool wrote them), or the session/hook silently breaks.

**Timeout**: 30s cap on the hook (transcript walk + regex is milliseconds); on timeout Claude Code proceeds, no trap.

**C3 digest keeps `set -euo pipefail`**: the while-read loop uses `|| [[ -n "$line" ]]` so a missing trailing newline on the last line can't abort the digest.

## Feature Activation Plan

**C3 ships FIRST and ON** (highest ROI, zero per-message cost, directly kills the exact Schwab-banner incident class). Verify against a real SessionStart before considering it done.

**C9 ships ON**, registered on BOTH Stop and SubagentStop, immediately after its synthetic-stdin unit probe and standalone test file pass (block case, allow-on-citation, allow-on-tool-ran, no-claim benign, stop_hook_active, fail-open, and a SubagentStop case with NO agent_transcript_path falling back to transcript_path). This is a built-and-tested feature → default ON per the project's 'Built switches default to ON' rule. It changes live session behavior (can block a real turn), so the owed live check before trusting it broadly: run one real session to confirm v2.1.210 populates last_assistant_message on an actual Stop (one-time guarded stderr key-dump), confirm no spurious block on a normal turn, and confirm the decision ledger is landing records.

**C4 is DEFERRED, not built**: it depends on forward-collected data that does not exist yet (C9's live false-fire rate, now captured by the decision ledger). Owed: after ~2 weeks of C9 live, count ledger 'block' records and how many fired on already-evidenced messages; only if false-fire >5% build the Haiku (type:'prompt') escalation branch over the same claim-shaped subset. Naming it as a deliberate deferral per the 'surface deferred features' rule.

## Verification Checklist

1. **C3 populated**: seed notifications.log with the real Schwab line, run `bash /root/.claude/hooks/openclaw-digest.sh`, confirm output shows 'UNVERIFIED as of 2026-07-15 23:00:01 UTC — machine snapshot; probe the primary source before repeating: …' wrapping that line, the red banner + '👉 Summarize…' footer still present, the memory-digest block below unchanged, and the digest still writes no files.

2. **C3 empty-log**: run the digest with an empty notifications.log — the existing `[[ -s "$NOTIF" ]]` guard must skip Block 1 with no tag and no error, and the '=== OpenClaw memory digest ===' block below must print unchanged.

3. **C9 block case**: pipe a synthetic Stop JSON (last_assistant_message='The Schwab login has expired.', transcript_path=a fixture JSONL with NO verification tool_use after the last user turn, cwd=project, stop_hook_active=false) → stdout {"decision":"block",...}, exit 0.

4. **C9 allow-on-tool**: same message but the fixture transcript has a Read/Bash tool_use after the last user turn → empty stdout, exit 0.

5. **C9 allow-on-citation**: message='The login token expired (see schwab_client.py:88).' → empty stdout, exit 0.

6. **C9 allow-on-no-claim (benign)**: message='The market is down 2% today.' → empty stdout, exit 0. And a hedged variant 'If the token expired we would see 401s.' → empty stdout, exit 0.

7. **C9 fail-open**: malformed stdin, and separately a non-project cwd, and stop_hook_active=true → empty stdout, exit 0 each.

8. **SubagentStop path (structural revision)**:
   - (a) Feed a SubagentStop JSON WITH agent_transcript_path pointing at a no-tool fixture + claim-shaped last_assistant_message → block.
   - (b) Feed a SubagentStop JSON WITHOUT agent_transcript_path but WITH transcript_path pointing at a no-tool fixture + claim-shaped message → block (proves fallback to transcript_path).
   - (c) SubagentStop with NEITHER transcript field + claim-shaped message → empty stdout, exit 0 (fail-open). Confirms claim text is read from last_assistant_message regardless of event, and the transcript resolves agent→main→fail-open.

9. **Standalone test file**: run /root/.claude/hooks/tests/test_verify_claim_gate.py (subprocess-driven; cases 3-8 plus one replay against a real current transcript confirming no crash) → all pass.

10. **Decision ledger**: after the above, confirm /root/.claude/hooks/logs/claim-gate-YYYYMMDD.log contains one JSON record per invocation with the documented fields (decision, matched_verb, snippet, tools_this_turn, transcript_source), and that a deliberately unwritable LOG_DIR still yields the correct allow/block (ledger failure is non-load-bearing).

11. **settings.json wiring**: after editing, re-validate with `python3 -m json.tool /root/.claude/settings.json`; confirm both Stop entries (verify-on-done.py + verify-claim-gate.py) and the new SubagentStop key are present.

12. **[always] regression bucket**: `python3 -m pytest tests/ -q` in the repo diffed against .test-baseline shows no new failures (hooks live outside the repo, so none should move); consensus-engine.service and openclaw-gateway.service both active; no ❌ GATEWAY drift; /root/.openclaw still resolves to /home/openclaw/.openclaw.

13. **Live sanity**: start one fresh session, confirm it does NOT hang or spuriously block a normal turn, verify-on-done.py still runs, and a one-time guarded stderr dump confirms last_assistant_message is populated on a real Stop under v2.1.210.

14. **Ownership**: `ls -l` the new/edited files show root:root and verify-claim-gate.py is executable.

15. **Observability sign-off**: after enabling, tail /root/.claude/hooks/logs/claim-gate-*.log across a few real sessions to confirm allow/block records land and eyeball the false-fire rate before any C4 decision.

---

## Feature Probes

### Feature 1: Deterministic Stop-Hook Claim-Shape Gate (C9)

**Kind**: live_probe

**Instruction**: Build the fixtures then run the synthetic-stdin cases (mirrors verify-on-done.py's env-override test pattern; no credentials, no live services).

- (a) BLOCK: `printf '{"last_assistant_message":"The Schwab login has expired.","transcript_path":"/tmp/vcg_notool.jsonl","cwd":"/home/openclaw/.openclaw/workspace","stop_hook_active":false}' | VERIFY_CLAIM_GATE_PROJECT_GIT=/home/openclaw/.openclaw/workspace/.git python3 /root/.claude/hooks/verify-claim-gate.py` where /tmp/vcg_notool.jsonl is a 2-line JSONL: a user message then an assistant message with only a text block (no tool_use).
- (b) ALLOW-tool: same but /tmp/vcg_tool.jsonl adds an assistant tool_use with name 'Read' after the user line.
- (c) ALLOW-cite: last_assistant_message='The login token expired (see schwab_client.py:88).' with the no-tool transcript.
- (d) ALLOW-noclaim: last_assistant_message='The market is down 2% today.' with the no-tool transcript.
- (e) FAIL-OPEN: `printf 'not json' | python3 /root/.claude/hooks/verify-claim-gate.py ; echo exit=$?`
- (f) SUBAGENT-FALLBACK: `printf '{"last_assistant_message":"The auth token has expired.","transcript_path":"/tmp/vcg_notool.jsonl","cwd":"/home/openclaw/.openclaw/workspace","stop_hook_active":false,"agent_id":"x","agent_type":"y"}' | VERIFY_CLAIM_GATE_PROJECT_GIT=/home/openclaw/.openclaw/workspace/.git python3 /root/.claude/hooks/verify-claim-gate.py` — a SubagentStop payload with NO agent_transcript_path must still read the claim from last_assistant_message and fall back to transcript_path.

**Expected evidence**: (a) prints `{"decision":"block","reason":...}` and exit 0; (b),(c),(d) print nothing and exit 0; (e) prints nothing and exit=0; (f) prints `{"decision":"block",...}` and exit 0 (proves last_assistant_message + transcript_path fallback on SubagentStop). A per-invocation JSON record lands in /root/.claude/hooks/logs/claim-gate-YYYYMMDD.log with decision + transcript_source. Confirms the AND-gate blocks only claim-shape+no-verification+no-citation, ignores benign/hedged text, and fails open otherwise.

### Feature 2: Source-Tag the SessionStart Digest (C3)

**Kind**: live_probe

**Instruction**: Ensure /root/task_system/notifications.log contains the real line `[2026-07-15 23:00:01 UTC] ⚠️ Schwab login has EXPIRED ...`, then run: `bash /root/.claude/hooks/openclaw-digest.sh`. Also run once with an empty notifications.log to confirm Block 1 is skipped cleanly. The digest writes no files, so this is non-destructive; restore/clear the log afterward as normal session flow already does.

**Expected evidence**: With the seeded line: stdout shows the Schwab alert emitted under 'UNVERIFIED as of 2026-07-15 23:00:01 UTC — machine snapshot; probe the primary source before repeating:' immediately preceding the alert text, the red banner and '👉 Summarize …' footer still present, and the memory-digest block below unchanged. With an empty log: Block 1 is skipped with no tag and no error and the memory-digest block prints unchanged. Confirms the snapshot arrives labelled without breaking the digest.

### Feature 3: Selective LLM Escalation Fallback (C4)

**Kind**: deferred_probe

**Reason**: forward_data

**Owed check**: C4 has no runtime surface yet by design — it is built only if C9 proves too fragile. C9's per-invocation decision ledger (/root/.claude/hooks/logs/claim-gate-YYYYMMDD.log) is the measurement instrument. After ~2 weeks of C9 live, count 'block' records and how many fired on messages that were actually already evidenced (false-fire). If the false-fire rate exceeds 5%, add a Haiku (type:'prompt') escalation branch inside verify-claim-gate.py that runs ONLY on the claim-shaped subset C9 already isolates; then probe it on the collected false-fire corpus and confirm it reverses those blocks while preserving the true blocks.

---

## Tournament Notes

### Scores Table

| Stance | Score | Summary |
|--------|-------|---------|
| **Minimal-diff** (winner) | 8.7 | Every integration point verified real (digest lines, settings.json Stop array, verify-on-done.py skeleton all present). Reads claim text from Stop-hook stdin field last_assistant_message, which current docs recommend over transcript parsing — core detection path is docs-correct. Completeness 9: all sections, 4 probes, bidirectional subject+verb AND-regex, citation escape, project-scope gate. Risk 7.5: fail-open and 8-block cap covered; decision logging grafted from loser. Fit 9: exactly one new file + two edits, scoped like verify-on-done.py. |
| **Robustness-first** | 8.3 | Best-grounded citations (every line number verified exact); live-verified transcript schema. **Core flaw**: extracts outbound claim text by parsing transcript_path — docs warn that file lags in-memory conversation; with its correct fail-open bias, gate silently allows exactly when the final message hasn't flushed, making the enforcer unreliable at fire time. Completeness 9: logging ledger, standalone test, regression checks. Risk handling 9: four-layer false-fire mitigation. Fit 8.5: unproven global regex to every repo. |

### Grounded Findings

Verified against live system (code.claude.com/docs/en/hooks, files at /root/.claude/):

1. **/root/.claude/hooks/openclaw-digest.sh**: notification block is exactly lines 11-16 with `cat "$NOTIF"` at line 14, `set -euo pipefail` at line 5, memory-digest block at 18-32 — both plans' edit targets are real.

2. **/root/.claude/settings.json**: hooks.Stop at lines 62-72 contains only verify-on-done.py (timeout 240); no SubagentStop key exists — both plans' wiring claims accurate; Plan B's cited line range exact.

3. **/root/.claude/hooks/verify-on-done.py** is 249 lines; allow()/block() writing `{"decision":"block","reason":...}`+exit 0 at ~:49-57, stop_hook_active guard at ~:134, VERIFY_ON_DONE_ACTIVE sentinel, DEFAULT_PROJECT_GIT="/home/openclaw/.openclaw/workspace/.git" with env override, git_common_dir gate, absolute fail-open try/except at :244-249 — every skeleton idiom both plans reuse is real.

4. **/root/task_system/notifications.log**: live file, owner openclaw:openclaw -rw-rw-r--, lines match `[YYYY-MM-DD HH:MM:SS UTC] ⚠️ Schwab login has EXPIRED ...` — the exact incident line both probes use.

5. **/root/.claude/hooks/logs** exists, root-owned drwxr-xr-x.

6. **claude --version** = 2.1.211 (Plan B correct; task intro said 2.1.210).

7. **Current hooks docs** (code.claude.com/docs/en/hooks, fetched live): Stop AND SubagentStop stdin both include last_assistant_message; docs explicitly say hooks needing the final assistant text should use it INSTEAD of reading the transcript because the transcript file is written asynchronously and may lag; `decision:"block"`+reason on exit 0 confirmed; SubagentStop adds agent_id/agent_type. This validates Plan A's core mechanism and exposes Plan B's transcript-parse of outbound text as the doc-discouraged path.

### Graft Decisions (Robustness-first → Minimal-diff winner)

1. **Decision logging ledger** (Failure Handling): Append one JSON decision record per invocation to /root/.claude/hooks/logs/claim-gate-YYYYMMDD.log — {ts, event, decision, matched verb, snippet≤120 chars, tools_this_turn} — with the log write wrapped in its own try/except so a write failure never changes the decision. This ledger is the only way the C4 go/no-go (false-fire >5%) can be measured rather than guessed.

2. **Standalone test file** (tests section): Add /root/.claude/hooks/tests/test_verify_claim_gate.py driving the hook via subprocess with synthetic fixtures: block case, escaped-by-tool, escaped-by-citation, no-claim benign text ('the market is down 2% today'), stop_hook_active=true, malformed transcript — plus one replay against a real current transcript confirming no crash.

3. **Negative lookarounds** (risk-callouts): Exclude hedged/conditional clauses (if/would/might/in case/not/n't in the same clause) from CLAIM_RE so 'if the token expired…' and 'the login has NOT expired' don't fire.

4. **Two-Stop-hooks coexistence** (risk-callouts): Both honor stop_hook_active so at most one block round total; if both would block the same stop Claude Code surfaces both reasons — keep the claim-gate reason to one line to avoid a wall of text.

5. **settings.json re-validation** (Verification Checklist): After editing, re-validate with `python3 -m json.tool /root/.claude/settings.json` and confirm both Stop entries plus the SubagentStop key are present.

6. **Empty-log case** (Verification Checklist): Run the digest with an empty notifications.log — the existing `[[ -s "$NOTIF" ]]` guard must skip the block with no tag and no error, and the '=== OpenClaw memory digest ===' block below must print unchanged.

7. **Regression-gate bucket** (Verification Checklist): Run `python3 -m pytest tests/ -q` diffed against .test-baseline after install (hooks live outside the repo, so none should move); consensus-engine.service and openclaw-gateway.service both active; no GATEWAY drift.

8. **Observability sign-off** (Verification Checklist): After enabling, tail /root/.claude/hooks/logs/claim-gate-*.log across a few real sessions to confirm allow/block records land and eyeball the false-fire rate before any C4 decision.

### Structural Revision (SubagentStop handling)

Do not assume an agent_transcript_path stdin field (current docs confirmed agent_id/agent_type/last_assistant_message but NOT that field): read the claim text from last_assistant_message always, and for the verification-this-turn walk use agent_transcript_path only if present, else transcript_path, else fail-open allow.

### Losing Plan One-Liners

- **Robustness-first** (8.3): Extracts outbound claim from transcript_path (the async-lag path the docs warn against), risking false-allows when the message hasn't flushed yet.
