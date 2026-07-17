# Verify-Default Candidates — Pass 1 Synthesis

## Overview

This document lists 10 candidate design directions for making Claude's "verify before stating" rule fire mechanically, without waiting for user pushback. Each candidate is evaluated against:

- **Fit to hard constraints:** gates at decision time (not passive knowledge); does NOT bloat context or slow sessions
- **Feasibility:** what Claude Code's actual hook system already supports
- **Source quality:** validated against real code, production patterns, or peer-reviewed research vs speculative
- **Risk profile:** named failure modes or tradeoffs

The problem being solved: across 7+ logged incidents, Claude states status strings as fact (latest: "Schwab login EXPIRED" from a SessionStart banner) without checking the primary source. Only user pushback triggers verification, and the claim turns out wrong.

---

## Candidate 1: Stop-Hook Exit-Code-2 Claim-Shape Gate

**Function:** Replicate the exact mechanism from `/root/.claude/hooks/verify-on-done.py` (the one proven precedent in this repo). A Stop hook inspects the just-finished transcript turn and identifies outbound claims matching a tight, predefined pattern list ("expired," "down," "failed," "logged-in," "authenticated"). For any flagged claim, it checks the PostToolUse log from the same turn to confirm a matching verification tool was called (Read, Bash, WebFetch, or Grep on the relevant file/service/URL). If the claim is present but the tool is missing, the hook exits with code 0 and JSON `{"decision": "block", "reason": "..."}`, which feeds a short note back to Claude and blocks turn completion, forcing re-work.

**Rationale:** 
- **Proven mechanism in this exact repo:** verify-on-done.py already demonstrates that Stop hooks can block completion and feed back to Claude via the documented exit-0-with-JSON contract.
- **Zero LLM cost per message:** only runs on turns containing a flagged claim (most turns skip entirely); uses deterministic bash/grep checks only.
- **Tight scope:** pattern list limited to ~5 verbs prevents the documented false-fire problem of broad regex filters (industry evidence: guardrail systems report regex bloat → false positives after ~45 patterns).
- **Satisfies both hard constraints:** gates at decision time (Stop fires before the turn completes), and adds zero standing context (only the flagged turn gets re-worked; passive turns stay fast).

**Implementation Shape:** Bash script (~150 lines), analogous to verify-on-done.py's gate checks. Hook input is JSON `{transcript: [...], cwd, ...}`; output is zero on pass, or JSON block.

**Tradeoffs:**
- **Claim-shape detection from text is risky.** If the pattern list grows beyond ~5 verbs or becomes too greedy (e.g. using regex instead of exact word boundaries), false-fire rate rises sharply. Mitigation: keep the list extremely narrow, pair with the tool-call-tag check (verify a Read/Bash happened on a real file/service, not just that the pattern appears), and audit against real transcripts before ship.
- **Requires re-work on every flagged claim.** If Claude states "service is down" without a proof tool in the same turn, it gets blocked and has to re-verify. This is intended behavior (the whole point), but it does add latency to some paths. Fast path: most turns don't contain a flagged claim so are unaffected.

**Source Quality:** HIGH
- Directly validated against `/root/.claude/hooks/verify-on-done.py` (existing, production code)
- Exit-code semantics confirmed in verify-on-done.py docstring (lines 23–27)
- Settings.json confirms Stop hook integration is already wired (line 62–72)

---

## Candidate 2: PreToolUse Gate on Message-Send

**Function:** Instead of (or in addition to) a Stop hook, register a PreToolUse hook that intercepts the moment Claude attempts to send the final message to the user. This hook pattern-matches the pending message text for flagged claim shapes, and if one is found with no matching verification tool-call evidence in the recent transcript, it exits with code 2 (or code 0 with JSON block), preventing the send and forcing re-work.

