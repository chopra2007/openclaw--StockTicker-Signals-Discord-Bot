# Discover Rebuild — Design Spec

**Date:** 2026-07-02
**Status:** Approved design, pending user review of this written spec (brainstorming hard gate).
**Provenance:** Brainstormed across two sessions (2026-07-01 → 02). Pressure-tested by a 26-agent adversarial workflow (10 critics + 16 refuters; 15 major findings held, 1 refuted by live experiment). Four amendments to previously-locked decisions plus the full recommendation package adopted by the user 2026-07-02. Piece 4 (testing) approved 2026-07-02. Raw findings: `.omc/research/discover-rebuild-pressure-test-2026-07-01.json`. Working notes: `todo/kickoffs/discover-rebuild.md`.
**Non-coder rule:** the plugin author (and reviewer of this spec) is not a coder. All user-facing output of the rebuilt plugin — status lines, checkpoint reviews, kill reports, error messages — must be plain language with jargon translated.

---

## 1. Goal

Rebuild the public `/discover` plugin (repo `chopra2007/claude-discover`) so its research→plan pipeline (Passes 0–4) runs on Claude Code's **built-in Workflow engine**, and its build step (Pass 5) runs in the main session. The engine buys: **main-session memory stays clean** (helper output never lands in the user's context), **reliable structured hand-offs** (schema-validated JSON instead of scraped markdown), **deterministic orchestration** (a script, not prose the model may drift from), and **crash-proof resume**. Explicitly NOT a goal: speed — on low-core machines the engine runs as few as 2 helpers at a moment and is no faster than today.

Simultaneously make the pipeline smarter: evidence-rule kill-testing, bounded research rounds, a plan tournament, an outcome memory across runs.

Hard requirement: works for **anyone on paid Claude Code ≥ 2.1.154** with zero plugins. OMC, superpowers, Codex CLI, Gemini CLI are auto-detected **boosters** — used when present and healthy, silently replaced by built-in fallbacks when absent, loudly flagged when present-but-broken.

## 2. What must not change (compatibility with the current plugin)

- The four hard triggers, unchanged: `/discover` · message starting `discover:` · `discover: resume <name>` · literal phrase "discover skill". Explicit-invocation-only stays.
- Run home: `.claude/discover/<run-name>/` relative to the project root; human-readable per-pass artifacts.
- One-short-line resume: `discover: <name>` resumes, `discover: build <name>` builds a saved plan. Never ask the user to paste file contents.
- Greenfield handling: a project with no meaningful code skips Pass 0 with a stated note.
- Research constraints: free/public data by default; no fragile scraping or ToS violations; paid sources only when the user says so.
- Evidence culture: "read the source, never infer from filenames" and the current SKILL.md anti-patterns carry into every new agent prompt. The engine validates the *shape* of an agent's answer, not its *truth* — the prompts stay the truth defense.

## 3. Architecture

Three parts:

1. **The skill (prose, thin).** Entry point and front-of-house. Runs the startup sequence (§4), launches engine bursts with the bundled script, relays checkpoint reviews, runs Pass 5. It no longer contains pass-by-pass orchestration instructions — the script owns that.
2. **The bundled workflow script (JS, shipped in the plugin).** Executes Passes 0–4 as `agent()` calls with JSON-schema outputs. The script itself has **no filesystem access**; every file read/write is done by a subagent. All parallelism lives at the script level (multiple `agent()` calls) — subagents cannot spawn nested subagents, so any multi-agent booster invoked inside a subagent runs in single-agent form (verified empirically).
3. **Pass 5 in the main session.** Visible build with user oversight; asks before commit and push.

**Burst model.** A workflow cannot pause mid-run to talk to the user, so user reviews happen *between* engine invocations ("bursts"). Every burst starts with a **bootstrap reader agent** that loads prior artifacts plus any user checkpoint edits from disk and returns them as structured input to the script. **Disk artifacts are the source of truth; the engine's journal is a disposable same-burst crash cache.** Burst prompts are re-assembled from current artifact contents, so a human edit at a checkpoint naturally invalidates any stale cached prefix.

**Return contract.** A burst returns to the main session only: a short plain-language summary, the list of artifact file paths, counts (candidates/drops/kills/survivors), and any items the human must decide. Never full artifacts inline — that would re-bloat the context the rebuild exists to protect.

## 4. Startup sequence (main session, in order)

