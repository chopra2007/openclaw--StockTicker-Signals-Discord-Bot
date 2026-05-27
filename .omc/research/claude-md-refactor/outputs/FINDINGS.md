# FINDINGS.md — Adversarial Review: Both CLAUDE.md Files

Plain English throughout. Numbers at end of each section.

---

## Before / After Line Counts

| File | Before | Draft | Reduction |
|---|---|---|---|
| global-CLAUDE.md | 117 lines | 62 lines | 47% |
| project-CLAUDE.md | 221 lines | 121 lines | 45% |
| Combined | 338 lines | 183 lines | 46% |

---

## 1. What Is Redundant (Same Rule in Both Files)

**Communication Style** appears word-for-word in both files (8 lines each). The global file is the right home for it — it applies to every project. The project file needs only a one-line pointer back to the global file, not a copy. CUT from project file: the full block (8 lines → 1 line pointer).

**"No confirmation" behavior** ("shall I proceed?") is in the project file AND in `inputs/memory/feedback_no_confirmations.md`. Memory already carries this. It can stay as a one-liner in the project file (single-line behavior rules are cheap), but the memory entry means it is not at risk of being lost even if trimmed.

**"Behavior" section** in the project file is a single instruction that memory already tracks. Kept as a one-liner — cost is negligible, safety is high.

---

## 2. What Is Verbose (Says in 10 Words What Could Be 3)

**Definition of Done — "Before typing done/complete/fixed/ready" paragraph**: This is a re-explanation of rules already stated earlier in the same section. The instruction "re-read this section" is meta-commentary on the section itself. The actual rule ("pre-existing is not an excuse") is already stated in the opening paragraph. CUT: the full closing paragraph (8 lines → 1 line).

**Definition of Done — "Never assume code behavior"**: This is a restatement of the Karpathy "Think Before Coding" rule and the Verification Ladder in the Communication Discipline section. One sentence suffices. CUT: 3 lines → 1 line (merged into Evidence Standard).

