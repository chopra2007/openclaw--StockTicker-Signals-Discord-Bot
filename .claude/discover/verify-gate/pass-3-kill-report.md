# Verify-Default Gate — Pass 3 Kill Report

**Date:** 2026-07-15  
**Scope:** Synthesis of Pass 1 (10 candidates) and Pass 2 (filtered 3) through adversarial review; final payload for implementation decision  
**Methodology:** Symmetric kill/survivor reporting; each finding cites Pass 1/2 evidence and real-world incidents from #77

---

## Executive Summary

Three candidate design patterns survive the screening. The deterministic Stop-hook gate (c9) reuses proven precedent from TODO #69, guards against false-fire via a two-condition AND rule (claim-shape AND no verification tool), and adds zero standing context. The SessionStart digest tagger (c3) hardenes the most common failure class (~70% of incidents) at minimal cost. The LLM escalation layer (c4) is reserved as a fallback if c9's pattern matching proves too coarse in practice. Seven candidate directions were deprioritized or killed due to violations of hard constraints, unresolved feasibility gaps, or subsumption into stronger alternatives.

---

## KILLS

### K1: Standalone LLM-Based Adjudication (Candidates C4/C6 as first-ship)

**Objection:** Both candidates violate the hard constraint "must NOT add LLM cost per message unless clearly justified."

**Evidence:**
- C4 (Multi-Gen + Contradiction Scoring): Pass 1, lines 81–98. "Adds LLM cost to flagged turns. For every claim matching the pattern, the system spins up an LLM judge. This contradicts the hard constraint."
- C6 (NeMo Grounding Rail): Pass 1, lines 122–139. "Requires model-based scoring (NLI or LLM judge). Adds LLM cost per flagged message. Contradicts the hard constraint."
- Research findings (RESEARCH_FINDINGS.md, lines 169–180): "Candidate (a) [deterministic] ⚠️ Runs on every stop; adds latency. Candidate (c) [agents] ⚠️ Scales with team size." LLM-based scoring fails both halves.

**Rebuttal:** The user explicitly selected this as the killer: "The fix cannot be 'more preamble' and it cannot add per-message cost." Pass 1 acknowledged the cost but proposed LLM escalation as a fallback, NOT as the first line.

**Judge Reason:** LLM-based fact-checking adds per-message cost that the user has already rejected for other attempted fixes (OMC pre-tool advisories, CLAUDE.md preambles). The cost is justified only if deterministic alternatives (C9) fail in practice. As a first ship, LLM-based candidates are rejected; C4 survives ONLY as a rank-3 contingent fallback, explicitly gated by "if c9's pure-regex+tool-call gate proves too coarse."

**Disputed By:** None — both Pass 1 and Pass 2 agree LLM approaches violate constraints unless paired with deterministic detection. C4 survives as rank-3 fallback with that gating in place.

---

### K2: PreToolUse Message-Send Gate (Candidates C2/C10)

**Objection:** Requires identifying which internal Claude Code tool handles final message-send; this tool ID is not documented in official Claude Code sources, creating implementation risk.

**Evidence:**
- C2 (Pass 1, lines 39–56): "Tool intercept point is less clear in current Claude Code docs. Verify-on-done.py is documented; what tool Claude Code uses internally to actually send the final message to the user is not explicitly named in available documentation. May require reverse-engineering from hook logs or experimentation."
- RESEARCH_FINDINGS.md lines 8–27: Table lists 11 hook events (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, FileChanged, SessionEnd, StopFailure, PermissionRequest, UserPromptExpansion, SubagentStop). No "MessageSend" or "FinalMessage" event listed.
- Settings.json (verified in RESEARCH_FINDINGS.md line 190): PreToolUse is wired for Skill tools, but the tool name for "final message to user" is not apparent.

**Rebuttal:** PreToolUse does fire earlier in the pipeline than Stop (potentially cheaper on some code paths). However, without confirmed tool identification, implementation would require reverse-engineering, trial-and-error, or waiting for Claude Code docs to clarify. This adds project risk.

**Judge Reason:** Pass 2 ranked this as medium-confidence (Rank not assigned; deprioritized below C3 and C4). The Stop-hook alternative (C9) is already proven in this exact repo (verify-on-done.py, lines 23–27). C2/C10 survive only as an optimization question: "If latency analysis shows Stop adds unacceptable delays on some paths, revisit PreToolUse as an optimization." For initial ship, C9 (Stop hook) is safer.

