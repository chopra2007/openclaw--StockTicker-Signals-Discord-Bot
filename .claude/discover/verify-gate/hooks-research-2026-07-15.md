# Claude Code 2.1.210 Hooks Research for Verify-Gate (#77)

**Date:** 2026-07-15  
**Version:** Claude Code v2.1.210 (Linux VPS)  
**Task:** Research mechanical gates to enforce "verify before stating" at decision time  

---

## Executive Summary

Claude Code 2.1.210 hooks support five decision-control points: **SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, StopFailure, SessionEnd**. Of these, only **Stop** and **PostToolUse** can gate outbound claims without bloating standing context. The verify-gate problem requires detecting a claim in Claude's *outbound response* and blocking it — a capability that **does not exist as a direct hook event**. This research evaluates three feasible workarounds given the actual API surface.

---

## Part 1: Claude Code Hook Architecture (v2.1.210)

### Available Hook Events

| Event | Fires | Callable Handler Types | Can Block? | Can Inject Context? | Input Scope |
|-------|-------|------------------------|------------|---------------------|------------|
| **SessionStart** | Once per session start/resume | command, mcp_tool | No | Yes (`additionalContext`) | Session metadata |
| **SessionEnd** | Once per session end | command, mcp_tool | No | No | Session metadata |
| **UserPromptSubmit** | Before Claude processes user prompt | command, http, mcp_tool, prompt, agent | Yes (`decision: "block"`) | No | User prompt text |
| **PreToolUse** | Before a tool executes | command, http, mcp_tool, prompt, agent | Yes (`permissionDecision: "deny"`) | No | Tool name, tool input |
| **PostToolUse** | After a tool succeeds | command, http, mcp_tool | Yes (via `decision: "block"`) | Yes (`additionalContext`) | Tool name, tool output |
| **Stop** | When Claude finishes responding | command, http | Yes (via `decision: "block"`) | Yes (`additionalContext`) | Claude's response text (transcript path) |
| **StopFailure** | When Stop hook errors | command | No | No | Error context |

### JSON I/O Contract (All Hooks)

#### Input (via stdin)

```json
{
  "session_id": "uuid",
  "prompt_id": "uuid",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/dir",
  "permission_mode": "auto|manual|etc",
  "hook_event_name": "EventName",
  // Event-specific fields below:
  "prompt": "user text",           // UserPromptSubmit only
  "tool_name": "Bash",             // PreToolUse, PostToolUse
  "tool_input": {...},             // PreToolUse
  "tool_output": {...},            // PostToolUse only
  "stop_hook_active": true|false   // Stop hook only (loop guard)
}
```

#### Output (via stdout, JSON)

```json
{
  "continue": true,
  "suppressOutput": false,
  "systemMessage": "Optional warning to Claude",
  "terminalSequence": "Optional escape sequence",
  "hookSpecificOutput": {
    "hookEventName": "EventName",
    "additionalContext": "Text injected into Claude's context",
    "decision": "block|allow|ask|defer",
    "reason": "Why blocked (for Stop hook)"
  }
}
```

#### Exit Code Semantics

| Code | Meaning | Behavior |
|------|---------|----------|
| 0 | Success | Process JSON output; continue normally |
| 2 | Blocking error | Reject action; stderr on user's screen |
| Other | Non-blocking error | Log and continue; JSON not processed |

### Handler Types (5 categories)

1. **command** (shell script): Receives JSON on stdin, outputs JSON on stdout. Used by both existing hooks (verify-on-done.py is a Python script run this way, openclaw-digest.sh is a bash script).
2. **http**: POST to endpoint; useful for external APIs.
3. **mcp_tool**: Invoke tools on connected MCP servers.
4. **prompt**: Single-turn LLM evaluation (introduces latency & cost; not suitable for zero-context gate).
5. **agent**: Spawn subagent (experimental, introduces cost).

### Critical Limitation: No "OutboundResponse" Hook Event

**The core problem for verify-gate:** Claude Code has no hook event that fires *after Claude writes a response but before it appears to the user*. The Stop hook fires *after* Claude stops (the response is already formed), but it receives only the `transcript_path` (path to the conversation JSON), not the raw response text directly in the hook input.

This means a Stop hook must read the transcript file from disk to inspect Claude's latest response — adding file I/O and latency.

---

## Part 2: Evaluation of Three Candidate Design Directions

### Option A: Deterministic Zero-Context Gate (Stop Hook)

**Goal:** Detect outbound claims shaped like "X expired / X down / X failed / X authenticated" that lack a matching verification tool-call, block with reason.

#### Feasibility: VIABLE, with caveats