**Real-World Testing**: The opening sentence "See the real-world test requirement under Definition of Done above" is dead weight — the reader is in the same file. The three-paragraph structure repeats the same idea (don't stop at unit tests) twice. Compressed from 18 lines to 8 lines.

**Regression Gate**: The explanation of what the pre-push hook does and how to install it is operational detail that changes rarely and is better looked up than memorized. The core rule (no new failures vs baseline) fits in 4 lines. CUT: setup/install prose (5 lines).

**Key Design Decisions**: The playwright-stealth note and pytest asyncio_mode line are look-up facts, not behavioral rules. They are already in memory. CUT: 2 lines. The rest stays — it's genuinely load-bearing for any new coding work.

**GitHub & Documentation Automation**: "After every functional change: commit locally then push immediately" is a behavioral rule that matters. The remote URL and README instruction are facts already in memory. CUT: 2 lines.

**OMC block in global file**: See Section 4 below for full analysis.

---

## 3. What Is Load-Bearing (Must Be Preserved)

### Communication Style + Discipline (BOTH files)
Why: The global style rules exist because the user is not a coder and this has caused real pain (multiple memory corrections). The Communication Discipline section (pre-send check, verification ladder, jargon table, comm-check trigger) is a formal enforcement layer added specifically because the style rules were eroding. Both must be preserved. The jargon table is load-bearing — it grows over time and would be painful to reconstruct.

### Definition of Done (project file)
Why: Three real incidents from memory confirm the exact rules here are needed:
- `feedback_no_premature_closure.md` — closed twice with broken @-mentions, called it "pre-existing."
- `feedback_verify_before_claiming_done.md` — declared done on "Gateway READY" log without showing actual bot output.
- `feedback_real_world_testing.md` — F3 shipped without running against a real YouTube video.

Each paragraph in this section maps to a real failure. The always-on checks (service status, symlink check) and shared-file tripwire are specific enough to be genuinely useful, not just general reminders. Preserved in full but tightened.

### Regression Gate (project file)
Why: The distinction between count and set ("fixes one, breaks another = still a regression") is non-obvious and has been the source of confusion. The `.test-baseline` mechanism and the pre-push hook are real infrastructure. Preserved with only boilerplate trimmed.

### Real-World Testing (project file)
Why: `feedback_real_world_testing.md` and `feedback_diagnose_and_explore_alternatives.md` both document failures that happened because Claude stopped at "code-functional." The diagnosis ladder (diagnose → fix → alternate path → then ask user) is the specific rule that prevents a specific repeated failure. Preserved, compressed.

### Karpathy Guidelines (global file)
Why: Explicitly user-designated doctrine. The four rules (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution) are each distinct and non-overlapping. The negative examples are useful because they give concrete counterexamples, not just abstract rules. Tightened but preserved in full.

### OMC Block (global file)
Why: Runtime-required. See Section 4.

### Alert Philosophy + Commands (project file)
Why: Alert Philosophy contains specific rules (8-K never standalone, Form 4 scoring) that are not derivable from general principles. Commands block is a fast reference. Both preserved as-is.

### Deferred Task System (project file)
Why: Specific mechanism (`/root/task_system/scripts/create_task.sh`, session-start check of notifications.log). Not in memory. Preserved.

---

## 4. OMC Block — Line-by-Line Deduplication Analysis

The global CLAUDE.md OMC block runs from line 57 to line 117 (61 lines including markers). The `skill-omc-reference.md` skill documents the following in full:

- Full agent catalog with models (explore, analyst, planner, architect, etc.)
- Full model routing table
- Full tools reference (state, team, notepad, project memory, LSP, AST)
- Full skills registry with all keyword triggers
- Full team pipeline stages
- Full commit protocol with trailers and example

**What the CLAUDE.md block has that the skill does NOT**: Nothing unique. Every piece of information in the CLAUDE.md OMC block is fully documented in `omc-reference`. The CLAUDE.md block itself even says "Detailed agent catalog, tools, team pipeline, commit protocol, and full skills registry live in the native `omc-reference` skill."

**What must stay in CLAUDE.md** (because it is runtime behavior, not reference lookup):
- The operating principles (delegate, verify, lightest path, consult docs) — behavioral directives that shape every action
- The delegation_rules summary (what to delegate vs. do directly) — decision rule used every turn
- The model_routing summary (haiku/sonnet/opus) — decision rule used every turn
- The skills trigger keywords — these ARE the invocation mechanism; without them in the always-loaded context the triggers don't fire
- The verification rule (verify before claiming, size appropriately, keep iterating) — behavioral directive
- The execution_protocols (explore first, parallel independent tasks, separate authoring/review, never self-approve) — behavioral directives
- The hooks_and_context patterns (hook success, MAGIC KEYWORD, boulder) — runtime signal patterns
- The persistence tags (`<remember>`) — runtime mechanism
- The cancellation rule — behavioral directive
- The worktree_paths — looked up not memorized, but short enough to keep

**What can be removed** (fully covered by `omc-reference` skill, explicitly referenced from the CLAUDE.md block itself):
- The sentence "Detailed agent catalog, tools, team pipeline, commit protocol, and full skills registry live in the native `omc-reference` skill..." — this is the pointer sentence; keep a short form of it
- The `## Setup` section ("Say 'setup omc' or run...") — utility note, not a behavioral rule. CUT: 2 lines.
- The `<!-- OMC:START -->` / `<!-- OMC:VERSION -->` / `<!-- OMC:END -->` marker lines — these are installation markers for the plugin installer, not instructions for Claude. They should be preserved so the plugin can update the block. KEPT.

Net: OMC block goes from 61 lines to 48 lines. Behavioral rules all preserved. Setup note cut.

---

## 5. What Is Droppable (No Behavioral Rule Lost)

| What | Lines | Reason |
|---|---|---|
| "Communication Style" block in project file (replaced by pointer) | 8 → 1 | Exact copy in global file |
| DoD "Before typing done" closing paragraph | 8 | Restatement of rules already in same section |
| DoD "Never assume code behavior" standalone heading | 4 | Folded into Evidence Standard (1 line) |
| Real-World Testing opening "see above" sentence | 1 | Useless self-reference |
| Real-World Testing middle paragraph (repetition of "unit tests don't count") | 5 | Said once is enough |
| Regression Gate hook install instructions | 3 | Operational detail, not a rule |
| Key Design Decisions: playwright + pytest lines | 2 | Facts, not rules; in memory |
| GitHub: remote URL + README instruction | 2 | Facts in memory |
| OMC `## Setup` section | 2 | Not a behavioral rule |
| Global file "Personal Preferences" section title line | 1 | Can be folded inline |

Total dropped: ~37 lines

---

## 6. Compression Strategy

**Approach**: Preserve every behavioral rule and incident-backed constraint at the expense of every explanatory sentence, self-referential instruction ("re-read this section"), and fact that memory already holds.

**How aggressive**: Moderately aggressive. The definition-of-done and communication discipline sections were touched only to remove duplicate statements and trim closing paragraphs — the core lists are intact. The OMC block was trimmed only where `omc-reference` explicitly covers the same content. The jargon table and all specific file paths / thresholds were kept verbatim.

**What I did NOT cut even though I could have argued for it**:
- The full jargon table (30+ rows) — grows over time, the user said add to it; removing it would require reconstructing it from scratch
- The shared-file tripwire list — specific enough to be worth the space
- The always-on check list (services, symlink) — these are the exact items that caught two real incidents

**One divergence from load-bearing constraints**: None. All seven load-bearing constraints are fully preserved in both drafts.