**Disputed By:** None — both passes agree C2 is riskier than C9 due to unconfirmed tool ID. Optimization path left open.

---

### K3: Passive-Only Provenance Tagging (Candidate C7 as standalone)

**Objection:** Labeling untrusted input without enforcement does not prevent Claude from relaying the claim.

**Evidence:**
- C7 (Pass 1, lines 143–161): "Tagging alone is not enough. Security research explicitly notes that labeling untrusted input only works if a wrapper enforces the tag. Without enforcement (a Stop hook), Claude can silently drop the label."
- MEMORY.md ("verify-default-not-firing.md"): "Passive knowledge — CLAUDE.md 'Verification ladder', comm-check.md §3, MEMORY.md, and ~30 `comm-check-fail-*` memory entries all say 'verify, don't assume.' They *inform* but don't *interrupt* at the instant of answering, and they degrade as context fills. (#40 bottleneck: 'Passive rules do not gate action.')"
- Real incident (Schwab login banner, MEMORY.md 07-14): Claude relayed the SessionStart banner as current fact despite a pre-existing rule against it. The rule was there; it wasn't applied.

**Rebuttal:** C7 is valid as an *input-side* nudge when paired with an enforcement mechanism (C9 Stop hook). Provenance tagging alone has no force.

**Judge Reason:** Pass 2 correctly notes C7 is "complementary" and "must be paired with enforcement" (lines 150–154 of Pass 1). As a standalone first ship, tagging fails the hard constraint "must gate behavior at decision time." Killed as standalone; survives as a complement to C9 (and may be implemented as part of the "near miss" safeguards for C9).

**Disputed By:** None — both passes acknowledge passive labels require enforcement to be effective.

---

### K4: General Regex-Only Pattern Scanning Without Tool-Call Verification (Candidate C8 as standalone)

**Objection:** Detecting claim shapes from free text (regex matching "expired", "down", etc.) has high false-positive risk and fragments if the pattern list grows beyond ~5 terms.

**Evidence:**
- C8 (Pass 1, lines 165–184): "Industry evidence shows regex-based filtering scales poorly: one production incident describes a filter set growing past ~45 patterns, after which false-fire rate rises and maintenance becomes expensive. Mitigation: keep the pattern list **extremely narrow** (this repo's list: ~5 verbs)."
- C8 Risk: "False positives are costly. If the regex fires on a legitimate phrase (e.g. 'the market is down 2%,' which contains 'down' but is not a status claim), the message gets blocked unnecessarily, forcing re-work."
- C5 (Pass 1, lines 102–118): "Requires structured tool-call logging. The gate needs to examine which tools were called and what files/services they touched… Must be paired with a verification step (Candidate 1's tool-call check)."

**Rebuttal:** C8 is the fast first-stage filter that C9 (Stop hook) already includes. The safeguard is the second condition: "AND no Read/Bash/Grep/WebFetch on a relevant source since the last user message." Text pattern alone is not sufficient.

**Judge Reason:** C8 survives as the *fast-path filter component* of C9 (Pass 2, lines 24–25: "Gate on TWO conditions ANDed: claim-shape present AND no Read/Bash/Grep/WebFetch on a relevant source"). Regex matching without tool-call verification is killed as a standalone; the AND-gate in C9 resolves the false-fire risk.

**Disputed By:** None — Pass 1 and Pass 2 both require the two-condition rule.

---

### K5: Broad PreToolUse Hook Without Tool-ID Confirmation

**Objection:** PreToolUse fires on EVERY tool call (Pass 1, line 49), which adds per-turn overhead unless the hook can efficiently no-op. Without confirmed tool ID for message-send, the hook would need expensive filtering logic to avoid false-matching.

**Evidence:**
- C2 (Pass 1, line 49): "PreToolUse fires on EVERY tool call, not just on Stop. This means the hook runs more frequently than a Stop hook."
- RESEARCH_FINDINGS.md line 19: PreToolUse event description confirms it fires "Before tool executes."
- C10 (Pass 1, lines 208–226): "PreToolUse fires on EVERY tool call, not just on Stop. To avoid per-turn cost, the hook must efficiently no-op when the intercepted tool is not message-send."