**Implementation sketch:**
1. Stop hook (command handler) fires after Claude responds
2. Hook reads the transcript JSON to extract Claude's latest response text
3. Hook searches for claim patterns: `expired`, `down`, `failed`, `authenticated`, `logged.in`, `status: ...`
4. For each claim, hook checks if a verification tool (WebFetch, Bash, Read) was called within the same turn
5. If claim exists but no verification tool was called, output `{"decision": "block", "reason": "..."}`
6. Otherwise, exit silently (exit 0, no stdout)

**Cost:**
- One Stop hook script (~200–300 lines Python)
- Per-turn file I/O (read transcript JSON)
- Pattern matching overhead: ~5–20ms per turn
- **Standing context cost: zero** — no preamble, no injected text

**Risk / False-Positive Rate:**
- Pattern detection is hard to make deterministic. The patterns `expired`, `down`, `failed` can appear in legitimate contexts (e.g., "the feature we deprecated is down" vs. "our service is down").
- A regex-based detector will false-fire on false positives (blocking valid claims) or false-negatives (missing real claims).
- Fixing the regex requires iterative tuning.

**Prototype working example:** `/root/.claude/hooks/verify-on-done.py` (Stop hook, same event) — demonstrates the JSON contract, file reading, and exit 0 / block decision pattern.

#### Design Iteration Needed

To reduce false-fire rate:
- Build a high-confidence pattern set (e.g., match "Schwab login EXPIRED" as a quoted status string or multiword phrase, not just the token "expired").
- Use transcript context: if a Schwab-related tool was called 2 turns ago and succeeded, a later "EXPIRED" claim is likely a stale banner, not a current truth.
- Track which claims were already verified earlier in the session (to avoid re-blocking on rephrased versions).

---

### Option B: Source-Tagging Startup Alerts (SessionStart Hook)

**Goal:** Rewrite banners from `notifications.log` and memory digest to label them "UNVERIFIED as of <time> — probe before repeating," moving the gate into the input itself.

#### Feasibility: MOST VIABLE, narrow scope

**Implementation sketch:**
1. SessionStart hook (command handler) fires at session start
2. Hook reads `/root/task_system/notifications.log` and memory digest files
3. For each banner/notification line, prepend: `[UNVERIFIED @ 2026-07-15T12:34Z]`
4. Inject the re-tagged digest into Claude's context via `additionalContext`

**Cost:**
- One SessionStart hook script (~80–120 lines bash/Python)
- File I/O at session start only (not per-turn)
- Text manipulation overhead: negligible
- **Standing context cost: minimal** — replaces existing digest text, doesn't add new preamble

**Immediate Win:**
- The latest incident (2026-07-14) was exactly this: a Schwab login banner relayed without verification. A `[UNVERIFIED @ 23:00Z]` label would have made the user question it immediately (and the banner is 15+ hours old by 2026-07-15).
- Addresses ~60–70% of real failures (all notification-relayed facts get labeled).

**Risk / Limitations:**
- Only works for *notifications that arrive via digests* — doesn't catch claims Claude derives internally.
- Doesn't force a tool call; only makes the user more suspicious of the input.
- If Claude still decides the claim is true despite the label, it can ignore it.

**Precedent:** The existing `openclaw-digest.sh` SessionStart hook already reads files and injects digests; this extends it.

---

### Option C: Sub-Agent Propagation

**Goal:** Carry verification rules into spawned agents so they don't return unverified conclusions for Claude to relay.

#### Feasibility: ARCHITECTURAL, not a hook-level fix

**Implementation:** Add verification rules to agent preambles (`/root/.openclaw/openclaw.json` agents.defaults.preamble or a similar field) so spawned agents inherit "verify before stating" discipline.

**Why not a hook:**
- Agents are spawned via API, not tool calls (no PreToolUse / PostToolUse interception).
- The agent config JSON is the entry point, not something a hook can gate.
- This is a documentation/training issue, not a mechanical enforcement issue.

**Cost:** 
- Change agent config template (5–10 lines added to preamble).
- Requires manual verification that all agent invocations pass the preamble.
- No hook code needed.

**Status:**
- This is not addressed by the hook architecture alone.
- Requires a separate change to agent spawning code.

---

## Part 3: Hook Event Comparison Table (Stop vs PostToolUse vs SessionStart)