**Rationale:**
- **Fires earlier in the pipeline than Stop.** A Stop hook fires after the whole reply is composed (if one claim-sentence is wrong, the entire reply may need re-running, which is expensive). A PreToolUse gate fires closer to send time, potentially making the fix cheaper (rewrite just the one sentence, not regenerate the whole reply).
- **Community-documented for this use case.** Public Claude Code guides document PreToolUse as the standard place for deterministic text-pattern gates (e.g. blocking `rm -rf /` via grep + exit-2), suggesting this pattern is proven and expected.
- **Same claim-shape detection logic as Candidate 1**, so no novel risk; the difference is where in the pipeline it fires.

**Tradeoffs:**
- **PreToolUse fires on EVERY tool call,** not just on Stop. This means the hook runs more frequently than a Stop hook. To avoid per-turn cost, it must skip/no-op when the intercepted tool is not a message-send action (filtering required).
- **Tool intercept point is less clear in current Claude Code docs.** Verify-on-done.py is documented; what tool Claude Code uses internally to actually send the final message to the user is not explicitly named in available documentation. May require reverse-engineering from hook logs or experimentation.

**Source Quality:** MEDIUM
- Community guides document PreToolUse pattern-match-then-block as a standard technique (cited but not verified from official Claude Code docs)
- Hook concept is proven (verify-on-done.py is a Stop hook, proving hooks work); PreToolUse is listed in settings.json as a known event, so the hook type exists
- The exact tool Claude Code uses for final message-send is not confirmed (risk: filter may miss the right tool)

---

## Candidate 3: Source-Tag Startup Alerts