1. **Engine gate (Amendment 1).** Check the Workflow tool is actually present in the session's tool list (presence check, not version comparison — catches policy-disabled installs too). If absent: stop with **zero artifacts written** and a plain message stating the required Claude Code version, the user's current version, and the exact update command. Boosters never block; the engine's absence is the one clean refusal. **A prose fallback pipeline is explicitly ruled out** (two implementations would drift apart; do not add one later).
2. **Capability scan (cached).** One-time scan of installed boosters → `~/.claude/discover/environment.json` (outside the plugin dir so updates can't wipe it). Records the Claude Code version; auto-rescans when it changes; `discover: recheck` forces a rescan.
3. **Booster health check (per run, fast, parallel, short timeout).** Codex/Gemini auth can expire. Three states per booster, shown before any work: ✅ present & working (used) · ⚠️ present but broken (LOUD warning + the exact fix command + choice: pause & fix, or proceed without) · absent (silent; built-in used). In **Hands-off** run style the ⚠️ prompt must NOT block: default to proceed-without and put a prominent note in the run output.
4. **Three setup questions** (asked, never silently defaulted; parameter inputs are exempt from the user's no-confirmation rules): **Name** (kebab-case slug = folder + resume key) · **Thoroughness** Light / Standard (default) / Deep (§8 table) · **Run style** Hands-off / Checkpoints (recommended) / Plan-only.
5. **Greenfield detection** (as today): too few source files → skip Pass 0, note it.
6. **Run dir init:** create `.claude/discover/<name>/` with `state.json` carrying a **format version**. Name collision with an existing run dir → offer resume or a new name; never silently overwrite.

## 5. The engine passes

Common rules for every pass: agents return schema-validated JSON; the pass's final synthesizer subagent **writes the pass artifact to disk the moment the pass ends** (all run styles — this is what makes any crash lose at most one pass); **no pass discards a candidate silently** — every drop appends `{candidate, stage, reason-code, one-line reason, evidence-pointer}` to a cumulative drops log.

### Pass 0 — Map
Parallel mapper agents (count by dial) read different parts of the codebase — actual source, never filenames — each returning a structured inventory; one architect agent merges into the system map, marking anything inferred-but-not-verified. Booster: OMC explore/architect agent types if present.

### Pass 1 — Research
Researcher agents (count by dial) search from assigned distinct angles. Rounds are **bounded**: hard cap by dial (Light 2 / Standard 3 / Deep 5) with a dry-stop early exit — after each round a cheap judge agent (small model — haiku/sonnet tier) semantically dedups the round's candidates against the accumulated list and applies a minimum-relevance bar; a round with 0 survivors is "dry"; Light/Standard stop after 1 dry round, Deep after 2 consecutive. Every candidate carries function, rationale, and source-quality grade. Boosters: OMC external-context / sciomc (single-agent form in-engine); superpowers brainstorming stays a *main-session* pre-step when the feature ask is fuzzy.

### Pass 2 — Filter
- **Outcome read-back:** if previous runs on this repo left outcome files (§9), surface prior verdicts next to matching candidates — **surface-only, never auto-kill** (kill reasons go stale).
- **Redundancy gate:** an "already exists" drop is the pipeline's only irreversible early decision, so each one gets an **independent verifier agent** (never the proposing analyst) that must quote the actual code — file + line + snippet — and return a verdict: `exists-fully` (drop stands) / `exists-partially` (convert to "extend existing X") / `stub` (keep; patch the map) / `not-found` (keep). Impact/feasibility drops are judgment calls and need no code evidence — but still log to the drops log.
- Rank survivors on impact + feasibility; **top 3/5/7 by dial** proceed to Pass 3; the rest go to the drops log as `below-cut` with rank preserved.

### Pass 3 — Kill-test (Amendment 2: evidence rule, not majority vote)
1. **Panel:** K skeptics by dial (Light 2 / Standard 3 / Deep 5), one batched `agent()` call per skeptic covering all ideas. No generic skeptics — each gets a distinct named lens bound to an evidence anchor it must actually inspect: **code-reality** (reads the target modules — does the hook point exist as described), **data/API feasibility** (probes the source for real), **maintenance burden for this user**, **security/ToS**, **external-evidence quality** (checks Pass-1 provenance). Light picks the first 2 lenses, Standard 3, Deep all 5.
2. **Kill eligibility** (schema-enforced): an objection may kill only if it is **CONCRETE** (trigger + mechanism + impact), **GROUNDED** (cites an artifact inspected this run: file:line, command output, fetched URL, or a Pass-0 map entry), and **FATAL-CLASS** (exactly one of: `infeasible` / `redundant-verified-in-code` / `unsafeguardable` / `hard-constraint-violation`). Anything failing a test auto-downgrades to a CONCERN.
3. **Decision per idea:** zero kill-eligible objections → SURVIVES; each CONCERN becomes an attached safeguard plus a recorded **demerit** that counts against the idea at the Pass-4 cut. One or more kill-eligible objections → **defense step**: one advocate drafts the strongest rebuttal (tool access allowed), one judge — who first **re-opens the cited evidence** (re-reads the file / re-runs the command) — rules each objection UPHELD (idea dies) / CONVERTED (safeguard + demerit) / REJECTED. **One upheld objection kills. No majority voting in either direction.** Never kill without a defense having run: if budget exhaustion prevents the defense, the objection downgrades to CONCERN-with-flag.
4. **Cross-model auditor** (booster; runs when ≥1 of Codex/Gemini healthy AND dial ≥ Standard): **one batched CLI call per healthy family** (never per-idea), after the panel, covering **survivors + unanimously-killed ideas** (unanimity is where same-family blind spots hide — never disagreement-triggered), capped ~8 ideas by rank, prompt format-matched and carrying the panel's evidence. Output is **advisory only — never a vote** (verdicts must be identical on every machine): "cross-family dissent" flags on survivors; disputed kills move to a "kill disputed — human decision" section. Per-call timeout + per-call degradation, not per-pass.
5. **Reporting (symmetric, every run style):** every kill shows objection + evidence + rebuttal + judge reason; every survivor shows its strongest near-miss objection and how it was resolved. All-Claude verdicts carry a visible **"single-family panel"** label.

### Pass 4 — Plan tournament
- **Entry cap:** top **3** survivors, fixed on every dial (the dial scales search effort, not build scope), ranked by kill-test outcome (fewest/weakest surviving demerits). Survivors 4..N → ranked **build-next backlog** artifact, never deleted.
- **Tournament size:** rival plans Light 1 (no tournament — one plan + one reviewer) / Standard 2 / Deep 3, hard max 3. Skip the tournament when a cheap approach-enumeration call finds fewer than 2 materially distinct architectures.
- **Rivals differ by assigned stance** on identical inputs and one shared plan schema: minimal-diff / robustness-first / extensibility-first.
- **One rubric-anchored judge** (a panel would re-import same-family correlation): isolated absolute scoring per plan + one comparative call. The rubric includes **verified groundedness**: the judge greps each plan's claimed integration points against the real code — otherwise the best-*written* plan wins instead of the most *buildable*.
- **Grafting is additive-only:** the judge's graft list may target only failure handling, activation steps, verification-checklist items, tests, and risk callouts. Component architecture, data structures, data flow, and integration plan are winner-only. A superior structural runner-up idea → the judge either declares that plan the winner or orders exactly ONE bounded revision cycle. Merge by re-generating the plan from winner + graft list, then one separate coherence-check pass. Losing plans and graft decisions surface at the plan review.
- **Plan schema** (engine-validated): the current SKILL.md's 8 sections, plus for **every feature a required `probe` field** — oneOf `live_probe {instruction, expected_evidence}` or `deferred_probe {reason ∈ missing_credential / forward_data / destructive_or_costly (dry-run analog required) / no_runtime_surface / environment_absent, owed_check}`. Schema validation rejects a plan without it.
- In-engine, **the tournament supersedes ralplan** (ralplan cannot fan out inside a subagent; it remains only a mention for main-session use outside discover).

## 6. Run styles

- **Hands-off:** one burst runs Passes 0–4; then Pass 5 after one OK on the plan. Kills and drops surface in the end-of-run summary with paths to the kill report and drops log (never full artifacts inline, per §3); broken-booster prompts don't block (§4.3).
- **Checkpoints (recommended, Amendment 4):** burst A = Passes 0–2 → **shortlist review** (user may drop/edit/add) → burst B = Pass 3 → **adaptive kill stop: pause ONLY if something was killed** (show kills + disputed-kill section; an override re-injects the candidate into Pass 4 WITH the objection and a mandatory safeguard attached) → burst C = Pass 4 → **plan review** → Pass 5. No kills → burst C launches immediately; still two stops.
- **Plan-only:** stop after the plan; `discover: build <name>` later.

## 7. Pass 5 — Build (main session)

1. Read `final-plan.md` + `state.json` (+ `EXECUTE.md` only in separate-session resume, as today).
2. Implement in a loop until the verification checklist passes. Booster: ralph; built-in fallback: implement → test → verify loop with a **verifier agent separate from the implementer**.
3. **Probe gate:** every feature's `live_probe` must be executed and its `expected_evidence` observed and recorded. A `deferred_probe` is honored only after actively verifying the named prerequisite is really absent. `superpowers:verification-before-completion` invoked when present; its evidence standard (fresh evidence in the same message, no completion claims without it) is written into the built-in fallback prompt too.
4. **Ask before commit** — the message enumerates every probe's status, including deferrals. Then push (skip with a note when no remote); on push failure surface the exact next step, never force-push.
5. Write the **outcome file** (§9) and the final report.

## 8. Economics

| Dial | P0 mappers | P1 researchers / round cap / dry-stop | P3 entry cap | P3 skeptics | P4 rival plans | Budget breaker* |
|---|---|---|---|---|---|---|
| Light | 2 + architect | 2 / 2 rounds / 1 dry | 3 | 2 (lenses 1–2) | 1 (no tournament) | ~0.9M CALIBRATE |
| Standard | 3 + architect | 3 / 3 rounds / 1 dry | 5 | 3 (lenses 1–3) | 2 | ~2.5M CALIBRATE |
| Deep | 5 + architect | 4 / 5 rounds / 2 dry | 7 | 5 (all lenses) | 3 | ~6M CALIBRATE |

*Token figures are placeholders marked CALIBRATE — replace from journal data after the Piece-4 toy runs. Cross-model: skipped on Light; one batched call per healthy family on Standard/Deep (§5, Pass 3).

- **Counts come only from the dial — never clamped to core count (Amendment 3).** Cores limit simultaneity; the engine queues overflow (5 skeptics on a 2-slot machine = waves, same quality, longer clock).
- **The budget is a circuit breaker, not a thermostat:** sized ~1.5–2× the dial's expected spend, implied by the dial — no fourth setup question. Power-user override: `discover: <name> budget=N`. It never adjusts thoroughness mid-run.
- **Exhaustion protocol, three layers:** (1) pass-boundary artifact flush (§5 common rules) guarantees a readable trail at any death point; (2) soft gates between passes and between Pass-1 rounds / Pass-3 stages — stop cleanly when `remaining() < next-unit estimate + 10%` (static per-dial estimates, no dynamic forecaster); (3) try/catch backstop on the hard throw returning partial state + the exact one-line resume command.
- **Determinism rule:** agent-call topology (which agents, how many, what prompts) may depend only on run-start constants persisted in `state.json` and on prior agent outputs — **never on live `budget.remaining()`** — so resume-with-a-raised-cap replays the finished prefix from cache instead of re-spending it.
- The breaker meters Claude tokens only; Codex/Gemini CLI calls are invisible to it (documented in README).
- User-facing cost line per dial in plain words at setup time.

## 9. Artifacts & state

```
.claude/discover/<name>/
├── state.json            # format_version, dial, run style, current pass, burst status, booster states
├── pass-0-system-map.md
├── pass-1-candidates.md
├── drops-log.md          # cumulative, all passes: {candidate, stage, reason-code, reason, evidence-pointer}
├── pass-2-filtered.md    # includes redundancy-verifier evidence
├── pass-3-kill-report.md # kills + survivors' near-misses + cross-model section + single-family labels
├── build-next.md         # ranked backlog beyond the top-3 cap
├── final-plan.md         # tournament output incl. probe fields; losing-plan summaries appended
├── EXECUTE.md            # separate-session handoff only (as today)
├── outcome.json          # per candidate: shipped+SHA / killed+reason / deferred — read by future runs (Pass 2)
└── pass-5-execution-log.md
```

- Artifacts written by subagents during the burst (script can't); `state.json` updated by the main session at burst boundaries.
- **Precedence:** disk artifacts > engine journal, always. Journal is used only for same-burst crash recovery, and only while `state.json`'s recorded input hashes still match the artifacts.
- `format_version` in `state.json`: a newer plugin meeting an older or in-flight run dir offers "finish with the old plugin version or restart" — never silent corruption.
- **Hit-rate metrics, telemetry, and auto-tuning are rejected**, not deferred: per-repo sample sizes are too thin to be honest, and nothing could act on them. `outcome.json` is the entire feedback loop — cross-run memory, surface-only.

## 10. Boosters (per pass)

| Pass | Booster when present & healthy | Built-in fallback |
|---|---|---|
| 0 | OMC explore/architect agent types | plain subagents with the same prompts |
| 1 | external-context, sciomc (single-agent form); brainstorming as main-session pre-step | plain research subagents |
| 2 | OMC analyst/critic | plain subagents |
| 3 | Codex/Gemini CLIs as cross-model auditor; security-reviewer lens | Claude-only panel, "single-family" label |
| 4 | — (tournament supersedes ralplan in-engine) | — |
| 5 | ralph; verification-before-completion; git-master | built-in implement/verify loop with separate verifier + its evidence rules |

One line the implementer must respect: **multi-agent boosters run single-agent inside engine subagents; script-level fan-out is the parallelism mechanism.** Booster degradation is per-call with timeouts (a dead Gemini call skips that call, not the pass) and is always reported in the run output, never silent.

## 11. Failure handling & recovery

- **Mid-burst death** (crash, sleep, kill): pass-boundary artifacts + `state.json` mark the last completed pass; `discover: <name>` resumes there. Same-burst re-launch may use the journal cache while input hashes match.
- **Budget exhaustion:** §8 protocol; the user always gets the one-line resume command.
- **Schema-valid garbage:** prompts carry the evidence rules (§2); the kill-test judge re-opens citations; the tournament judge greps integration points; Pass 5's verifier is separate from the implementer.
- **Plugin update mid-run:** `format_version` gate (§9).
- **Greenfield:** Pass 0 skipped with a note; Pass 2's redundancy gate short-circuits (nothing to be redundant with).
- **User aborts:** `state.json` gets `status: aborted`; re-invoking the name offers resume.

## 12. Human-in-the-loop — the always-surface list

Affirmative and closed: pre-run booster status line · everything dropped at any pass, with reasons · kill verdicts + the override path · disputed kills (cross-family) · the plan before build · budget exhaustion + resume command · Pass-5 plan-vs-reality mismatches · push. Everything else runs autonomously and is reported after the fact.

## 13. Explicitly rejected (do not re-add later)

Prose fallback pipeline for engine-less installs · majority-vote kill semantics · per-skeptic advocate pairing (defense convenes only on proposed kills) · judge panels (one judge, both in Pass 3 and Pass 4) · disagreement-triggered cross-model · per-idea cross-model calls · hit-rate metrics / telemetry / auto-tuning · budget as thermostat or any topology dependence on live budget state · a 4th setup question · dial counts clamped to core count · structural grafting between rival plans.

## 14. Testing & verification of the rebuild itself (Piece 4, approved)

1. **End-to-end toy run:** scratch git repo, small toy project; `/discover` Light + Checkpoints through Pass 5; inspect actual artifacts at every gate; judge the plan's buildability by spot-checking its claimed integration points against the toy code.
2. **Branch tests (each a real invocation):** checkpoint edits respected by the next burst · seeded kill → adaptive pause → override lands in the plan · tiny budget → clean death (artifacts + resume command) → resume-with-raised-cap completes without re-spending finished passes · session killed mid-burst → resume from last pass · Codex auth temporarily moved → ⚠️ + exact fix + pause/proceed (and Hands-off proceeds with a note, no stall) · vanilla-user simulation (plugins unavailable; if full simulation is impossible, do the closest real probe and name the residual gap — no silent deferral) · second run on the same repo → outcome read-back surfaces the prior kill · fabricated prose-era run dir → clean old-format message.
3. **Honest deferrals, named:** true engine-absence (cannot downgrade this install — logic + message review instead) · Windows (no machine; README states it).
4. **Separate verifier:** a fresh agent (not the builder) re-runs the toy run + branch matrix and diffs claims vs evidence before "done".
5. Budget CALIBRATE values replaced from the toy runs' journal data.

## 15. Release

- Source of truth: `/root/work/claude-discover-publish/repo/` (skill + script + references). Staging copy updated; version bumped.
- README rewrite: engine model (back room / front), boosters + three-state detection, 3 setup questions, dial table with plain-words cost, run styles, minimum Claude Code version, tmux removed everywhere, tested-on statement, budget-doesn't-meter-Codex/Gemini note.
- `discover.sh` and `references/tmux-layout.md` retired; `references/pass-templates.md` and `kickoff-prompt.md` revised to the new schemas.
- Push to `chopra2007/claude-discover`.
- In this workspace: new TODO item for the build (do not reopen #7); memory updated.

## 16. Notes for the implementation plan (writing-plans input)

- Keep the skill text thin; every rule that governs engine behavior lives in the script + schemas, not prose.
- The five kill-test lenses, the FATAL enum, the probe-reason enum, and the drop reason-codes are closed lists — spell them out in schemas.
- Carry the current SKILL.md's setup-question phrasings (run-name explanation, mode tradeoffs) where they survive. The 5→3 reduction: layout and agent-count questions are removed (the dial + engine replace them); the old mode and execution-handoff questions merge into the single run-style question; thoroughness is new.
- Implementation order suggestion: script skeleton + schemas → burst/bootstrap/artifact plumbing → Pass 3 (most novel) → tournament → skill text + startup sequence → Pass 5 rewrite → Piece-4 test matrix → README/release.