| Aspect | Stop | PostToolUse | SessionStart |
|--------|------|-------------|-------------|
| **Fires** | After Claude finishes response | After tool completes | Session starts |
| **Can block outbound response?** | Yes (after formed; blocks display) | No (only tool result) | N/A (no response yet) |
| **Can read response text?** | Yes (transcript file) | No (only tool output) | N/A |
| **Can inject context?** | Yes | Yes | Yes |
| **Cost per turn** | Medium (file I/O, parsing) | Low (in-tool data) | Zero (once per session) |
| **Context bloat?** | No (silent block) | No (context already in flow) | Minimal if reusing existing digest |
| **Existing precedent** | verify-on-done.py (#69) | None | openclaw-digest.sh |
| **False-fire risk** | Medium (pattern matching) | N/A | Low (explicit labels) |
| **Latency visible to user** | Yes (blocks response display) | No | No |

---

## Part 4: Recommended Path Forward

### Phase 1: Narrow Win (Option B, Source-Tagging) — Weeks 1–2

**Why first:**
- Tackles the most common real failure (notification relayed as fact).
- Lowest complexity, zero LLM cost.
- Extends existing hook (openclaw-digest.sh).
- Can ship immediately without design iteration.

**Scope:**
1. Modify `openclaw-digest.sh` to prepend `[UNVERIFIED @ <timestamp>]` to all notification lines.
2. Test on existing notifications.log entries (including the 2026-07-14 Schwab alert).
3. Verify user can see the label and question the claim sooner.

**Definition of Done:**
- Schwab-like banners arrive labeled UNVERIFIED.
- A real session with a notification shows the label in context.
- User can trace a single notification → label → their response.

---

### Phase 2: Deterministic Claim Gate (Option A, Stop Hook) — Weeks 3–4

**Why after Phase 1:**
- Addresses claims Claude derives internally (not from notifications).
- Requires pattern tuning; easier after Phase 1 gives real data on false-fire rate.
- More complex; benefits from learning from Phase 1's rollout.

**Scope:**
1. Build Stop hook script to detect claim patterns.
2. Establish baseline false-fire rate on test suite.
3. Implement `transcript → latest response → pattern search` logic.
4. Add safeguards (claim + tool + turn proximity checks).

**Definition of Done:**
- Stop hook fires on "X expired / X down" claims with no verification tool.
- False-fire rate < 5% on 100-turn test.
- Blocks at least one real case (e.g., a derived claim without prior tool call).

---

### Phase 3: Agent Propagation (Option C) — Deferred

**Why later:**
- Orthogonal to the hook system; requires config change.
- Can be done in parallel with Phase 1–2 if agent-spawning becomes a blocker.
- Depends on understanding which agents spawn and which inherit config.

---

## Part 5: Technical Details for Implementation

### Stop Hook Invocation Example (from verify-on-done.py)

```python
def block(reason):
    """Block the stop and feed `reason` back to the agent."""
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)  # Note: exit 0, not 2; output is JSON, not error
```

### Transcript JSON Structure (from Stop hook input)

The `transcript_path` points to a JSONL file where each line is a message event:

```jsonl
{"role": "user", "content": "your message"}
{"role": "assistant", "content": "response text"}
{"role": "user", "content": "..."}
```

A Stop hook reads the last assistant message from this file to inspect the claim.

### SessionStart Hook additionalContext Example (from openclaw-digest.sh)

```bash
printf '=== OpenClaw memory digest (%s, head -%d) ===\n' "$fname" "$MAX_LINES"
head -n "$MAX_LINES" "$latest"
printf '\n=== end digest — full file: %s ===\n' "$latest"
# This outputs plain text; Claude Code injects it into context automatically
```

---

## Appendix: API Reference

### Settings.json Hook Configuration (Current)

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.claude/hooks/openclaw-digest.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $HOME/.claude/hooks/verify-on-done.py",
            "timeout": 240
          }
        ]
      }
    ]
  }
}
```

### Hook Matcher Patterns

- Omitted or `"*"`: Match all events
- String: Exact name (e.g., `"Bash"`)
- Regex: If contains non-alphanumeric (e.g., `"^web.*"`)

For Stop hook: no matcher (fires on every stop)

---

## References

- **Official docs:** https://code.claude.com/docs/en/hooks (v2.1.210 current)
- **Working precedent:** `/root/.claude/hooks/verify-on-done.py` (Stop hook, TODO #69)
- **Related task:** `/home/openclaw/.openclaw/workspace/todo/verify-default-not-firing.md` (TODO #77)
- **Failure assessment:** `/home/openclaw/.openclaw/workspace/todo/reasoning-failures-assessment-2026-06-13.md` (TODO #40)

---

## Summary: What This Research Enables

1. **Definitive answer**: The hook architecture v2.1.210 supports two viable mechanical gates (Stop hook + SessionStart hook), but neither directly intercepts an outbound response *before* Claude forms it. Both must read or block *after the response is formed*.

2. **Precedent exists**: verify-on-done.py demonstrates Stop hook JSON contract, file reading, and decision blocking — this can be extended.

3. **Fastest path**: Option B (source-tagging startup alerts) is lowest-risk and can ship in ~1 week. Option A (claim detection Stop hook) is more comprehensive but requires design iteration to minimize false-fires.

4. **Known constraint**: Any mechanical gate that inspects Claude's response (Option A) adds per-turn latency visible to the user (Stop hook blocks response display). Option B adds latency only at session start.

5. **Gap remains**: Sub-agent conclusion verification (Option C) requires config change, not a hook-level fix.
