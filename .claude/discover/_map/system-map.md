# Pass 0: System Map — Verify-Default Feature

**Purpose:** Inventory what exists, what's missing, and what needs research before building a mechanical gate for the "verify before stating" rule (TODO #77).

**Scope:** The Claude Code hook system, startup digest, passive rules, and the diagnosis that led to this ticket.

---

## Component Inventory

### Working Precedent

**verify-on-done.py** (`/root/.claude/hooks/verify-on-done.py`)  
A gated Stop hook (250 lines) that re-runs affected tests when code changes are left uncommitted at session end. Proof-of-concept for mechanical enforcement at decision time (Stop event). Key behaviors:
- Fast-path exit (milliseconds) if no code change exists (lines 170–171)
- Maps changed files to test files via filename-token match, with grep fallback (lines 95–120)
- Diffs test results against `.test-baseline` to detect regressions (line 212)
- Blocks the stop with `{"decision": "block", "reason": "..."}` JSON on stdout if a regression is found (line 56)
- Fails OPEN (exits cleanly) on any internal error or timeout (lines 204–209, 246–249)
- Zero standing context on the common path; reason text only appears when blocking

**Lesson:** A narrow, deterministic gate that fires only on a specific trigger (code change + test failure) can block an outbound action without bloating the session or adding standing cost. This is the ONLY working precedent for mechanical enforcement on this project.

---

### Startup Digest (SessionStart Hook)

**openclaw-digest.sh** (`/root/.claude/hooks/openclaw-digest.sh`)  
33-line SessionStart hook that runs every session. Two blocks:

1. **Block 1 — Notifications alert (lines 11–16):** If `/root/task_system/notifications.log` is non-empty, prints a banner "🚨🚨 UNRESOLVED GATE / CI / PUSH ALERTS — N line(s)" and cats the log verbatim, followed by a footer asking Claude to summarize and clear the file.
   - **Current issue:** The banner frames entries as action items to resolve, but does NOT tag each line as "UNVERIFIED as of <time> — probe before repeating." A raw status string (e.g., "Schwab login EXPIRED") flows into Claude's context as trustworthy, and Claude may relay it in a completion summary without checking the primary source (the actual 2026-07-14 incident that triggered #77).
   - **Notifications log state:** Exists at `/root/task_system/notifications.log`, currently 0 bytes (empty).

2. **Block 2 — Memory digest (lines 18–32):** Finds the newest dated memory file from `/root/.openclaw/workspace/memory/` and prints the first 60 lines, with a footer pointing to the full file path.
   - **Note:** This is memory storage outside the repo (different from `/root/.claude/projects/.../MEMORY.md` which is the auto-memory index loaded at session start).

---

### Hook Wiring

**settings.json** (`/root/.claude/settings.json`)  
Registers exactly 4 hook events:
- `PreToolUse` (matcher: 'Skill' → omc-hud.mjs)
- `UserPromptSubmit` (omc-hud.mjs)
- `SessionStart` (openclaw-digest.sh)
- `Stop` (verify-on-done.py, timeout 240 seconds)

**Key finding:** Only TWO events can gate outbound behavior — SessionStart (runs before context loads) and Stop (runs when "done" is pressed). No PostToolUse hook exists. For mid-message claim detection (candidate a), a new hook event or a Stop-based gate would be needed.

---

### Passive Rules

**CLAUDE.md — Verification ladder (lines 24–30)**  
A prose rule block: "Already loaded? / Smallest probe first / Parallel for breadth / Never describe behavior from memory." Present in system-prompt context at every session start. It *informs* but does not *interrupt* at the moment a claim is produced — depends on in-the-moment recall under load. This is the exact pattern #40 identified as failed.

**comm-check.md — Reactive grading rubric (~250 lines)**  
Section 3 ("Verify, don't assume") documents what verification should look like (line 64). But comm-check is ONLY read **after** user pushback or at session close (per CLAUDE.md line 62–64) — it grades failures post-hoc, never pre-hoc. Inherently reactive; cannot gate a mid-session claim.

