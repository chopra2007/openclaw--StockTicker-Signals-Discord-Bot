# Research Findings — Verify-Default Gate (#77)

**Date:** 2026-07-15  
**Status:** RESEARCH COMPLETE  
**Scope:** Claude Code hook capabilities (v2.1.210), notification log format, feasibility of candidate directions

---

## 1. Hook System Capabilities (VERIFIED)

### Available Hook Events
The Claude Code hook system (v2.1.210) supports the following events:

| Event | Timing | Can Block? | Can Inject Context? |
|-------|--------|-----------|-------------------|
| `SessionStart` | Session begins/resumes | No | Yes (`additionalContext`) |
| `UserPromptSubmit` | Before Claude processes prompt | Yes | No |
| `PreToolUse` | Before tool executes | Yes (via `permissionDecision`) | No |
| `PostToolUse` | After tool succeeds | No (action done) | No (replace output only) |
| `Stop` | Claude finishes response | Yes | No |
| `FileChanged` | Watched file changes | No | No |
| `SessionEnd` | Session terminates | No | No |
| `StopFailure` | API error during Stop | No | No |
| `PermissionRequest` | Permission decision needed | Yes | No |
| `UserPromptExpansion` | Prompt expansion | Yes | No |
| `MessageDisplay` | (Mentioned in limits) | Unknown | Unknown |
| `SubagentStop` | Subagent finishes | Yes | No |

**Source:** `https://code.claude.com/docs/en/hooks.md` and `https://code.claude.com/docs/en/hooks-guide.md` (official Claude Code documentation)

### JSON I/O Contract

**Command hooks receive:** JSON on stdin containing:
- `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`
- Plus event-specific fields (tool_name, tool_input, etc.)

**Command hooks return:** JSON on stdout (exit 0) or stderr (exit 2):
```json
{
  "decision": "block",
  "reason": "Explanation text",
  "suppressOutput": false,
  "systemMessage": "Warning to user",
  "additionalContext": "Injected text"
}
```

**Exit codes:**
- `0` = Success; JSON stdout is parsed
- `2` = Blocking error; stderr feedback blocks the action
- Other = Non-blocking error; execution continues

**Key limitation:** "Text returned via `additionalContext` is injected as a system reminder that Claude reads as plain text." (Hooks Guide, Limitations section)

### Stop Hook Behavior (CRITICAL FOR #77)

- Fires **after Claude finishes composing a response** but **before the response is sent to the user**
- Can block with `{"decision": "block", "reason": "..."}` to prevent the response from being sent
- **Can access full transcript** via `transcript_path` to inspect recent messages
- Receive `stop_hook_active` field to detect re-blocking (cap at 8 consecutive blocks)
- Timeout: 600 seconds default (10 minutes)

**Implication:** A Stop hook CAN examine Claude's composed message for unverified claims and block it before sending.

### SessionStart Context Injection (CRITICAL FOR #77)

- Fires at session start/resume
- Returns `additionalContext` field which is injected as a **system reminder** into the session
- Text is read by Claude as plain context
- Guaranteed to be in every session's context at the start

**Implication:** SessionStart can tag notification lines with "UNVERIFIED as of <time>" labels before Claude sees them, making the verification requirement visible at input time.

---

## 2. Current Notification Log (VERIFIED)

**File:** `/root/task_system/notifications.log`  
**Current size:** 157 bytes (not empty at time of research)  
**Current content (sampled 2026-07-15):**
```
[2026-07-15 23:00:01 UTC] ⚠️ Schwab login has EXPIRED — the real-time options feed is on the free ~15-min Yahoo fallback right now until you re-login.
```

**Format:** Plain text, one entry per line, timestamp in [YYYY-MM-DD HH:MM:SS UTC] format.

**Entry structure:**
- Timestamp in UTC
- Emoji indicator (⚠️)
- Free-text status message