**Rebuttal:** The latency concern is valid but marginal if filtering is simple. However, without tool ID confirmation, filtering logic itself becomes speculative.

**Judge Reason:** Stop hook (C9) has lower per-turn cost because it fires once per response (after composition), not once per tool call. PreToolUse optimization is deferred until latency measurements show it's necessary. C2/C10 killed as standalone; optimization path left open post-ship.

**Disputed By:** None — both C2 and C10 acknowledge the latency trade-off.

---

## SURVIVORS

### S1: Deterministic Stop-Hook Claim-Shape Gate (C9)

**ID:** c9  
**Rank:** 1 (Recommended for first ship)  
**Status:** APPROVED for implementation

#### Description
Reuses the proven mechanism from `/root/.claude/hooks/verify-on-done.py` (TODO #69). A Stop hook fires when Claude finishes composing a response. It inspects the final message for claim patterns matching a fixed narrow verb list (expired, down, failed, logged-in, authenticated). For any flagged claim, it checks the current turn's tool-call log for a matching verification tool (Read, Bash, Grep, WebFetch) probing a relevant source. If the claim is present but the verification tool is absent, the hook blocks the message with `{"decision": "block", "reason": "Verify before stating"}`, forcing Claude to re-work.

#### Demerits
1. **Per-turn cost on flagged claims.** When a claim-shaped message is detected, re-work is forced. This adds latency to some paths, though most turns skip (fast-path exit on lines 170–171 of verify-on-done.py analogy).
2. **False-fire risk on quoted/hedged claims.** Detecting "X expired" from free text may match hypothetical phrasing ("if the token expired," "the log says it expired") and block legitimate hedged statements.
3. **Stop-hook recursion cap at 8 blocks.** If Claude's re-work still contains the flagged claim, the hook blocks again. After 8 consecutive blocks, the session hits Claude Code's internal cap and may stall. (Mitigation: honor `stop_hook_active` sentinel and fail-open on errors.)
4. **Transcript parsing dependency.** Hook must read `transcript_path` to inspect tool-call history. Research notes "transcript_path 'may lag behind the in-memory conversation'" (RESEARCH_FINDINGS.md line 19). Edge case: new tool calls may not yet be in the transcript JSON.

#### Safeguards
1. **Two-condition AND-gate (required).** Not (claim-shape present) alone, but (claim-shape present) AND (no Read/Bash/Grep/WebFetch on a relevant source since last user message). This is the key differentiator from C8 regex-only. The tool-call check recovers false-fire risk (validated by peer research: Candidate 5, Pass 1 lines 107–108: "A published benchmark… tested a 4-gate suite of deterministic, read-only pre-execution checks… Result: task success improved from 29.6% to 42.0%").
2. **Fixed, narrow verb list.** Keep the list to ~5 terms (expired, down, failed, logged-in, authenticated). Never widen to chase more claim shapes; pattern-list bloat is documented to cause false-fire explosion at ~45 patterns (C8 evidence, Pass 1 line 173).
3. **Fail-open on errors.** If the hook times out, fails to parse transcript_path, or encounters internal error, exit with code 0 (allow the stop) and log the error. Exactly replicate verify-on-done.py lines 245–249: never trap Claude on the hook's own bug.
4. **Honor recursion sentinel.** Maintain a `stop_hook_active` counter (verified in verify-on-done.py line 134). If already blocking repeatedly on the same turn, allow the next stop to proceed (avoid 8-block cap stall).
5. **Register hook on BOTH Stop and SubagentStop.** Stop fires at end of Claude's response. SubagentStop fires when a spawned agent finishes (RESEARCH_FINDINGS.md line 27). Subagent findings can be relayed unchecked (incident from #40: "Apify actor is dead" was delegated to a subagent and returned as fact). Register the same gate on SubagentStop to catch subagent claims.
6. **Escape for cited claims.** A message containing a file path (file:line), URL, or quoted tool-output that cites evidence for the claim passes the gate automatically. Example: "Schwab login expired (verified via /root/.openclaw/.env check)" passes even if no Read happened in this turn (the citation proves the claim is backed).

#### Near-Miss / Strongest Objection & Resolution
**Objection:** "The AND-gate requires knowing whether a verification tool-call (Read/Bash/Grep/WebFetch) happened THIS turn; the Stop hook input's `last_assistant_message` is final-message TEXT only and carries no tool-call data, so the hook must parse `transcript_path` to find current-turn tool_use entries."

**Resolution:** This is a real code challenge, not a design flaw. The transcript JSON (available to Stop hooks; verified in RESEARCH_FINDINGS.md line 58: "Can access full transcript via `transcript_path`") contains complete tool-call history. The hook must iterate recent entries to find tool_use blocks with matching context (file paths touched, service names probed, URLs fetched). Implementation is ~150 lines (analogous to verify-on-done.py's test-baseline logic). The risk is parsing fragility if transcript format changes; mitigation is to fail-open and test against real transcripts before ship.

#### Cross-Family Notes
- **Supersedes C1, C8, C5.** C1 was C9 with docs added. C8 (regex-only) is the fast path within C9. C5 (pre-exec gate research) is the validation that C9's two-condition approach works.
- **Complementary to C3.** C3 (source-tag) handles startup-alert input; C9 (Stop hook) handles general claims. Together they cover both input and decision-time gates.
- **Deprecates passive rules.** Once C9 is live, the passive "Verification ladder" rule in CLAUDE.md is no longer the primary control; it becomes a reference, not an enforcer.

---

### S2: Source-Tag the SessionStart Digest (C3)

**ID:** c3  
**Rank:** 2 (Recommended for concurrent ship)  
**Status:** APPROVED for implementation

#### Description
Rewrite `/root/.claude/hooks/openclaw-digest.sh` (the SessionStart hook that emits the OpenClaw memory digest and notifications) so that machine-snapshot banners (e.g., "Schwab login has EXPIRED") arrive labelled with "[UNVERIFIED as of HH:MM:SS — probe before repeating]". The tag is prepended or appended to each snapshot entry, making the verification requirement visible at input time, before Claude reads the notification.

#### Demerits
1. **Only fixes startup alerts, not general claims.** A claim like "Codex is not authenticated" that Claude derives from reasoning (not from a startup banner) is not covered. This is intentional narrowing but leaves ~30% of incidents unaddressed (Pass 2, line 54: "only fixes the digest input path; does nothing for other trust-string sources").
2. **Depends on Claude recognizing the label.** A label like `[UNVERIFIED]` is metadata. Claude has to choose to honor it or can silently drop it. Passive labels can degrade under load or paraphrase (MEMORY.md: "passive rules do not gate action").
3. **Requires updating a live system script.** `/root/.claude/hooks/openclaw-digest.sh` is outside the repo and run by the system at every SessionStart. Changes affect every session. Coordination with system startup may be needed; errors could break SessionStart.
4. **Notification log has no structured write-time metadata.** The script reads from `/root/task_system/notifications.log`, which stores plain-text entries with timestamps. Adding `[UNVERIFIED]` labels requires string manipulation; if the write mechanism changes, labels may get orphaned.

#### Safeguards
1. **Pair with C9 as the enforcer.** Tagging is the input-side nudge; the Stop-hook gate (C9) is the decision-time enforcement. Neither alone is sufficient (C7 evidence). Together: incoming notifications are marked suspicious, and any outbound claim relaying them is blocked until verified.
2. **Synthesize timestamp deterministically.** If notification entries lack a timestamp, derive one from the file's mtime or the current date-time at print time. Keep it ISO8601 format and note the source (file mtime vs. print time).
3. **Keep existing action-item framing.** The digest already provides useful action items ("until you re-login"). The `[UNVERIFIED]` tag is additive, not a replacement. One short line per snapshot entry to avoid burying the actionable part.
4. **Test against real SessionStart runs.** Before shipping, verify that notifications.log entries are correctly tagged and the digest output is still readable (not mangled by escaping or line wrapping).
5. **Ship first.** This change is the cheapest and has the highest immediate ROI (~70% of incidents per MEMORY.md comm-check-fail-2026-07-14). It can ship independently before C9 is deployed; C9 is a later enhancement for general claims.

#### Near-Miss / Strongest Objection & Resolution
**Objection:** "Tagging alone is not enforced — the model can silently drop or restate the label in its own words."

**Resolution:** Correct; that's why C3 is rank-2 (concurrent) not rank-1. C3 alone would be passive and insufficient. However, shipping C3 first is still justified because: (1) it directly targets the exact real incident (Schwab login banner from MEMORY.md), (2) it has zero per-message cost (SessionStart runs once), (3) it removes an entire class of false negatives from future incidents (even if Claude drops the label, at least the tag tried). The full solution requires C9 (the enforcer). C3 + C9 together satisfy both hard constraints: gate at decision time (C9) and inform at input time (C3).

#### Cross-Family Notes
- **Targets the most common failure mode.** ~70% of the 7+ logged incidents in #77 involve relaying a startup notification as current fact. This fix addresses exactly that class (MEMORY.md 07-14).
- **Complements C9.** C3 hardens input; C9 hardens decision. Symmetry: defense-in-depth.
- **Narrow scope = high confidence.** Only one script file, one data structure (notification entries). Low risk of side effects.
- **SessionStart hook already proven.** RESEARCH_FINDINGS.md lines 65–72 confirm SessionStart fires at session start/resume, can inject `additionalContext`, and text is read by Claude as a system reminder.

---

### S3: Selective LLM Escalation (C4)

**ID:** c4  
**Rank:** 3 (Fallback layer, contingent)  
**Status:** APPROVED as fallback; ship only if C9's pattern-matching proves too coarse

#### Description
Pairs a deterministic keyword pre-filter (the claim-shape detection from C9) with a Stop-prompt hook that judges only flagged messages using a language model. If C9's pure-regex+tool-call gate produces unacceptable false-fire rates in real sessions (>5%), escalate to an LLM judge for fact-checking. The judge uses a small, cheap model (Haiku) to score contradiction between the claim and the retrieved evidence in the turn's context. If contradiction is found, the message is blocked; if no contradiction, it passes.

#### Demerits
1. **Adds per-turn LLM cost on flagged claims.** Violates the hard constraint "must NOT add LLM cost per message unless clearly justified" (user's explicit rejection in MEMORY.md: "The fix cannot be 'more preamble' and it cannot add per-message cost"). This demerit is intentional; C4 is rank-3 *precisely because* it incurs cost and is only justified as a fallback.
2. **LLM judge accuracy is model-dependent.** NVIDIA NeMo docs (C6 evidence, Pass 1 line 131): "accuracy is 'strongly dependent on the capability of the LLM.'" A Haiku-level judge may produce false negatives (fails to catch real errors) or false positives (wrongly flags correct claims). This project has had mixed results with model selection (MEMORY.md: model-bakeoff, nemotron-retest).
3. **Only triggered if C9 fails.** C4 is contingent on C9 producing unacceptable false-fire rates. If C9 works well (false-fire rate <5%), C4 adds complexity without benefit.
4. **Doubles the decision logic.** Once C4 is deployed, every flagged message goes through two gates: (1) C9's deterministic check, (2) C4's LLM judge. Debugging failures becomes more complex.

#### Safeguards
1. **Keep as a fallback layer, NOT first ship.** Build C9 deterministic first. Add LLM escalation only if, after real-world deployment, C9's false-fire rate exceeds the acceptable threshold (recommend: >5% of flagged messages are false-positives). Contingency gate: set a flag `use_llm_escalation` to false by default; flip to true only after evidence that C9 alone is insufficient.
2. **Deterministic pre-filter ensures LLM runs on a small subset only.** The LLM judge only runs on claim-shaped messages (the ~5% of turns that match keywords). The other ~95% of turns are unaffected. This keeps per-session cost low even if the judge is enabled.
3. **Use type:'prompt' Stop hook with Haiku default.** RESEARCH_FINDINGS.md line 53 confirms stop hooks can use `type: 'prompt'` to escalate to an LLM. Default to Haiku (~0.80 cap + ~1.20 output) to keep cost under $0.01 per flagged message. Escalate model only if Haiku accuracy proves insufficient (require evidence before upgrading).
4. **Implement only AFTER C9 is live and baseline metrics are established.** Ship C9, monitor its false-fire rate in production (log every claim-shape block), and use that baseline to justify C4's cost if needed.

#### Near-Miss / Strongest Objection & Resolution
**Objection:** "C4 is explicitly rank-3/contingent: it only fires the LLM judge on the same claim-shaped subset C9's pure-regex+tool-call gate already handles deterministically. Why not just improve C9's pattern list instead?"

**Resolution:** Good question. C4 is the explicit contingency for the case where C9's *text pattern detection* itself is too fragile — e.g., "if the market is down 2%" contains "down" but is not a status claim, and word-boundary regex can't reliably disambiguate. If this class of false-fire proves common in real use, C4 allows an LLM judge to do semantic disambiguation WITHOUT changing the underlying deterministic gate. C4 is architecture-heavy but justified if the text-pattern approach itself is the bottleneck. If improvements to the verb list or word-boundary logic solve the problem, C4 is not needed.

#### Cross-Family Notes
- **Only shipped if C9 proves insufficient.** Not a standalone solution; explicitly deprecated as a first-choice.
- **Lower cost than C4/C6 as autonomous first-ship.** Because it runs only on the claim-shaped subset, not all turns. If C9 is accurate, LLM cost is zero.
- **Research-backed as a fallback.** Industry guardrail papers document this sampled-escalation pattern (C4, Pass 1 line 86: "A cheap keyword filter (`expired|down|failed|logged-in|authenticated`) fires only on the ~5% of turns containing a flagged claim").

---

## Summary Table

| Candidate | Status | Rank | Deterministic? | Per-Turn Cost | Context Bloat? | Hard Constraints Met? | Ship Order |
|-----------|--------|------|---|---|---|---|---|
| **C9** | APPROVED | 1 | Yes | Flagged turns only | No | ✓ Both | First |
| **C3** | APPROVED | 2 | Yes | SessionStart only | No | ✓ Both | Concurrent |
| **C4** | FALLBACK | 3 | No (LLM) | Flagged turns (if C9 insufficient) | No | ✓ If deferred | Later |
| K1: LLM-standalone | KILLED | — | No | Flagged turns | No | ✗ Cost constraint | Never |
| K2: PreToolUse | KILLED | — | Yes | All turns (filtered) | No | ⚠️ Tool ID unknown | Deferred |
| K3: Passive-tag-only | KILLED | — | Yes | SessionStart | No | ✗ No decision-time gate | Never |
| K4: Regex-only | KILLED | — | Yes | Flagged turns | No | ⚠️ False-fire risk | Never (subsumed in C9) |
| K5: PreToolUse-broad | KILLED | — | Yes | All turns | No | ⚠️ Per-turn overhead | Deferred |

---

## Implementation Roadmap

### Phase 1: Immediate (C3 + C9)
1. **C3 first (1–2 days).** Rewrite `/root/.claude/hooks/openclaw-digest.sh` to tag notifications with "[UNVERIFIED as of <time> — probe before repeating]". Lowest friction, highest immediate ROI.
2. **C9 follow (3–5 days).** Implement Stop hook (~150 lines bash, analogous to verify-on-done.py). Wire in `/root/.claude/settings.json`. Test against historical transcripts for false-fire rate.
3. **Validation.** Ship both. Monitor false-fire rate and user feedback. If C9's false-fire is <5%, declare Phase 1 done.

### Phase 2: Contingent (C4)
- Only open if Phase 1 monitoring shows C9's false-fire rate exceeds 5%.
- Document the evidence (specific false-positives with transcript links).
- Implement LLM judge on top of C9 deterministic gate.
- A/B test Haiku vs. stronger models to find accuracy/cost sweet spot.

### Phase 3: Optional (C2 Latency Optimization)
- If latency analysis shows Stop-hook blocking adds >200ms to common paths, revisit PreToolUse message-send optimization.
- Requires reverse-engineering the internal tool name from Claude Code logs.
- Low priority; ship C9/C3 first and measure before investing.

---

## Evidence Trail

1. **Pass 1:** 10 candidates synthesized from 7+ logged #77 incidents, peer-reviewed research (arxiv 2607.07405), and production precedent (verify-on-done.py).
2. **Pass 2:** Filtered to 3 survivors (C9, C3, C4) based on hard constraints and feasibility.
3. **Research Findings (RESEARCH_FINDINGS.md):** Verified Claude Code v2.1.210 hook system, notification log format, and transcript JSON availability.
4. **Real-world incidents:** MEMORY.md comm-check narratives (07-14: Schwab login banner relayed as fact; 06-01: stall misdiagnosed; 07-12: grep artifact → false claim about config key).
5. **Production code:** verify-on-done.py (TODO #69, 250 lines, deployed).

All findings sourced from official documentation, live system inspection, and incident logs. No speculation.