**MEMORY.md — Auto-memory index**  
Present in system-prompt context. Records repeated incidents of trusting status strings instead of probing primary sources (comm-check §3 failures on 07-12, 07-14, and others). Memory entries inform but do not interrupt.

---

### Diagnosis Document

**todo/reasoning-failures-assessment-2026-06-13.md** (Status: DONE)  
Closed diagnostic-only record from 06-13. Names the core problem: "I reliably possess the relevant rule or fact, but do not apply it at the moment I produce an answer." Identifies two unaddressed mechanical gaps:
1. Passive CLAUDE.md/comm-check rules do not interrupt at decision time.
2. Rules do not auto-propagate to spawned sub-agents.

Explicitly defers: "If the user later wants these enforced mechanically (a hook / a sub-agent preamble injector), open a new build item" — which is #77.

---

### Build Ticket

**todo/verify-default-not-firing.md** (Status: OPEN)  
71-line open ticket created 2026-07-14. Restates the problem: Claude relayed a SessionStart "Schwab login EXPIRED" banner as fact without checking. Three candidate directions (open, not decided):

1. **Deterministic zero-context gate (candidate a):** A hook that detects outbound claims shaped like "X expired / down / failed / logged-in / authenticated" with no matching verification tool-call in the turn, and blocks just that message. Risk: claim-shape detection from text may false-fire.

2. **Source-tagging startup alerts (candidate b):** Rewrite the digest so notification lines arrive labelled "UNVERIFIED as of <time> — probe before repeating." Turns the input itself into the gate. Narrow; cheap; targets the most common real incidents.

3. **Sub-agent propagation (candidate c):** Carry verification rules into spawned agents so delegated verdicts are not relayed unchecked. Addresses the second unaddressed gap from #40.

Hard constraints: (1) must gate at decision time; (2) must NOT bloat context or slow sessions.

---

## Data Sources (Read)