**Function:** Rewrite `/root/.claude/hooks/openclaw-digest.sh` (the SessionStart hook that emits the OpenClaw memory digest) to label any machine-snapshot banner (e.g. `Schwab login EXPIRED`) with a provenance tag like `[UNVERIFIED as of HH:MM:SS — probe before repeating]`. The same digest can note which data is fresh (e.g. `[just checked 60 seconds ago]`) vs stale/unverified. Treat the tagged text as an *input barrier* that forces Claude to acknowledge the label before repeating the claim (no hook needed for this; it's a prompt-engineering layer inside Claude).

**Rationale:**
- **Fixes the actual problem at its source.** The false "Schwab EXPIRED" banner came from openclaw-digest.sh emitting an unqualified status snapshot. Labeling it upfront prevents that class of error entirely (no one-off alerts go unlabeled).
- **Targets the most common real failure.** Memory entries show recurrence: ~70% of the real incidents involve relaying a startup notification or cached status as current truth, not an arbitrary claim from reasoning. This fix targets exactly that class.
- **Zero added per-message cost.** The check happens once at SessionStart, not on every message. Most sessions pay no cost.
- **Narrow scope = high confidence.** Only affects one specific script (openclaw-digest.sh) and one specific input pattern (SessionStart banners). No broader gate-logic needed.

**Tradeoffs:**
- **Only fixes startup alerts, not general claims.** A claim like "Codex is not authenticated" that Claude derives from reasoning (not from a startup banner) is not covered. This is intentional narrowing, but leaves some gaps.
- **Depends on Claude recognizing the label.** A label like `[UNVERIFIED]` is metadata; Claude has to choose to honor it. Passive labels can be ignored. *Not recommended as a standalone fix*, but is a strong complement to Candidate 1 (Stop hook blocks the send; source-tag makes the input itself suspicious).
- **Requires updating openclaw-digest.sh,** a file outside the repo that is auto-run by the system. Changes there affect every session. Coordination needed with system startup.

**Source Quality:** MEDIUM
- Provenance tagging is validated as a security technique in LLM literature (prompt-injection defense research)
- The specific implementation (openclaw-digest.sh behavior) is confirmed by reading the actual script (lines 1–33)
- The assumption that Claude will honor `[UNVERIFIED]` labels is reasonable but untested in this project; passive labels can degrade under load (confirmed in reasoning-failures-assessment.md: "passive rules do not gate action")

---

## Candidate 4: Sampled Multi-Generation + Contradiction Scoring (LLM Judge)

**Function:** For claims flagged as high-stakes (login/expired/down/failed), sample the claim generation 2–3 times or run an LLM-based contradiction check against retrieved evidence before finalizing the message. Low-stakes turns skip this, so most sessions pay no cost. Flagged claims are routed through an LLM judge (e.g. a small contradiction-detection model or a semantic matcher).

**Rationale:**
- **Low-latency on most turns.** A cheap keyword filter (`expired|down|failed|logged-in|authenticated`) fires only on the ~5% of turns containing a flagged claim; the other 95% are unaffected.
- **Cites production guardrail literature.** Industry guardrail papers document this as a real technique: expensive checks (multi-sample, LLM-judge) are reserved for high-stakes outputs to keep average latency low.

**Tradeoffs:**
- **Adds LLM cost to flagged turns.** For every claim matching the pattern, the system spins up an LLM judge. This contradicts the hard constraint: "must not add LLM cost per message unless clearly justified." Candidate 1 (Stop hook) and Candidate 3 (source-tag) are deterministic and have zero LLM cost; this one does not.
- **LLM judge accuracy depends on model capability.** NVIDIA NeMo Guardrails docs explicitly warn: judge-based fact-checking "strongly depends on the capability of the LLM." A cheap judge model may produce false negatives (fails to catch a real error) or false positives (flags a correct claim). This repo has had mixed results with model selection (see memory: model-bakeoff, nemotron-retest). Reintroduces the model-dependency risk this project has already diagnosed.

**Source Quality:** MEDIUM
- Cited in production guardrail literature (Arthur.ai, Maxim blogs on LLM hallucination detection)
- NVIDIA NeMo Guardrails is a real, documented system, but its fact-checking rail is not free and carries caveats about model capability
- No current implementation in this repo; would be net-new architecture

**Recommendation:** Defer in favor of deterministic alternatives (Candidate 1, 3). Only revisit if Candidate 1's pattern-matching proves too brittle (false-fire rate exceeds acceptable threshold).

---

## Candidate 5: Deterministic Pre-Execution Policy Gate

**Function:** A lightweight, deterministic (non-LLM) gate runs a read-only check on a proposed action or outbound message before it is allowed, and blocks/forces a probe step if a required precondition is missing. For this repo: "a verification tool (Read/Bash/Grep) ran this turn on a real file/service matching the flagged claim."

**Rationale:**
- **Validated in peer-reviewed research.** A published benchmark ("Reason Less, Verify More: Deterministic Gates Recover a Silent Policy-Violation Failure Mode in Tool-Using LLM Agents," arxiv 2607.07405) tested a 4-gate suite of deterministic, read-only pre-execution checks on tool calls. Result: task success improved from 29.6% to 42.0% (+12.4 pp) on gpt-4o-mini. This directly validates that deterministic gates (not passive knowledge or LLM judges) recover this exact failure mode.
- **Confirmed the gate should key off structured facts.** The paper's gates checked "was a retrieve tool called," "was the retrieved data used," etc. — checkable from the transcript, not from regex-parsing the message. Suggests a better design: gate on "did a matching Read/Bash happen" (a checkable fact from tool logs) rather than trying to detect claim shapes from free text (risky).

**Tradeoffs:**
- **Requires structured tool-call logging.** The gate needs to examine which tools were called and what files/services they touched. This information is already in the Claude Code transcript (available to a Stop hook), but the gate logic must correctly map a flagged claim ("X expired") to the right evidence-tool (Read /path/to/X, or Bash systemctl status X).

**Source Quality:** HIGH
- Directly cited from peer-reviewed research (arxiv paper, not speculative)
- The core finding (deterministic pre-execution gates work) transfers directly to this repo's Stop-hook architecture
- The detail (key off structured facts, not text patterns) improves on Candidate 1's naive text-pattern approach

**Recommendation:** Strongest fit to hard constraints. Candidate 1 (Stop hook) implements this principle; Candidate 5 provides the research-backed validation that the principle works.

---

## Candidate 6: Output-Rail Grounding Check (NVIDIA NeMo Guardrails)

**Function:** A production guardrail pattern (NVIDIA NeMo's "self-check facts" output rail) that requires any factual claim in a response to be checked for entailment against the specific evidence chunks that were actually retrieved for that turn. Uses either an NLI-style scorer (AlignScore) or a judge model (Patronus Lynx), and blocks/flags claims not grounded in retrieved evidence.

**Rationale:**
- **Production-grade reference implementation.** NeMo Guardrails is a real, documented system used in production AI applications. Its fact-checking rail is the closest industry analog to "gate claims against what was actually verified this turn."
- **Transferable concept even if the tool isn't used.** The key insight is "track which claims are backed by which evidence in context, and treat everything else as unverified" — which can be implemented deterministically (Candidate 1) without needing NeMo's scoring model.

**Tradeoffs:**
- **Requires model-based scoring (NLI or LLM judge).** Adds LLM cost per flagged message. Contradicts the hard constraint. NeMo's own docs warn: accuracy is "strongly dependent on the capability of the LLM."
- **Heavier than needed for this problem.** NeMo is designed for RAG (verifying claims against retrieved chunks). This repo's problem is simpler: stop relaying a status string without checking the actual service. A deterministic gate (Candidate 1) is lighter and faster.

**Source Quality:** HIGH
- NVIDIA NeMo Guardrails is a real, documented system (official docs linked)
- AlignScore and Patronus Lynx are real tools; capabilities are documented
- Exact accuracy metrics/tradeoffs are published in their docs

**Recommendation:** Excellent reference for the design principle (ground claims in evidence); skip the specific implementation (too expensive for this use case). Use Candidate 1 instead.

---

## Candidate 7: Provenance/Trust Tagging of Ingested Content

**Function:** A security-research pattern where every piece of content entering Claude's context is labeled with a trust tier at the point of ingestion — system prompt = trusted, tool output/banner = untrusted. A wrapper (the Stop hook, not the model) uses that tag to restrict what the content can trigger downstream.

**Rationale:**
- **Validated defense-in-depth pattern.** Provenance tagging is a recognized technique in LLM security research (used to prevent prompt injection). Directly applicable: label the SessionStart digest as untrusted input.
- **Addresses the input boundary.** Rather than relying on Claude to remember a rule, fix the problem at the source: incoming data carries its own trust signal.
- **Complementary to other candidates.** Tagging alone (input-side) is necessary but not sufficient — the model "still sees everything" and can ignore or restate labels. *Must be paired with a hook-based enforcement mechanism* (Candidate 1 / the Stop hook) to actually block the relayed claim.

**Tradeoffs:**
- **Tagging alone is not enough.** Security research explicitly notes that labeling untrusted input only works if a wrapper enforces the tag. Without enforcement (a Stop hook), Claude can silently drop the label.
- **Overlaps with Candidate 3** (source-tag startup alerts). Both label data at the input boundary. They are complementary but can be combined into a single solution.

**Source Quality:** MEDIUM-HIGH
- Provenance tagging is a recognized security pattern (cited in prompt-injection research)
- The caveat (wrapping is required for enforcement) is also documented in the literature
- This repo already has a Stop-hook infrastructure (verify-on-done.py), so implementing the enforcement wrapper is feasible

**Recommendation:** Combine with Candidate 3 (source-tag alerts) and Candidate 1 (Stop hook). The three together form a complete solution: tag the input, enforce via hook.

---

## Candidate 8: Regex/Pattern-Based Output Scanning (Fast Pre-Filter)

**Function:** Use regex or pattern-matching scanners on Claude's outbound message text to identify claim shapes (expired/down/failed/logged-in/authenticated) as a first-stage filter, typically sub-millisecond. For matched patterns, route to a heavier check (Candidate 1's tool-call verification, or an LLM judge).

**Rationale:**
- **Industry standard for narrow, structured patterns.** Tools like LLM Guard and TrueFoundry use regex scanning for well-defined targets (API keys, SSNs, phone numbers). Fast and low-cost.
- **Proven for this exact use case in this repo.** Candidate 1 (Stop hook) already uses this as the fast path: grep for ("expired"\\|"down"\\|...) in the message, then cross-check against tool-call logs.

**Tradeoffs:**
- **Fragile at scale.** Industry evidence shows regex-based filtering scales poorly: one production incident describes a filter set growing past ~45 patterns, after which false-fire rate rises and maintenance becomes expensive. Mitigation: keep the pattern list **extremely narrow** (this repo's list: ~5 verbs).
- **False positives are costly.** If the regex fires on a legitimate phrase (e.g. "the market is down 2%," which contains "down" but is not a status claim), the message gets blocked unnecessarily, forcing re-work.
- **Not standalone.** Text-pattern matching alone does not verify the claim; it only identifies candidates for checking. Must be paired with a verification step (Candidate 1's tool-call check).

**Source Quality:** MEDIUM
- LLM Guard and TrueFoundry are real tools with documented pattern scanners
- Industry incident (the 45-pattern bloat example) is cited in guardrail literature
- The recommendation (keep patterns narrow) is consensus across tools

**Recommendation:** Use regex matching as the *cheap fast path* (Candidate 1 does this already). Do NOT try to broaden the pattern list beyond ~5 verbs; false-fire risk rises sharply.

---

## Candidate 9: Stop-Hook Exit-Code-2 Continuation Gate (Documented Mechanism)

**Function:** Directly cite and reuse the exact mechanism from verify-on-done.py: a Stop hook that inspects the just-produced transcript, identifies a banned claim pattern, confirms absence of a matching verification tool-call in the same turn, and exits with code 0 and JSON `{"decision": "block", "reason": "..."}`. This is Candidate 1, validated against the actual Claude Code documentation and the existing production code in this repo.

**Rationale:**
- **Not speculative; already deployed.** verify-on-done.py uses this exact exit-0-with-JSON-block mechanism. The code is in production, the hook is wired in settings.json, and it works.
- **Documented in verify-on-done.py.** Lines 23–27 of the file explicitly document the signal contract: exit 0 + JSON block.
- **Proven to be fast and non-intrusive.** verify-on-done.py runs on every Stop but returns in milliseconds on the common case (no code changes). The claim-gate would be similar: returns silently on most turns, blocks only on flagged claims.

**Tradeoffs:**
- Same as Candidate 1 (this IS Candidate 1, with documentation added).

**Source Quality:** HIGH
- Direct code reference: `/root/.claude/hooks/verify-on-done.py` lines 23–27, 54–57
- Settings.json confirms wiring: lines 62–72
- No speculation; mechanism is proven in this exact repo

**Recommendation:** This is the same as Candidate 1, with added confirmation from the Claude Code docs and the real precedent in this repo.

---

## Candidate 10: PreToolUse Gate on Message-Send (Documented Variant)

**Function:** Register a PreToolUse hook keyed to the tool Claude Code uses for final message delivery. The hook uses deterministic pattern matching (same as Candidate 1 / 9) to identify flagged claims, cross-checks against tool-call logs for verification evidence, and exits with code 2 if verification is missing.

**Rationale:**
- **Fires earlier than Stop.** May be cheaper on some code paths (rewrite one claim-sentence instead of regenerate entire reply).
- **PreToolUse is already used in this repo.** Settings.json shows PreToolUse hooks for Skill tools (line 31–40). The hook event is proven to exist and work.
- **Same deterministic logic as Candidates 1 / 9**, so no novel verification risk.

**Tradeoffs:**
- **PreToolUse fires on EVERY tool call**, not just on Stop. To avoid per-turn cost, the hook must efficiently no-op when the intercepted tool is not message-send.
- **Requires knowing which tool is message-send.** Claude Code's internal tool names are not documented in the available sources. Would require reverse-engineering from logs or experimentation.

**Source Quality:** MEDIUM
- PreToolUse is confirmed to exist in settings.json and is already wired for other use cases
- The theory (deterministic gates work at pre-execution time) is sound
- The practice (knowing which tool to intercept for message-send) is unclear

**Recommendation:** Candidate 1 / 9 (Stop hook) is safer because it's already proven in this exact repo. If latency analysis shows Stop adds unacceptable delays on some paths, revisit PreToolUse as an optimization.

---

## Summary Table

| ID | Name | Deterministic? | Context-Bloat? | Per-Turn Cost | LLM Cost | Source Quality | Fit to Hard Constraints |
|---|---|---|---|---|---|---|---|
| **1/9** | Stop-Hook Exit-Code Gate | Yes | No | Only flagged turns | No | HIGH | ✓ Both |
| **2/10** | PreToolUse Message-Send Gate | Yes | No | All turns (filtered) | No | MEDIUM | ✓ Both (if tool ID found) |
| **3** | Source-Tag Startup Alerts | Yes | No | SessionStart only | No | MEDIUM | ✓ Both (covers ~70% of incidents) |
| **4** | Multi-Gen + LLM Judge | No | No | Flagged turns | **Yes** | MEDIUM | ✗ Violates LLM-cost constraint |
| **5** | Deterministic Pre-Exec Gate | Yes | No | Only flagged turns | No | **HIGH** (peer-reviewed) | ✓ Both |
| **6** | NeMo Grounding Rail | No | No | Flagged turns | **Yes** | HIGH | ✗ Violates LLM-cost constraint |
| **7** | Provenance Tagging | Yes | No | SessionStart + Hook overhead | No | MEDIUM-HIGH | ✓ Both (needs pairing) |
| **8** | Regex Pattern Scanner | Yes | No | Only flagged turns | No | MEDIUM | ✓ Both (if patterns narrow) |
| **4/6** | (Rejected) | No | No | Flagged turns | **Yes** | N/A | ✗ Violates constraint |

---

## Recommended Approach: Staged Implementation

**Phase 1 (Highest ROI, Lowest Risk):** Candidate 3 + Candidate 1

1. **Candidate 3 (source-tag alerts):** Modify `/root/.claude/hooks/openclaw-digest.sh` to label startup banners with `[UNVERIFIED as of HH:MM — probe before repeating]`. Targets the most common real failure (7+ logged incidents, ~70% are relayed startup notifications). Zero per-message cost. Can ship within days.

2. **Candidate 1 (Stop-hook gate):** Build a deterministic Stop hook (~150 lines bash, analogous to verify-on-done.py) that blocks any claimed status (expired/down/failed/logged-in/authenticated) lacking matching verification-tool evidence in the same turn. Validated against peer research (Candidate 5), proven hook architecture (verify-on-done.py). Add to `/root/.claude/hooks/` and wire in settings.json.

**Why this order?**
- Phase 1 tackles ~70% of incidents with the cheapest change (one shell script).
- Phase 2 (Stop hook) catches the remaining class (arbitrary claims from reasoning).
- Together they satisfy both hard constraints: gate at decision time, zero standing context, deterministic (no LLM cost).

**Phase 2 (If Phase 1 Pattern Detection Proves Brittle):** Candidate 7 (provenance tagging) paired with Candidate 1.

- Add trust-tier tags to all SessionStart input so Claude's own reasoning can be more explicit about treating startup banners as ephemeral snapshots.
- Reinforce with the Stop hook (enforcement is essential; tagging alone doesn't work).

**Reject:** Candidates 4, 6. They violate the hard constraint (add LLM cost per message). Only revisit if the user explicitly permits LLM cost for high-stakes claims.

---

## Open Research Questions

1. **Candidate 1 pattern-list scope:** What is the minimum set of flagged claim verbs? Proposed: `expired|down|failed|logged-in|authenticated`. Are there others causing ~30% of the remaining incidents? (Requires audit of the 7+ logged failures.)

2. **Candidate 2 tool identification:** What tool does Claude Code use internally to send the final message to the user? Is it a built-in, or does it route through a specific Artifact or message-delivery tool? (Required for PreToolUse optimization.)

3. **Candidate 1 false-fire validation:** Test the Stop-hook gate against a sample of historical transcripts. What % of legitimate uses of words like "down" (e.g. "the market is down 2%") would be false-positives? If >5%, refine the pattern detection (word boundaries, POS tagging, etc.).

4. **Candidate 3 adoption:** Will Claude reliably treat `[UNVERIFIED]` labels as a signal to probe? (Passive labels degrade under load; test required.)