**Observations:**
- No "UNVERIFIED" prefix present
- No source field
- No structured markers (plain text only)
- Timestamp uses UTC, not PDT (but that's internal)

**Gap:** Cannot verify how entries are created (write mechanism not inspected — would require tracing the task system code). Assumed to be from `/root/task_system/` scripts based on file path and CLAUDE.md reference.

---

## 3. Existing Working Precedent (VERIFIED)

**File:** `/root/.claude/hooks/verify-on-done.py`  
**Status:** LIVE (#69, SHIPPED)  
**Hook event:** `Stop`  
**Behavior:**
- Fires when agent claims "done"
- Reads `.test-baseline` to get known-failing tests
- Re-runs affected tests (determined by file-change heuristic)
- Blocks with `{"decision": "block", "reason": "..."}` if regressions found
- **Fails open:** any internal error exits 0 (allows stop)
- **Fast path:** ~milliseconds if no code change detected (lines 170–171)

**Key lesson:** A narrow, deterministic Stop hook that fires only on a specific trigger (code change + test failure) can block outbound action without bloating the session or adding standing cost.

---

## 4. Feasibility of Candidate Directions

### Candidate (a) — Deterministic Claim-Shape Gate (NEW STOP HOOK)

**How it would work:**
1. New Stop hook that fires on EVERY stop (already happens)
2. Hook reads `transcript_path` to load the conversation JSON
3. Examines Claude's last message for claim patterns: "X expired", "X is down", "X failed", "X is [status]"
4. Checks recent turn's tool calls for matching verification tool-calls (Read, Bash with probe command, etc.)
5. If pattern found + no matching verification → blocks with reason "Verify before stating"

**Blockers:**
- **Fragility:** Detecting claim shapes from message text requires careful regex/NLP. False-positives likely (e.g., hypothetical: "if Schwab expired..."). High risk of blocking legitimate hedged statements or quoted text.
- **Every-turn cost:** Runs on every stop, not just problem turns. Adds latency to all sessions. (The existing verify-on-done.py mitigates this with fast-path exit, but still requires file I/O and subprocess call.)

**Verdict:** FEASIBLE but RISKY. Would need extensive testing on false-positives. Adds latency to every session.

### Candidate (b) — Source-Tag Startup Alerts (REWRITE SESSIONSTART DIGEST)

**How it would work:**
1. Rewrite `/root/.claude/hooks/openclaw-digest.sh` to tag each notification line with "UNVERIFIED as of <time> — probe before repeating"
2. SessionStart hook already runs and injects context
3. Notification lines now arrive with a verification reminder built in
4. Claude sees "⚠️ Schwab login has EXPIRED — the real-time options feed is on the free ~15-min Yahoo fallback" **PLUS** injected label "UNVERIFIED as of 2026-07-15 23:00:01 UTC — probe before repeating"
5. Verification reminder is part of the input, not a separate rule

**Blockers:**
- **None identified.** Requires only rewriting 33-line bash script. SessionStart can inject `additionalContext`. Notification log has clear structure.
- **Side benefit:** Works on the exact real-world incidents from #77 (Schwab login banner). Narrow, not general.

**Verification gap:** Have not inspected the code path that WRITES to notifications.log to confirm it can't already carry a timestamp-only label. (Assumed it can't based on observed format.) 

**Verdict:** MOST FEASIBLE. Zero standing context cost. Targets the most common real failure (startup alerts). Requires no new hook event. Low risk of false-positives.

### Candidate (c) — Sub-Agent Rule Propagation

**How it would work:**
1. When spawning a sub-agent (TaskCreate, agent config in `openclaw.json`), inject verification rules into the agent's system prompt
2. The spawned agent reads the rule and applies it to its own conclusions
3. Parent agent then receives findings that are already self-verified

**Blockers:**
- **Scope unknown:** How agent prompts are assembled, where rule injection point exists, whether injecting into every agent bloats or slows spawning
- **Not inspected:** `/root/.openclaw/openclaw.json` (agent config), task creation code paths
- **Complexity:** Requires changes to agent spawning and prompt assembly, not just hook config

**Verdict:** FEASIBLE but REQUIRES DEEPER INSPECTION. Addresses second gap from #40 (rules don't carry into sub-agents). Broader scope than (a) or (b). Likely higher complexity and context cost if done naively.

---

## 5. Constraints Check (HARD CONSTRAINTS)

**Constraint 1:** "Must gate behavior at decision time, not just add knowledge"
- Candidate (a): ✅ Blocks message via Stop hook
- Candidate (b): ✅ Tags input so verification is visible at read time
- Candidate (c): ✅ Injects rule into agent so it's applied before delegation

**Constraint 2:** "Must NOT bloat context or slow sessions"
- Candidate (a): ⚠️ Runs on every stop; adds latency to all sessions
- Candidate (b): ✅ SessionStart runs once per session; one-time context injection; no per-turn cost
- Candidate (c): ⚠️ Requires injecting text into sub-agent prompts; scales with team size

---

## 6. Evidence Standards (VERIFIED)

All findings sourced from:
1. **Official Claude Code documentation** (code.claude.com/docs)
   - `/en/hooks-guide.md` — guide with examples
   - `/en/hooks.md` — complete reference (58KB)
2. **Live system inspection**
   - `/root/.claude/settings.json` — hook wiring (verified 4 hooks wired: SessionStart, Stop, PreToolUse, UserPromptSubmit)
   - `/root/.claude/hooks/verify-on-done.py` — 250-line working precedent (examined for error handling, fast path)
   - `/root/.claude/hooks/openclaw-digest.sh` — 33-line SessionStart hook (examined for structure)
   - `/root/task_system/notifications.log` — actual notification entry (157 bytes, sampled)
3. **Project documentation**
   - `todo/verify-default-not-firing.md` — problem statement and candidate directions
   - CLAUDE.md "Verification ladder" — the passive rule this aims to mechanize

---

## 7. Recommendation (NOT DECIDED BY THIS RESEARCH)

Based on feasibility, risk, and constraints:

**Candidate (b) is the lowest-friction, narrowest first win.**

- Targets the exact failure mode from #77 (SessionStart digest → Schwab alert)
- Single bash script rewrite (33 lines → ~40 lines)
- Zero standing context cost
- Highest confidence of success
- No new hooks needed; uses existing SessionStart event
- Natural escalation path if more general gate still needed

**For a future opus/ultracode session:** build (b) first, then if needed, add (a) as a general complement, and research (c) for sub-agent coverage.

---

## 8. Inspection Gaps (Known Unknowns)

These would be needed before implementation:

1. **Exact write mechanism for notifications.log** — what creates entries, on what schedule, can it be modified at write time
2. **MessageDisplay hook** — mentioned in limitations but not fully documented in fetched pages; might be relevant for candidate (a)
3. **Agent spawning code** — `/root/.openclaw/openclaw.json` not inspected; needed for candidate (c)
4. **Transcript JSON structure** — exact format for Stop hook to parse recent messages (needed for candidate a)
5. **SessionStart additionalContext flow** — verify that text injected via additionalContext is visible to Claude before processing notifications.log

---

## Summary Table

| Candidate | Feasibility | Context Cost | Risk | Complexity | Real-World Impact |
|-----------|------------|--------------|------|-----------|------------------|
| (a) Claim-shape gate | Medium | High (every turn) | High (false-pos) | High | Broad (all claims) |
| (b) Tag alerts | High | Zero | Low | Low | Narrow (startup) |
| (c) Sub-agent rules | Medium | Medium (per agent) | Medium | High | Moderate (agents) |