- `/root/.claude/hooks/verify-on-done.py` — full 250 lines
- `/root/.claude/hooks/openclaw-digest.sh` — full 33 lines
- `/root/.claude/settings.json` — full 147 lines
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/todo/verify-default-not-firing.md` — full 71 lines
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/todo/reasoning-failures-assessment-2026-06-13.md` — full 48 lines
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/CLAUDE.md` — lines 1–186 (full file includes jargon table, timezone rule, communication discipline, behavior directives, TODO/close triggers, definition of done, regression gate, alert philosophy, commands, design decisions, deferred task system, GitHub automation)
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/comm-check.md` — lines 1–252 (6 sections with prompts and gold answers; Section 3 covers verification, line 64)
- `/root/.claude/settings.json` — full 147 lines
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/.githooks/pre-commit` — full 37 lines
- `/home/openclaw/.openclaw/workspace/.claude/worktrees/todo-77-verify-default/.claude/settings.local.json` — full 89 lines (worktree permissions only)

File listings: `/root/task_system/notifications.log` (0 bytes, empty), `/home/openclaw/.openclaw/workspace/.claude/discover/verify-gate/` directory structure confirmed.

---

## Gaps (Truly Absent)

### Claude Code Hook Capabilities — Not Verified

The installed version is Claude Code v2.1.210. The `settings.json` wiring shows 4 hooks in use, but the full available event set, JSON I/O contract, `"decision": "block"` semantics, `additionalContext` injection capability, exit-code behavior, and whether any event fires on *outbound* assistant message content (not just user input or tool results) are **not documented in any file in this repo.**

**Why this matters:** Candidate (a) needs a hook that can intercept an assistant message before it's sent; candidate (b) needs to know if SessionStart can inject additional context that flows through the turn. Research must check Claude Code v2.1.210's official hook documentation (not inferred from settings.json alone).

### Sample Notification Log Entry

No live sample of `/root/task_system/notifications.log` content inspected. Candidate (b) needs to know:
- Do entries already carry a timestamp or source field?
- What format do they have (plain text, JSON, structured)?
- Can the digest inject a "UNVERIFIED as of <time>" tag per entry, or must it synthesize the time from file mtime?

Currently the log is empty (0 bytes), so samples must come from history or from triggering the notification system.

### Sub-Agent Propagation Mechanism

How Task/subagent prompts are assembled (via TaskCreate, agent config in `openclaw.json`, spawn parameters) and whether a rule-injection point exists for candidate (c) is unknown. Requires reading:
- `/root/.openclaw/openclaw.json` (agent configuration)
- Task creation and invocation code paths
- How parent-to-child prompt inheritance works in Claude Code

### Git History Context

The pre-commit hook (`/.githooks/pre-commit`) is present and gates LLM model sync, but no other git hooks (e.g., pre-push) are in this worktree. The `CLAUDE.md` references `scripts/pre-push` at the main checkout level; whether it exists and what it does is not verified here.

---

## Unverified (Believed But Not Re-Read by This Pass)

1. **verify-on-done.py fail-open behavior:** Mapper-1 reports lines 204–209 and 246–249 catch all exceptions and exit 0 (fail-open). I read the file and see try/except blocks wrapping main() and the subprocess call, but did not line-anchor the exact exception handling to confirm the exit 0 flow on error.

2. **Schwab token freshness claim in #77:** The ticket states the token was "21.5h old (valid ~7 days)" and a live pull worked. This is cited as the ground truth for why #77 was opened, but the actual probe that verified the token age and the live pull is not included in the ticket — it is presumably from the user's 2026-07-14 pushback session. Treated as established fact; the ticket itself is the evidence this feature is needed.

3. **Notification log triggering mechanism:** How entries end up in `/root/task_system/notifications.log` (what writes to it, on what schedule) is not inspected. Assumed to be related to the "Deferred Task System" section of CLAUDE.md (line 174–178) but not verified.

4. **Memory file location:** The digest reads from `/root/.openclaw/workspace/memory/`, which is a different directory from `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` (the auto-memory index). The distinction and the layout is assumed but not re-verified.

---

## Implications for Candidate Directions

### Candidate (a) — Claim-Shape Gate

**Blockers:**
- Needs to know: what hook event can intercept an outbound assistant message *before* it's sent? SessionStart is input-time, Stop is at "done" — neither sees mid-conversation claims.
- Risk: detecting "X expired/down/failed" shapes from raw message text is fragile. Must distinguish genuine unverified assertions from hedged ("might be"), quoted ("the user said..."), or hypothetical frames without false-firing.

**If feasible:**
- Would be a new hook, likely on a currently-unused event or a Stop hook that backtracks through recent turns to detect unverified claims. Zero standing context cost (fires only on a trigger). Could address mid-conversation claims.

### Candidate (b) — Source-Tag Startup Alerts

**Blockers:**
- Needs sample of notification log format and entry structure.
- Needs confirmation that SessionStart can inject contextual labels (candidate suggests adding "UNVERIFIED as of <time>" per line).

**If feasible:**
- Rewrites the digest (openclaw-digest.sh) to tag each notification line at print time. Zero code cost (bash one-liner addition). Targets the exact failure mode from the #77 incident. Narrow (only startup alerts), not general claims.
- Most likely to be lowest-friction first win.

### Candidate (c) — Sub-Agent Rule Propagation

**Blockers:**
- Requires inspection of agent/task spawning code and prompt assembly.
- Requires decision: is the rule injected into every agent prompt, or only on certain agent types? How to avoid bloat?

**If feasible:**
- Addresses the second gap from #40 (rules don't carry into sub-agents). Broader scope than (a) or (b). Likely higher complexity.

---

## Summary for Next Phase

**Ready for research:**
- Claude Code v2.1.210 official hook documentation (events, I/O contract, capabilities)
- Sample notification log entries (format, existing fields)

**Ready for candidate evaluation:**
- (b) is the lowest-friction, narrowest win if notification log format permits tagging
- (a) requires identifying a hook event for mid-message detection
- (c) requires deeper code inspection

**No unknown blockers for this repo-level work:**
- All four hook events are wired and accessible
- CLAUDE.md/comm-check/MEMORY.md are present and documented
- Diagnosis (#40, #77) is clear and explicit
