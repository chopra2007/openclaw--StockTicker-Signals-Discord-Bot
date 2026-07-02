# Discover Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the public `/discover` plugin so Passes 0–4 run as one bundled Workflow-engine script and Pass 5 runs in the main session, per the approved spec.

**Spec (read first, it is the authority):** `docs/superpowers/specs/2026-07-02-discover-rebuild-design.md` (this workspace). Section references (§) below point there.

**Architecture:** One self-contained JS workflow script (`discover-pipeline.js`) executes Passes 0–4 with schema-validated agents, parameterized by `args.from_pass`/`args.to_pass` so the same script serves all run styles (Hands-off = one burst 0–4; Checkpoints = bursts 0–2 / 3 / 4). A thin rewritten SKILL.md is front-of-house: startup gates, launching bursts, relaying checkpoints, Pass 5. All file I/O is done by subagents (the script cannot touch files); disk artifacts under `.claude/discover/<name>/` are the source of truth.

**Tech Stack:** Claude Code Workflow engine (built-in, ≥ 2.1.154), plain JavaScript (no imports, no fs, no Date.now/Math.random in-script), JSON-schema structured outputs, git, node 22 (syntax check + stub harness only).

## Global Constraints (from the spec — every task inherits these)

- Target repo (source of truth to edit): `/root/work/claude-discover-publish/repo/`. Staging copy to keep in sync: `/root/work/claude-discover-publish/extracted/discover-plugin/skills/discover/`. NEVER edit the installed cache (`/root/.claude/plugins/cache/discover/...`) except when syncing for local testing (Task 11).
- Engine floor: Claude Code ≥ 2.1.154, checked by tool-list PRESENCE, not version (§4.1). On absence: stop, zero artifacts, plain message with required version + current version + update command. NO prose fallback pipeline — explicitly rejected (§13).
- The workflow script is ONE self-contained file. No imports. No filesystem access in the script; every read/write happens inside a subagent prompt. No `Date.now()` / `Math.random()` / argless `new Date()`.
- Determinism rule (§8): agent-call topology depends only on `args` + prior agent outputs — never on live budget readings.
- Every pass flushes its artifact to disk via its synthesizer subagent the moment the pass ends (§5). Drops are never silent: every discard appends to `drops-log.md` with `{candidate, stage, reason-code, reason, evidence-pointer}`.
- Kill rule (§5 Pass 3): evidence rule, NOT majority vote. One upheld CONCRETE+GROUNDED+FATAL-CLASS objection kills, after a defense has run. Closed enums exactly as in §5/§16.
- Cross-model (§5 Pass 3.4): advisory only, never a vote; one batched CLI call per healthy family; survivors + unanimous kills; cap 8 ideas; per-call timeout.
- User-facing text (status lines, errors, reports): plain language, jargon translated. All times PDT if any appear.
- Version bump: 0.1.0 → 1.0.0 in BOTH `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`. tmux references removed everywhere (files, tags, descriptions).
- Commit in the PLUGIN repo after every task (imperative style). Do not push until Task 14 (release, with user confirmation).
- Workspace bookkeeping files (this repo): plan checkboxes here; kickoff `todo/kickoffs/discover-rebuild.md` is local-only (gitignored) — update its Status line as tasks land.

## File Structure (end state of the plugin repo)

```
/root/work/claude-discover-publish/repo/
├── .claude-plugin/plugin.json          # v1.0.0, tmux wording removed
├── .claude-plugin/marketplace.json     # v1.0.0, tags updated
├── README.md                           # rewritten (Task 10)
├── LICENSE                             # unchanged
├── tests/run-harness.mjs               # node stub-harness for the script (Task 7)
└── skills/discover/
    ├── SKILL.md                        # rewritten thin front-of-house (Tasks 8–9)
    ├── workflows/discover-pipeline.js  # THE engine script, passes 0–4 (Tasks 1–6)
    └── references/
        ├── pass-templates.md           # rewritten: artifact inventory (Task 9)
        └── kickoff-prompt.md           # revised EXECUTE.md template (Task 9)
    # DELETED: discover.sh, references/tmux-layout.md (Task 1)
```

### The `args` contract (consumed by the script, produced by SKILL.md — used everywhere)

```js
// args = {
//   name: "reddit-sentiment",            // run slug
//   run_dir: "/abs/path/.claude/discover/reddit-sentiment",
//   project_root: "/abs/path",
//   feature_ask: "add reddit sentiment to the trade bot",  // user's words
//   dial: "light" | "standard" | "deep",
//   run_style: "handsoff" | "checkpoints" | "planonly",
//   from_pass: 0, to_pass: 4,            // burst window (checkpoints: 0-2, 3-3, 4-4)
//   greenfield: false,                   // main session detected (§4.5)
//   capabilities: { omc: true, superpowers: true, codex: "healthy"|"broken"|"absent", gemini: "..." },
//   budget_override: null,               // tokens, from "discover: <name> budget=N"
//   free_data_only: true
// }
```

### The return contract (produced by the script, consumed by SKILL.md — §3)

```js
// return {
//   ok: true|false, partial: false,      // partial=true when a gate/exhaustion stopped us early
//   completed_passes: [0,1,2],
//   summary: "plain-language 3-6 sentences",
//   artifacts: ["/abs/.../pass-0-system-map.md", ...],
//   counts: { candidates: 12, drops: 7, kills: 1, survivors: 3 },
//   decisions_needed: ["kill of 'X' disputed by gemini — see kill report"],
//   resume_command: "discover: reddit-sentiment"   // set when partial
// }
```

---

### Task 1: Repo prep — retire tmux, scaffold the script

**Files:**
- Delete: `/root/work/claude-discover-publish/repo/skills/discover/discover.sh`
- Delete: `/root/work/claude-discover-publish/repo/skills/discover/references/tmux-layout.md`
- Create: `/root/work/claude-discover-publish/repo/skills/discover/workflows/discover-pipeline.js`

**Interfaces:**
- Produces: the script file with `meta` and the `args` unpacking that every later task extends. Later tasks insert code at the marked `// === Task N ===` anchors.

- [ ] **Step 1: Delete the tmux artifacts**

```bash
cd /root/work/claude-discover-publish/repo
git rm skills/discover/discover.sh skills/discover/references/tmux-layout.md
```

- [ ] **Step 2: Create the script skeleton**

Write `skills/discover/workflows/discover-pipeline.js`:

```js
export const meta = {
  name: 'discover-pipeline',
  description: 'discover Passes 0-4: map, research, filter, kill-test, plan',
  phases: [
    { title: 'Bootstrap', detail: 'load prior artifacts + user edits from disk' },
    { title: 'Pass 0 - Map', detail: 'parallel mappers + architect merge' },
    { title: 'Pass 1 - Research', detail: 'bounded rounds with dry-stop' },
    { title: 'Pass 2 - Filter', detail: 'redundancy gate + ranking + cut' },
    { title: 'Pass 3 - Kill-test', detail: 'evidence-rule skeptic panel' },
    { title: 'Pass 4 - Plan', detail: 'stance tournament + judge + coherence' },
  ],
}

const A = args
// === Task 2: constants & schemas ===
// === Task 3: plumbing helpers ===
// === Task 4: passes 0-2 ===
// === Task 5: pass 3 ===
// === Task 6: pass 4 + run dispatcher ===
return { ok: true, partial: false, completed_passes: [], summary: 'skeleton', artifacts: [], counts: {}, decisions_needed: [], resume_command: '' }
```

- [ ] **Step 3: Syntax check**

Run: `node --check /root/work/claude-discover-publish/repo/skills/discover/workflows/discover-pipeline.js`
Expected: no output, exit 0. (`export const` at top level is valid module syntax; if node complains about `args`/`return` at top level, that is EXPECTED here — the engine wraps the body in an async function. In that case check syntax of everything below the meta block by wrapping: `node -e "new (Object.getPrototypeOf(async function(){}).constructor)('args','agent','parallel','pipeline','phase','log','budget','workflow', require('fs').readFileSync(process.argv[1],'utf8').replace(/export const meta[\s\S]*?\n}\n/, ''))" <path>` — exit 0 = good. Use whichever form works; record it, all later syntax checks use the same form.)

- [ ] **Step 4: Commit**

```bash
cd /root/work/claude-discover-publish/repo
git add -A && git commit -m "Retire tmux layout; scaffold Workflow-engine pipeline script"
```

---

### Task 2: Script constants and schemas

**Files:**
- Modify: `skills/discover/workflows/discover-pipeline.js` (replace the `// === Task 2 ===` anchor)

**Interfaces:**
- Produces (used by Tasks 3–6, exact names): `DIAL` (resolved object for this run), `LENSES`, `FATAL_CLASSES`, `PROBE_REASONS`, `DROP_CODES`, `PLAN_SECTIONS`, and schemas `S_ACK, S_BOOT, S_MAP, S_CAND, S_DRY, S_RED, S_FILTER, S_SKEPTIC, S_DEFENSE, S_XMODEL, S_KILL, S_APPROACHES, S_PLAN, S_JUDGE, S_COHERE`.

- [ ] **Step 1: Insert constants (verbatim — these encode §8 and the closed enums of §5/§16)**

```js
const DIALS = {
  light:    { mappers: 2, researchers: 2, roundCap: 2, dryStop: 1, p3cap: 3, skeptics: 2, rivals: 1, crossModel: false, breaker: 900_000,   passEst: { 0: 120_000, 1: 200_000, 2: 150_000, 3: 200_000, 4: 200_000 } },
  standard: { mappers: 3, researchers: 3, roundCap: 3, dryStop: 1, p3cap: 5, skeptics: 3, rivals: 2, crossModel: true,  breaker: 2_500_000, passEst: { 0: 300_000, 1: 500_000, 2: 400_000, 3: 600_000, 4: 600_000 } },
  deep:     { mappers: 5, researchers: 4, roundCap: 5, dryStop: 2, p3cap: 7, skeptics: 5, rivals: 3, crossModel: true,  breaker: 6_000_000, passEst: { 0: 600_000, 1: 1_200_000, 2: 800_000, 3: 1_600_000, 4: 1_600_000 } },
} // token figures = CALIBRATE placeholders; replaced from journal data in Task 12
const DIAL = DIALS[A.dial]
const P4CAP = 3 // fixed on every dial (spec §5 Pass 4)

const LENSES = [ // order matters: light uses first 2, standard first 3, deep all 5 (spec §5 Pass 3.1)
  { key: 'code-reality',      anchor: 'Read the actual target modules and integration points named in the system map. A kill from this lens must quote file:line proving the hook point does not exist as the idea assumes.' },
  { key: 'data-api',          anchor: 'Probe the data source or API for real (curl/CLI/read the client code). A kill must show the actual probe output proving the data is unavailable, paywalled, or rate-limited beyond use.' },
  { key: 'maintenance',       anchor: 'Read the repo size, test setup, and this user\'s constraints from the system map. A kill must ground in specifics of THIS repo, not generic burden claims.' },
  { key: 'security-tos',      anchor: 'Check terms of service / auth / scraping reality of the sources involved (fetch the ToS or docs). A kill must cite the fetched text.' },
  { key: 'evidence-quality',  anchor: 'Re-check the Pass-1 provenance of the idea: open the cited sources. A kill must show the source does not support the claimed benefit.' },
]
const FATAL_CLASSES = ['infeasible', 'redundant-verified-in-code', 'unsafeguardable', 'hard-constraint-violation']
const PROBE_REASONS = ['missing_credential', 'forward_data', 'destructive_or_costly', 'no_runtime_surface', 'environment_absent']
const DROP_CODES = ['already-exists-verified', 'below-cut', 'kill-upheld', 'dry-round-dedup', 'user-dropped', 'infeasible-early']
const PLAN_SECTIONS = ['System Overview', 'Component Architecture', 'Data Flow Pipeline', 'Data Structures', 'Integration Plan', 'Failure Handling', 'Feature Activation Plan', 'Verification Checklist']
```

- [ ] **Step 2: Insert schemas (verbatim)**

```js
const S_ACK = { type: 'object', required: ['path', 'summary'], properties: { path: { type: 'string' }, summary: { type: 'string' } } }
const S_BOOT = { type: 'object', required: ['found', 'artifacts', 'user_edits'], properties: {
  found: { type: 'boolean' },
  artifacts: { type: 'object', properties: { map: { type: 'string' }, candidates: { type: 'string' }, filtered: { type: 'string' }, kill_report: { type: 'string' }, drops: { type: 'string' }, outcomes_prior: { type: 'string' } }, description: 'full text content of each artifact file that exists, keyed as named' },
  user_edits: { type: 'string', description: 'verbatim content of checkpoint-edits.md if present, else empty' } } }
const CAND = { type: 'object', required: ['id', 'name', 'function', 'rationale', 'source_quality'], properties: {
  id: { type: 'string' }, name: { type: 'string' }, function: { type: 'string' }, rationale: { type: 'string' },
  source_quality: { type: 'string', enum: ['high', 'medium', 'low'] }, sources: { type: 'array', items: { type: 'string' } } } }
const S_MAP = { type: 'object', required: ['components', 'data_sources', 'gaps', 'unverified'], properties: {
  components: { type: 'array', items: { type: 'object', required: ['name', 'path', 'does'], properties: { name: { type: 'string' }, path: { type: 'string' }, does: { type: 'string' } } } },
  data_sources: { type: 'array', items: { type: 'string' } }, gaps: { type: 'array', items: { type: 'string' } },
  unverified: { type: 'array', items: { type: 'string' }, description: 'anything inferred from naming, not read' } } }
const S_CAND = { type: 'object', required: ['candidates'], properties: { candidates: { type: 'array', items: CAND } } }
const S_DRY = { type: 'object', required: ['new_candidates', 'dry'], properties: { new_candidates: { type: 'array', items: CAND }, dry: { type: 'boolean' } } }
const S_RED = { type: 'object', required: ['verdict', 'evidence'], properties: {
  verdict: { type: 'string', enum: ['exists-fully', 'exists-partially', 'stub', 'not-found'] },
  evidence: { type: 'string', description: 'file path + line numbers + quoted snippet actually read' },
  extend_note: { type: 'string', description: 'when exists-partially: what to extend' } } }
const S_FILTER = { type: 'object', required: ['kept', 'drops'], properties: {
  kept: { type: 'array', items: { type: 'object', required: ['id', 'name', 'rank', 'failure_modes', 'safeguards', 'prior_outcome'], properties: { id: { type: 'string' }, name: { type: 'string' }, rank: { type: 'number' }, failure_modes: { type: 'array', items: { type: 'string' } }, safeguards: { type: 'array', items: { type: 'string' } }, prior_outcome: { type: 'string', description: 'from outcome read-back, or empty' } } } },
  drops: { type: 'array', items: { type: 'object', required: ['id', 'name', 'code', 'reason', 'evidence'], properties: { id: { type: 'string' }, name: { type: 'string' }, code: { type: 'string', enum: DROP_CODES }, reason: { type: 'string' }, evidence: { type: 'string' } } } } } }
const OBJ = { type: 'object', required: ['candidate_id', 'lens', 'kind', 'trigger', 'mechanism', 'impact', 'evidence', 'fatal_class'], properties: {
  candidate_id: { type: 'string' }, lens: { type: 'string' },
  kind: { type: 'string', enum: ['kill-eligible', 'concern'] },
  trigger: { type: 'string' }, mechanism: { type: 'string' }, impact: { type: 'string' },
  evidence: { type: 'string', description: 'REQUIRED artifact inspected THIS run: file:line / command + output / fetched URL / map entry. Empty or generic => auto-downgrade to concern.' },
  fatal_class: { type: 'string', enum: [...FATAL_CLASSES, 'none'] } } }
const S_SKEPTIC = { type: 'object', required: ['objections', 'endorsements'], properties: { objections: { type: 'array', items: OBJ }, endorsements: { type: 'array', items: { type: 'string' }, description: 'candidate_ids with no objection from this lens' } } }
const S_DEFENSE = { type: 'object', required: ['rulings'], properties: { rulings: { type: 'array', items: { type: 'object', required: ['candidate_id', 'objection_ref', 'ruling', 'reason', 'evidence_recheck'], properties: { candidate_id: { type: 'string' }, objection_ref: { type: 'string' }, ruling: { type: 'string', enum: ['UPHELD', 'CONVERTED', 'REJECTED'] }, reason: { type: 'string' }, evidence_recheck: { type: 'string', description: 'what the judge saw when it re-opened the cited evidence' } } } } } }
const S_XMODEL = { type: 'object', required: ['family', 'available', 'notes'], properties: { family: { type: 'string' }, available: { type: 'boolean' }, notes: { type: 'array', items: { type: 'object', required: ['candidate_id', 'stance', 'note'], properties: { candidate_id: { type: 'string' }, stance: { type: 'string', enum: ['endorse', 'dissent', 'dispute-kill'] }, note: { type: 'string' } } } } } }
const S_KILL = { type: 'object', required: ['survivors', 'kills'], properties: {
  survivors: { type: 'array', items: { type: 'object', required: ['id', 'name', 'demerits', 'safeguards', 'near_miss', 'cross_family'], properties: { id: { type: 'string' }, name: { type: 'string' }, demerits: { type: 'number' }, safeguards: { type: 'array', items: { type: 'string' } }, near_miss: { type: 'string', description: 'strongest objection raised and how it was resolved' }, cross_family: { type: 'string' } } } },
  kills: { type: 'array', items: { type: 'object', required: ['id', 'name', 'objection', 'evidence', 'rebuttal', 'judge_reason', 'disputed_by'], properties: { id: { type: 'string' }, name: { type: 'string' }, objection: { type: 'string' }, evidence: { type: 'string' }, rebuttal: { type: 'string' }, judge_reason: { type: 'string' }, disputed_by: { type: 'string', description: 'cross-model family disputing this kill, or empty' } } } } } }
const S_APPROACHES = { type: 'object', required: ['distinct_architectures'], properties: { distinct_architectures: { type: 'number' }, notes: { type: 'string' } } }
const S_PLAN = { type: 'object', required: ['stance', 'sections', 'features'], properties: {
  stance: { type: 'string' },
  sections: { type: 'object', required: PLAN_SECTIONS.map(s => s), properties: Object.fromEntries(PLAN_SECTIONS.map(s => [s, { type: 'string' }])) },
  features: { type: 'array', items: { type: 'object', required: ['name', 'probe'], properties: { name: { type: 'string' }, probe: { type: 'object', required: ['kind'], properties: { kind: { type: 'string', enum: ['live_probe', 'deferred_probe'] }, instruction: { type: 'string' }, expected_evidence: { type: 'string' }, reason: { type: 'string', enum: [...PROBE_REASONS, ''] }, owed_check: { type: 'string' } } } } } } } }
const S_JUDGE = { type: 'object', required: ['winner_stance', 'scores', 'grounded_findings', 'graft_list', 'revision_order'], properties: {
  winner_stance: { type: 'string' },
  scores: { type: 'array', items: { type: 'object', required: ['stance', 'score', 'reason'], properties: { stance: { type: 'string' }, score: { type: 'number' }, reason: { type: 'string' } } } },
  grounded_findings: { type: 'string', description: 'what the judge found when grepping each plan\'s claimed integration points against real code' },
  graft_list: { type: 'array', items: { type: 'object', required: ['from_stance', 'target_section', 'item'], properties: { from_stance: { type: 'string' }, target_section: { type: 'string', enum: ['Failure Handling', 'Feature Activation Plan', 'Verification Checklist', 'tests', 'risk-callouts'] }, item: { type: 'string' } } } },
  revision_order: { type: 'string', description: 'ONE bounded structural revision instruction, or empty' } } }
const S_COHERE = { type: 'object', required: ['coherent', 'fixes_applied'], properties: { coherent: { type: 'boolean' }, fixes_applied: { type: 'array', items: { type: 'string' } } } }
```

- [ ] **Step 3: Syntax check** — same command as Task 1 Step 3. Expected: exit 0.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "Add pipeline constants, closed enums, and structured-output schemas"`

---

### Task 3: Plumbing helpers — evidence preamble, synthesizer writes, budget gates, drop log

**Files:**
- Modify: `skills/discover/workflows/discover-pipeline.js` (replace `// === Task 3 ===`)

**Interfaces:**
- Consumes: `DIAL`, schemas (Task 2).
- Produces (exact signatures): `PRE` (string), `used()`, `gate(passNo)` → bool, `synth(passTitle, fileName, bodySpec, phase)` → Promise<{path,summary}>, `appendDrops(dropsArr, phase)` → Promise, `bootstrap()` → Promise<S_BOOT-shaped>, `partialReturn(completed, why)` → return-contract object, `RUNSTATE` (mutable {artifacts:[], counts:{...}, decisions:[]}).

- [ ] **Step 1: Insert helpers (verbatim)**

```js
const PRE = `You are part of the "discover" feature-discovery pipeline, run ${A.name}, working on the project at ${A.project_root}.
The feature ask: ${A.feature_ask}
Run directory for artifacts: ${A.run_dir}
EVIDENCE RULES (non-negotiable): Read actual source before claiming anything about the code - NEVER infer functionality from filenames (a stub file is a gap, not a feature). Free/public data only${A.free_data_only ? '' : ' EXCEPT the user has allowed paid sources'}; no fragile scraping or ToS violations. Cite what you inspected (file:line, command + output, URL). Your final structured output is consumed by a program - be precise, no padding.`

const spent0 = budget.spent()
const used = () => budget.spent() - spent0
const BREAKER = A.budget_override || DIAL.breaker
const gate = passNo => used() + DIAL.passEst[passNo] * 1.1 <= BREAKER

const RUNSTATE = { artifacts: [], counts: { candidates: 0, drops: 0, kills: 0, survivors: 0 }, decisions: [] }

async function synth(passTitle, fileName, bodySpec, phase) {
  const r = await agent(`${PRE}
You are the ${passTitle} synthesizer. Write the artifact file ${A.run_dir}/${fileName} (create/overwrite) with the content described below, formatted as clean human-readable markdown with plain-language section intros (the plugin author is not a coder). Then return {path, summary} where summary is 2-4 plain sentences.
CONTENT SPEC:
${bodySpec}`, { label: `synth:${fileName}`, phase, schema: S_ACK })
  if (r && r.path) RUNSTATE.artifacts.push(r.path)
  return r
}

async function appendDrops(drops, phase) {
  if (!drops.length) return
  RUNSTATE.counts.drops += drops.length
  await agent(`${PRE}
APPEND (never overwrite; create if missing) to ${A.run_dir}/drops-log.md one markdown bullet per item below, format: "- **<name>** [<stage> / <code>] <reason> - evidence: <evidence>". Items (JSON): ${JSON.stringify(drops)}
Return {path, summary}.`, { label: 'synth:drops-log', phase, schema: S_ACK })
}

async function bootstrap() {
  return await agent(`${PRE}
You are the burst bootstrap reader. Read the run directory ${A.run_dir} (it may not exist yet - then found=false).
Return the FULL TEXT of each of these files that exists, in artifacts keyed exactly: map=pass-0-system-map.md, candidates=pass-1-candidates.md, filtered=pass-2-filtered.md, kill_report=pass-3-kill-report.md, drops=drops-log.md. Also key outcomes_prior = concatenated content of outcome.json files from OTHER run dirs under ${A.project_root}/.claude/discover/*/outcome.json (empty string if none).
user_edits = verbatim content of ${A.run_dir}/checkpoint-edits.md if it exists (the human's checkpoint decisions - these OVERRIDE artifact content), else "".`, { label: 'bootstrap', phase: 'Bootstrap', schema: S_BOOT })
}

function partialReturn(completed, why) {
  return { ok: false, partial: true, completed_passes: completed, summary: why + ` Everything finished so far is saved in ${A.run_dir}. Resume with the command below - completed work will not be re-paid.`, artifacts: RUNSTATE.artifacts, counts: RUNSTATE.counts, decisions_needed: RUNSTATE.decisions, resume_command: `discover: ${A.name}` }
}
```

- [ ] **Step 2: Syntax check** (same as before). Expected: exit 0.
- [ ] **Step 3: Commit** — `git commit -am "Add pipeline plumbing: bootstrap reader, synthesizer writes, budget gates, drop log"`

---

### Task 4: Passes 0–2 (burst A)

**Files:**
- Modify: `skills/discover/workflows/discover-pipeline.js` (replace `// === Task 4 ===`)

**Interfaces:**
- Consumes: everything from Tasks 2–3.
- Produces: `async passMap()` → S_MAP-shaped, `async passResearch(map)` → {candidates}, `async passFilter(map, candidates, priorOutcomes, userEdits)` → S_FILTER-shaped `{kept, drops}` where `kept` is already cut to `DIAL.p3cap`.

- [ ] **Step 1: Insert Pass 0 (verbatim)**

```js
async function passMap() {
  phase('Pass 0 - Map')
  if (A.greenfield) { log('greenfield project - Pass 0 skipped (nothing to map)'); return { components: [], data_sources: [], gaps: ['greenfield - no existing system'], unverified: [] } }
  const views = await parallel(Array.from({ length: DIAL.mappers }, (_, i) => () =>
    agent(`${PRE}
You are codebase mapper ${i + 1} of ${DIAL.mappers}. Divide the repo mentally into ${DIAL.mappers} slices by top-level directory order and take slice ${i + 1}. READ the actual source files in your slice (entrypoints, core modules, config). Mark anything you did not actually read as unverified.`,
      { label: `mapper-${i + 1}`, phase: 'Pass 0 - Map', schema: S_MAP })))
  const merged = await agent(`${PRE}
You are the architect. Merge these mapper inventories into ONE faithful system map (dedupe, resolve conflicts by re-reading the disputed file yourself). Keep the unverified list honest.
MAPPER OUTPUTS: ${JSON.stringify(views.filter(Boolean))}`, { label: 'architect-merge', phase: 'Pass 0 - Map', schema: S_MAP })
  await synth('Pass 0', 'pass-0-system-map.md', `Component inventory, data sources, gaps (only truly absent things), and an "inferred but not verified" section. JSON to render: ${JSON.stringify(merged)}`, 'Pass 0 - Map')
  return merged
}
```

- [ ] **Step 2: Insert Pass 1 (verbatim)**

```js
async function passResearch(map) {
  phase('Pass 1 - Research')
  const angles = ['how similar open-source systems solve this', 'academic/industry patterns and their tradeoffs', 'data sources and APIs that could power it', 'failure stories and anti-patterns from practitioners']
  let all = []
  let dry = 0
  for (let round = 1; round <= DIAL.roundCap; round++) {
    const found = await parallel(Array.from({ length: DIAL.researchers }, (_, i) => () =>
      agent(`${PRE}
You are researcher ${i + 1}, round ${round}. Your angle: ${angles[i % angles.length]}. Search the web and read real sources. The system already has (do NOT propose): ${JSON.stringify(map.components.map(c => c.name))}. Already found this run (do NOT repeat): ${JSON.stringify(all.map(c => c.name))}. Return candidate features with function, rationale, source_quality (high=peer-reviewed/production-validated, medium=widely-used pattern, low=blog-grade), sources.`,
        { label: `researcher-${i + 1}-r${round}`, phase: 'Pass 1 - Research', schema: S_CAND })))
    const roundCands = found.filter(Boolean).flatMap(f => f.candidates)
    const judged = await agent(`${PRE}
You are the round judge (cheap dedup). Existing list: ${JSON.stringify(all)}. New this round: ${JSON.stringify(roundCands)}. Return new_candidates = only genuinely new, relevant-to-the-ask items (semantic dedup, drop off-topic), and dry = true iff new_candidates is empty.`,
      { label: `dry-judge-r${round}`, phase: 'Pass 1 - Research', schema: S_DRY, model: 'haiku' })
    if (!judged || judged.dry) { dry++; if (dry >= DIAL.dryStop) { log(`round ${round} dry - research complete`); break } }
    else { dry = 0; all = all.concat(judged.new_candidates) }
    if (!gate(1)) break
  }
  all = all.map((c, i) => ({ ...c, id: `c${i + 1}` }))
  RUNSTATE.counts.candidates = all.length
  await synth('Pass 1', 'pass-1-candidates.md', `Full unfiltered candidate list with function/rationale/source-quality/sources. JSON: ${JSON.stringify(all)}`, 'Pass 1 - Research')
  return all
}
```

- [ ] **Step 3: Insert Pass 2 (verbatim)**

```js
async function passFilter(map, candidates, priorOutcomes, userEdits) {
  phase('Pass 2 - Filter')
  const analysis = await agent(`${PRE}
You are the filter analyst. For each candidate: (a) if you believe it already exists in the system, put it in drops with code "already-exists-verified" and name the map entry - it will be independently verified, so only claim it when the map really says so; (b) list failure modes + safeguards; (c) rank the rest on impact + feasibility (rank 1 = best). Never drop for weak/low-impact silently - use code "below-cut" with a one-line reason.
${priorOutcomes ? `PRIOR RUN OUTCOMES on this repo (surface next to matching candidates as prior_outcome - NEVER auto-drop because of them, reasons go stale): ${priorOutcomes}` : ''}
${userEdits ? `HUMAN CHECKPOINT EDITS (these OVERRIDE everything - apply them literally, log removed items with code "user-dropped"): ${userEdits}` : ''}
SYSTEM MAP: ${JSON.stringify(map)}
CANDIDATES: ${JSON.stringify(candidates)}`, { label: 'filter-analyst', phase: 'Pass 2 - Filter', schema: S_FILTER })
  const claimed = analysis.drops.filter(d => d.code === 'already-exists-verified')
  const verified = await parallel(claimed.map(d => () =>
    agent(`${PRE}
You are an independent redundancy verifier (you did NOT propose this drop). Claim: candidate "${d.name}" (${JSON.stringify(candidates.find(c => c.id === d.id) || d)}) already exists in this codebase. Locate and READ the actual source yourself - do not trust the map. Quote file + lines + snippet. Verdict: exists-fully (drop stands) / exists-partially (keep as "extend existing X") / stub (looks built, is not - keep) / not-found (keep).`,
      { label: `redundancy:${d.name.slice(0, 30)}`, phase: 'Pass 2 - Filter', schema: S_RED }).then(v => ({ d, v }))))
  const drops = analysis.drops.filter(x => x.code !== 'already-exists-verified')
  let kept = analysis.kept
  for (const { d, v } of verified.filter(Boolean)) {
    if (v.verdict === 'exists-fully') drops.push({ ...d, evidence: v.evidence })
    else kept.push({ id: d.id, name: v.verdict === 'exists-partially' ? `Extend existing: ${d.name} (${v.extend_note})` : d.name, rank: kept.length + 1, failure_modes: [], safeguards: [], prior_outcome: v.verdict === 'stub' ? 'stub found - map patched' : '' })
  }
  kept = kept.sort((x, y) => x.rank - y.rank)
  const cut = kept.slice(DIAL.p3cap).map(k => ({ id: k.id, name: k.name, code: 'below-cut', reason: `ranked ${k.rank}, cap ${DIAL.p3cap}`, evidence: '' }))
  kept = kept.slice(0, DIAL.p3cap)
  await appendDrops(drops.concat(cut).map(d => ({ ...d, stage: 'pass-2' })), 'Pass 2 - Filter')
  await synth('Pass 2', 'pass-2-filtered.md', `Kept candidates (ranked, with failure modes, safeguards, prior-outcome notes) and the redundancy-verifier evidence. kept=${JSON.stringify(kept)} verifier_evidence=${JSON.stringify(verified.filter(Boolean).map(x => ({ name: x.d.name, verdict: x.v.verdict, evidence: x.v.evidence })))}`, 'Pass 2 - Filter')
  return { kept, drops }
}
```

- [ ] **Step 4: Syntax check** (same as before). Expected: exit 0.
- [ ] **Step 5: Commit** — `git commit -am "Implement Passes 0-2: map, bounded research rounds, filter with redundancy gate"`

---

### Task 5: Pass 3 — kill-test (burst B)

**Files:**
- Modify: `skills/discover/workflows/discover-pipeline.js` (replace `// === Task 5 ===`)

**Interfaces:**
- Consumes: Tasks 2–4 names.
- Produces: `async passKill(map, kept)` → S_KILL-shaped `{survivors, kills}`.

- [ ] **Step 1: Insert Pass 3 (verbatim)**

```js
async function passKill(map, kept) {
  phase('Pass 3 - Kill-test')
  const lenses = LENSES.slice(0, DIAL.skeptics)
  const panel = (await parallel(lenses.map(l => () =>
    agent(`${PRE}
You are the ${l.key} skeptic. Try to disprove EACH candidate below through your lens ONLY. Your evidence anchor - you MUST actually do this before objecting: ${l.anchor}
An objection is kill-eligible ONLY if all three hold: CONCRETE (trigger + mechanism + impact), GROUNDED (evidence field cites an artifact you inspected THIS run), FATAL-CLASS (exactly one of ${FATAL_CLASSES.join(' / ')}). Otherwise mark kind=concern, fatal_class=none. Do not manufacture objections - explicit endorsement is a valid result.
SYSTEM MAP: ${JSON.stringify(map)}
CANDIDATES: ${JSON.stringify(kept)}`, { label: `skeptic:${l.key}`, phase: 'Pass 3 - Kill-test', schema: S_SKEPTIC })))).filter(Boolean)
  let objections = panel.flatMap(p => p.objections)
    .map((o, i) => ({ ...o, ref: `o${i + 1}`, kind: (o.kind === 'kill-eligible' && o.evidence && o.evidence.length > 20 && FATAL_CLASSES.includes(o.fatal_class)) ? 'kill-eligible' : 'concern' }))
  const killable = objections.filter(o => o.kind === 'kill-eligible')
  let rulings = []
  if (killable.length) {
    if (!gate(3)) { objections = objections.map(o => ({ ...o, kind: 'concern', budget_flagged: true })); log('budget guard: defense cannot run - kill-eligible objections downgraded to flagged concerns (never kill without a defense)') }
    else {
      const defense = await agent(`${PRE}
You are the advocate. For each kill-eligible objection below, draft the strongest honest rebuttal (tool access allowed - read the code, probe the source).
OBJECTIONS: ${JSON.stringify(killable)}
CANDIDATES: ${JSON.stringify(kept)}
Return your rebuttals inside rulings with ruling=REJECTED and reason=your rebuttal (the judge will overwrite ruling).`, { label: 'advocate', phase: 'Pass 3 - Kill-test', schema: S_DEFENSE })
      const judged = await agent(`${PRE}
You are the judge. For each objection: FIRST re-open its cited evidence yourself (re-read the file / re-run the command / re-fetch the URL) and record what you saw in evidence_recheck. Then, weighing the advocate's rebuttal, rule UPHELD (candidate dies) / CONVERTED (becomes safeguard + demerit) / REJECTED. An objection whose evidence does not check out is REJECTED. One UPHELD objection kills - there is no vote.
OBJECTIONS: ${JSON.stringify(killable)}
ADVOCATE REBUTTALS: ${JSON.stringify(defense ? defense.rulings : [])}`, { label: 'judge', phase: 'Pass 3 - Kill-test', schema: S_DEFENSE })
      rulings = judged ? judged.rulings : []
    }
  }
  const killedIds = new Set(rulings.filter(r => r.ruling === 'UPHELD').map(r => r.candidate_id))
  const singleFamily = !(DIAL.crossModel && (A.capabilities.codex === 'healthy' || A.capabilities.gemini === 'healthy'))
  let xnotes = []
  if (!singleFamily) {
    const unanimousKills = kept.filter(k => killedIds.has(k.id))
    const survivors = kept.filter(k => !killedIds.has(k.id))
    const batch = survivors.concat(unanimousKills).slice(0, 8)
    const families = [['codex', 'timeout 240 codex exec'], ['gemini', 'GEMINI_CLI_TRUST_WORKSPACE=true timeout 240 gemini -p']].filter(([f]) => A.capabilities[f] === 'healthy')
    xnotes = (await parallel(families.map(([fam, cli]) => () =>
      agent(`${PRE}
You are the cross-model auditor for ${fam}. Compose ONE batched prompt covering all ideas below (include the panel's evidence per idea; for killed ideas attach the kill's failure scenario and ask "is this stated failure scenario factually correct for this system?"). Run it via bash: ${cli} "<your prompt>" . If the CLI errors or times out, return available=false. Parse the reply into per-candidate notes: endorse / dissent (for survivors) / dispute-kill (for killed ones). Advisory only - you are NOT a vote.
IDEAS: ${JSON.stringify(batch)}
KILL RULINGS: ${JSON.stringify(rulings)}`, { label: `xmodel:${fam}`, phase: 'Pass 3 - Kill-test', schema: S_XMODEL })))).filter(Boolean).filter(x => x.available)
  }
  const survivors = kept.filter(k => !killedIds.has(k.id)).map(k => {
    const mine = objections.filter(o => o.candidate_id === k.id)
    const conv = rulings.filter(r => r.candidate_id === k.id && r.ruling === 'CONVERTED')
    const strongest = mine[0]
    return { id: k.id, name: k.name, demerits: mine.filter(o => o.kind === 'concern').length + conv.length,
      safeguards: (k.safeguards || []).concat(mine.filter(o => o.kind === 'concern').map(o => `guard against: ${o.trigger}`)),
      near_miss: strongest ? `${strongest.lens}: ${strongest.trigger} -> resolved: ${rulings.find(r => r.objection_ref === strongest.ref)?.reason || 'concern, safeguard attached'}` : 'no objections raised',
      cross_family: xnotes.flatMap(x => x.notes.filter(n => n.candidate_id === k.id && n.stance === 'dissent').map(n => `${x.family} dissent: ${n.note}`)).join('; ') }
  })
  const kills = kept.filter(k => killedIds.has(k.id)).map(k => {
    const r = rulings.find(x => x.candidate_id === k.id && x.ruling === 'UPHELD')
    const o = objections.find(x => x.ref === r.objection_ref) || {}
    return { id: k.id, name: k.name, objection: `${o.lens}: ${o.trigger} -> ${o.mechanism} -> ${o.impact}`, evidence: o.evidence || '', rebuttal: r.reason, judge_reason: `${r.reason} | recheck: ${r.evidence_recheck}`,
      disputed_by: xnotes.flatMap(x => x.notes.filter(n => n.candidate_id === k.id && n.stance === 'dispute-kill').map(n => x.family)).join(',') }
  })
  RUNSTATE.counts.kills = kills.length; RUNSTATE.counts.survivors = survivors.length
  kills.filter(k => k.disputed_by).forEach(k => RUNSTATE.decisions.push(`kill of "${k.name}" disputed by ${k.disputed_by} - human decision (see kill report)`))
  await appendDrops(kills.map(k => ({ name: k.name, stage: 'pass-3', code: 'kill-upheld', reason: k.objection, evidence: k.evidence })), 'Pass 3 - Kill-test')
  await synth('Pass 3', 'pass-3-kill-report.md', `${singleFamily ? 'LABEL PROMINENTLY AT TOP: "single-family panel - all verdicts are from one AI family; unanimity counts for less." ' : ''}Sections: KILLS (each: objection + evidence + rebuttal + judge reason + disputed_by flag), SURVIVORS (each: demerits, safeguards, near_miss - the strongest objection and its resolution, cross_family notes). Symmetric reporting is mandatory. JSON: ${JSON.stringify({ survivors, kills })}`, 'Pass 3 - Kill-test')
  return { survivors, kills }
}
```

- [ ] **Step 2: Syntax check.** Expected: exit 0.
- [ ] **Step 3: Commit** — `git commit -am "Implement Pass 3: lens skeptics, evidence-rule kills, advocate+judge, cross-model auditor"`

---

### Task 6: Pass 4 tournament + run dispatcher

**Files:**
- Modify: `skills/discover/workflows/discover-pipeline.js` (replace `// === Task 6 ===` AND the placeholder `return` from Task 1)

**Interfaces:**
- Consumes: all prior names.
- Produces: `async passPlan(map, survivors)` → {plan_path}; the final top-level `run()` flow and return contract.

- [ ] **Step 1: Insert Pass 4 (verbatim)**

```js
async function passPlan(map, survivors) {
  phase('Pass 4 - Plan')
  const ranked = [...survivors].sort((x, y) => x.demerits - y.demerits)
  const chosen = ranked.slice(0, P4CAP)
  const backlog = ranked.slice(P4CAP)
  if (backlog.length) await synth('Pass 4', 'build-next.md', `Ranked backlog of survivors beyond the top-${P4CAP} build cap (never deleted; promotable by the human next run). JSON: ${JSON.stringify(backlog)}`, 'Pass 4 - Plan')
  const STANCES = ['minimal-diff', 'robustness-first', 'extensibility-first'].slice(0, DIAL.rivals)
  let rivals
  if (DIAL.rivals > 1) {
    const enu = await agent(`${PRE}
Quick check: for integrating ${JSON.stringify(chosen.map(c => c.name))} into this system (map: ${JSON.stringify(map.components)}), how many MATERIALLY DISTINCT architectures exist? Distinct = different integration points or data flow, not different polish.`, { label: 'approach-enum', phase: 'Pass 4 - Plan', schema: S_APPROACHES, model: 'haiku' })
    if (enu && enu.distinct_architectures < 2) { log('approach space is narrow - tournament skipped, single plan'); rivals = [STANCES[0]] } else rivals = STANCES
  } else rivals = [STANCES[0]]
  const planPrompt = stance => `${PRE}
You are the ${stance} planner. Produce a build-ready plan integrating the features below into the existing system without duplicating anything. Your assigned stance - optimize for: ${stance === 'minimal-diff' ? 'the smallest correct change; touch the fewest files' : stance === 'robustness-first' ? 'failure handling, safeguards, and observability' : 'clean seams for future features'}. READ the actual integration-point code before naming file paths or signatures. Every plan section required. EVERY feature needs a probe: live_probe {instruction: exact command/action, expected_evidence: what output proves it works} or deferred_probe {reason from ${PROBE_REASONS.join('/')}, owed_check}. destructive_or_costly REQUIRES a dry-run analog in instruction.
FEATURES (with safeguards to bake in): ${JSON.stringify(chosen)}
SYSTEM MAP: ${JSON.stringify(map)}`
  const plans = (await parallel(rivals.map(s => () => agent(planPrompt(s), { label: `plan:${s}`, phase: 'Pass 4 - Plan', schema: S_PLAN })))).filter(Boolean)
  let final = plans[0], judge = null
  if (plans.length > 1) {
    judge = await agent(`${PRE}
You are the single tournament judge. Rubric per plan, scored 1-10 each, in isolation first: buildability (are named files/functions real - GREP THE CODE for each plan's claimed integration points, record findings in grounded_findings), completeness (all sections + probes), risk handling, fit-to-stance. Then ONE comparative pass -> winner_stance. graft_list: ONLY additive items from losers (allowed target sections: Failure Handling / Feature Activation Plan / Verification Checklist / tests / risk-callouts). Structural superiority of a loser => either declare it winner or put ONE bounded instruction in revision_order - structural ideas are NEVER grafted.
PLANS: ${JSON.stringify(plans)}`, { label: 'tournament-judge', phase: 'Pass 4 - Plan', schema: S_JUDGE })
    const winner = plans.find(p => p.stance === judge.winner_stance) || plans[0]
    final = await agent(`${PRE}
You are the plan reviser. Re-generate the winning plan as ONE coherent whole: apply the graft list (additive items only, into their target sections)${judge.revision_order ? ' and this single structural revision: ' + judge.revision_order : ''}. Do not import any other loser ideas.
WINNER: ${JSON.stringify(winner)}
GRAFTS: ${JSON.stringify(judge.graft_list)}`, { label: 'plan-reviser', phase: 'Pass 4 - Plan', schema: S_PLAN })
    const co = await agent(`${PRE}
Coherence check on the merged plan: contradictions between sections, grafted items that don't fit, features without probes. Fix what you find and report fixes_applied. PLAN: ${JSON.stringify(final)}`, { label: 'coherence-check', phase: 'Pass 4 - Plan', schema: S_COHERE })
    if (co && co.fixes_applied.length) log(`coherence pass applied ${co.fixes_applied.length} fixes`)
  }
  await synth('Pass 4', 'final-plan.md', `The build spec Pass 5 reads. Render all 8 sections in order, then a "Feature Probes" section listing every feature's probe verbatim, then (if a tournament ran) "Tournament notes": scores table, grounded_findings, graft decisions, losing-plan one-line summaries. plan=${JSON.stringify(final)} judge=${JSON.stringify(judge)}`, 'Pass 4 - Plan')
  if (A.run_style === 'planonly') await synth('Pass 4', 'EXECUTE.md', `Separate-session kickoff per references/kickoff-prompt.md template: run name ${A.name}, absolute plan path ${A.run_dir}/final-plan.md, activation summary from the plan's Feature Activation Plan section, and the one-line resume trigger "discover: build ${A.name}".`, 'Pass 4 - Plan')
  return { plan_path: `${A.run_dir}/final-plan.md` }
}
```

- [ ] **Step 2: Replace the Task-1 placeholder return with the dispatcher (verbatim)**

```js
phase('Bootstrap')
const boot = await bootstrap()
const priorMap = boot.found && boot.artifacts.map ? boot.artifacts.map : ''
const completed = []
let map = null, candidates = null, filtered = null
try {
  if (A.from_pass > 0 && !boot.found) return partialReturn([], `Cannot start at pass ${A.from_pass}: no saved artifacts found in ${A.run_dir}.`)
  if (A.from_pass === 0) {
    if (!gate(0)) return partialReturn(completed, 'Budget too low for Pass 0.')
    map = await passMap(); completed.push(0)
    if (!gate(1)) return partialReturn(completed, 'Budget exhausted after Pass 0.')
    candidates = await passResearch(map); completed.push(1)
    if (!gate(2)) return partialReturn(completed, 'Budget exhausted after Pass 1.')
    filtered = await passFilter(map, candidates, boot.artifacts.outcomes_prior, boot.user_edits); completed.push(2)
  } else {
    map = { fromDisk: true, raw: priorMap, components: [], data_sources: [], gaps: [], unverified: [] }
    const reparse = await agent(`${PRE}\nParse this saved system-map artifact back into structured form:\n${priorMap}`, { label: 'reparse-map', phase: 'Bootstrap', schema: S_MAP, model: 'haiku' })
    if (reparse) map = reparse
    const refilter = await agent(`${PRE}\nParse the saved pass-2 artifact back into {kept, drops} structured form. HUMAN CHECKPOINT EDITS OVERRIDE the artifact - apply them (drop = remove from kept; note rewordings): edits=${JSON.stringify(boot.user_edits)}\nARTIFACT:\n${boot.artifacts.filtered}`, { label: 'reparse-filtered', phase: 'Bootstrap', schema: S_FILTER, model: 'haiku' })
    filtered = refilter || { kept: [], drops: [] }
  }
  let survivors = null
  if (A.to_pass >= 3 && A.from_pass <= 3) {
    if (!gate(3)) return partialReturn(completed, 'Budget exhausted before Pass 3.')
    const kill = await passKill(map, filtered.kept); completed.push(3)
    survivors = kill.survivors
  } else if (A.from_pass === 4) {
    const rekill = await agent(`${PRE}\nParse the saved kill report back into {survivors, kills} structured form. HUMAN CHECKPOINT EDITS OVERRIDE (an overridden kill re-enters survivors WITH its objection recorded as a safeguard): edits=${JSON.stringify(boot.user_edits)}\nARTIFACT:\n${boot.artifacts.kill_report}`, { label: 'reparse-kill', phase: 'Bootstrap', schema: S_KILL, model: 'haiku' })
    survivors = rekill ? rekill.survivors : []
  }
  if (A.to_pass >= 4) {
    if (!gate(4)) return partialReturn(completed, 'Budget exhausted before Pass 4.')
    await passPlan(map, survivors); completed.push(4)
  }
} catch (e) {
  return partialReturn(completed, `A stage failed hard (${String(e).slice(0, 200)}).`)
}
const summary = await agent(`${PRE}\nWrite a 3-6 sentence plain-language summary of this burst for a non-coder: passes completed ${JSON.stringify(completed)}, counts ${JSON.stringify(RUNSTATE.counts)}, decisions needed ${JSON.stringify(RUNSTATE.decisions)}. Name the artifact files to look at. No jargon.`, { label: 'burst-summary', phase: completed.includes(4) ? 'Pass 4 - Plan' : 'Pass 3 - Kill-test', schema: { type: 'object', required: ['text'], properties: { text: { type: 'string' } } }, model: 'haiku' })
return { ok: true, partial: false, completed_passes: completed, summary: summary ? summary.text : 'burst complete', artifacts: RUNSTATE.artifacts, counts: RUNSTATE.counts, decisions_needed: RUNSTATE.decisions, resume_command: '' }
```

- [ ] **Step 3: Syntax check.** Expected: exit 0.
- [ ] **Step 4: Commit** — `git commit -am "Implement Pass 4 tournament and the burst dispatcher with budget gates"`

---

### Task 7: Stub harness — test the script's topology without the engine

**Files:**
- Create: `/root/work/claude-discover-publish/repo/tests/run-harness.mjs`

**Interfaces:**
- Consumes: the finished script (Tasks 1–6).
- Produces: `node tests/run-harness.mjs` exits 0 with `PASS` lines; used again in Tasks 11–12 after any script edit.

- [ ] **Step 1: Write the harness (verbatim)**

```js
// Stub harness: runs discover-pipeline.js with canned agent() responses.
// Catches topology/reference bugs without spending tokens. NOT a semantic test.
import { readFileSync } from 'fs'
const src = readFileSync(new URL('../skills/discover/workflows/discover-pipeline.js', import.meta.url), 'utf8')
const body = src.replace(/export const meta[\s\S]*?\n}\n/, '')
const AsyncFn = Object.getPrototypeOf(async function () {}).constructor

const canned = label =>
  label === 'bootstrap' ? { found: false, artifacts: {}, user_edits: '' } :
  label.startsWith('mapper') || label === 'architect-merge' ? { components: [{ name: 'core', path: 'src/core.py', does: 'x' }], data_sources: [], gaps: [], unverified: [] } :
  label.startsWith('researcher') ? { candidates: [{ id: '', name: 'F-' + label, function: 'f', rationale: 'r', source_quality: 'medium', sources: [] }] } :
  label.startsWith('dry-judge') ? { new_candidates: [], dry: true } :
  label === 'filter-analyst' ? { kept: [{ id: 'c1', name: 'F1', rank: 1, failure_modes: [], safeguards: [], prior_outcome: '' }], drops: [{ id: 'c2', name: 'F2', code: 'already-exists-verified', reason: 'map says so', evidence: '' }] } :
  label.startsWith('redundancy') ? { verdict: 'stub', evidence: 'src/core.py:1 stub', extend_note: '' } :
  label.startsWith('skeptic') ? { objections: [{ candidate_id: 'c1', lens: 'code-reality', kind: 'kill-eligible', trigger: 't', mechanism: 'm', impact: 'i', evidence: 'src/core.py:10 quoted-snippet-longer-than-20', fatal_class: 'infeasible' }], endorsements: [] } :
  label === 'advocate' || label === 'judge' ? { rulings: [{ candidate_id: 'c1', objection_ref: 'o1', ruling: 'CONVERTED', reason: 'safeguardable', evidence_recheck: 'checked' }] } :
  label.startsWith('xmodel') ? { family: 'codex', available: false, notes: [] } :
  label === 'approach-enum' ? { distinct_architectures: 2, notes: '' } :
  label.startsWith('plan:') ? { stance: label.slice(5), sections: Object.fromEntries(['System Overview', 'Component Architecture', 'Data Flow Pipeline', 'Data Structures', 'Integration Plan', 'Failure Handling', 'Feature Activation Plan', 'Verification Checklist'].map(s => [s, 'x'])), features: [{ name: 'F1', probe: { kind: 'live_probe', instruction: 'run x', expected_evidence: 'y', reason: '', owed_check: '' } }] } :
  label === 'tournament-judge' ? { winner_stance: 'minimal-diff', scores: [], grounded_findings: 'ok', graft_list: [], revision_order: '' } :
  label === 'plan-reviser' ? { stance: 'minimal-diff', sections: Object.fromEntries(['System Overview', 'Component Architecture', 'Data Flow Pipeline', 'Data Structures', 'Integration Plan', 'Failure Handling', 'Feature Activation Plan', 'Verification Checklist'].map(s => [s, 'x'])), features: [{ name: 'F1', probe: { kind: 'live_probe', instruction: 'run x', expected_evidence: 'y', reason: '', owed_check: '' } }] } :
  label === 'coherence-check' ? { coherent: true, fixes_applied: [] } :
  label === 'burst-summary' ? { text: 'done' } :
  label.startsWith('synth') ? { path: '/fake/' + label, summary: 's' } :
  label.startsWith('reparse-map') ? { components: [], data_sources: [], gaps: [], unverified: [] } :
  label.startsWith('reparse-filtered') ? { kept: [{ id: 'c1', name: 'F1', rank: 1, failure_modes: [], safeguards: [], prior_outcome: '' }], drops: [] } :
  label.startsWith('reparse-kill') ? { survivors: [{ id: 'c1', name: 'F1', demerits: 0, safeguards: [], near_miss: '', cross_family: '' }], kills: [] } :
  { }

async function runCase(name, argsObj, assert) {
  const calls = []
  const agent = async (prompt, opts = {}) => { calls.push(opts.label || 'unlabeled'); return canned(opts.label || '') }
  const parallel = async thunks => Promise.all(thunks.map(t => t().catch(() => null)))
  const pipeline = async (items, ...stages) => Promise.all(items.map(async (it, i) => { let v = it; for (const s of stages) v = await s(v, it, i); return v }))
  const fn = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', 'workflow', body)
  const result = await fn(argsObj, agent, parallel, pipeline, () => {}, () => {}, { total: null, spent: () => 0, remaining: () => Infinity }, async () => null)
  const err = assert(result, calls)
  console.log(err ? `FAIL ${name}: ${err}` : `PASS ${name}`)
  if (err) process.exitCode = 1
}

const base = { name: 'toy', run_dir: '/tmp/x', project_root: '/tmp/p', feature_ask: 'add F', dial: 'light', run_style: 'checkpoints', greenfield: false, capabilities: { omc: false, superpowers: false, codex: 'absent', gemini: 'absent' }, budget_override: null, free_data_only: true }

await runCase('handsoff-full-0-4', { ...base, run_style: 'handsoff', from_pass: 0, to_pass: 4 },
  (r, calls) => !r.ok ? 'not ok: ' + r.summary
    : JSON.stringify(r.completed_passes) !== '[0,1,2,3,4]' ? 'passes=' + JSON.stringify(r.completed_passes)
    : !calls.some(c => c === 'skeptic:code-reality') ? 'no skeptic ran'
    : calls.filter(c => c.startsWith('skeptic:')).length !== 2 ? 'light dial must run exactly 2 skeptics'
    : calls.some(c => c.startsWith('xmodel')) ? 'cross-model must not run on light/absent'
    : !calls.some(c => c === 'synth:pass-3-kill-report.md') ? 'kill report not written' : '')
await runCase('burst-A-0-2', { ...base, from_pass: 0, to_pass: 2 },
  (r, calls) => !r.ok ? 'not ok' : JSON.stringify(r.completed_passes) !== '[0,1,2]' ? 'passes=' + JSON.stringify(r.completed_passes)
    : calls.some(c => c.startsWith('skeptic')) ? 'pass 3 leaked into burst A' : '')
await runCase('burst-C-4-4-resume', { ...base, from_pass: 4, to_pass: 4 },
  r => (!r.partial ? 'must be partial without saved artifacts (bootstrap stub returns found:false)' : ''))
await runCase('greenfield-skips-map', { ...base, greenfield: true, from_pass: 0, to_pass: 2 },
  (r, calls) => calls.some(c => c.startsWith('mapper')) ? 'mappers ran on greenfield' : '')
```

- [ ] **Step 2: Run it**

Run: `cd /root/work/claude-discover-publish/repo && node tests/run-harness.mjs`
Expected: four `PASS ...` lines, exit 0. If a case fails, fix the SCRIPT (or, if the canned data is wrong-shaped vs a schema you changed, fix the harness) and re-run until green. Note: the bootstrap stub returns `found:false`, so `burst-C-4-4-resume` exercises the guard `from_pass>0 && !boot.found` → partial return.

- [ ] **Step 3: Commit** — `git add tests && git commit -m "Add stub harness covering burst windows, dial counts, greenfield, resume guard"`

---

### Task 8: SKILL.md rewrite — front-of-house

**Files:**
- Rewrite: `/root/work/claude-discover-publish/repo/skills/discover/SKILL.md`

**Interfaces:**
- Consumes: the `args`/return contracts (top of this plan), the script path `workflows/discover-pipeline.js` relative to the skill base dir.
- Produces: the full front-of-house prose. Task 9 appends the Pass-5 section at the marker `<!-- PASS5 -->`.

- [ ] **Step 1: Write the new SKILL.md.** Keep the frontmatter `name: discover` and the entire current `description:` UNCHANGED except: replace the parenthetical pass list with `(existing-system analysis, external research, filter/prioritize, evidence-rule adversarial kill-test, plan tournament, main-session execution with verification)` and delete the sentence `Composes OMC and superpowers skills rather than reimplementing them.` (boosters are optional now). The four hard triggers and the explicit-invocation-only paragraphs stay verbatim. Then the body (write exactly this, then adjust only where a literal path must be resolved at runtime):

````markdown
# discover — 5-Pass Feature Discovery & Execution (Workflow-engine edition)

Passes 0–4 (map → research → filter → kill-test → plan) run inside Claude Code's built-in
Workflow engine via the bundled script `workflows/discover-pipeline.js` (resolve the absolute
path from this skill's base directory). Pass 5 (the build) runs here in the main session.
Helpers' output never lands in this session's context: bursts return a short summary + file
paths only. Artifacts on disk under `.claude/discover/<run-name>/` are ALWAYS the source of
truth; the engine journal is a disposable same-burst cache.

## When this fires
[VERBATIM from the current SKILL.md "When this fires" section — four triggers, never-fire rules]
Additional sub-triggers: `discover: recheck` (force capability rescan) · `discover: build <name>`
(build a saved plan) · `discover: <name> budget=N` (power-user token cap override).

## Startup sequence — in order, before ANY work

1. **Engine gate.** Check the Workflow tool is present in YOUR current tool list. If absent, STOP
   with zero artifacts written: "discover needs Claude Code 2.1.154 or newer (the built-in
   Workflow engine). You have <version from `claude --version`>. Update with: `claude update` —
   then run discover again." Do NOT improvise a degraded run; a prose fallback is explicitly
   forbidden (design decision — two pipelines would drift).
2. **Capability scan (cached).** Read `~/.claude/discover/environment.json`. If missing, or its
   recorded Claude Code version ≠ current, or the user said `discover: recheck`: rescan — OMC
   (`~/.claude/plugins/cache/` contains oh-my-claudecode, or /oh-my-claudecode:* skills listed),
   superpowers (same pattern), codex CLI (`command -v codex`), gemini CLI (`command -v gemini`).
   Write the file: `{claude_code_version, omc, superpowers, codex_installed, gemini_installed,
   scanned_at}`.
3. **Booster health (per run, parallel, ~10s timeout each).** Only for installed CLIs:
   `timeout 10 codex exec "say ok"` and `GEMINI_CLI_TRUST_WORKSPACE=true timeout 10 gemini -p "say ok"`.
   healthy = replies; broken = installed but errors (usually logged out). Show ONE status line, e.g.:
   `✅ OMC · ✅ superpowers · ⚠️ Codex (logged out) · ✅ Gemini — cross-model will use Gemini only.`
   If anything is ⚠️: say the exact fix (`codex login` / `gemini` re-auth) and ask: pause & fix, or
   proceed without it? EXCEPTION — Hands-off run style: never block; proceed-without and put the
   ⚠️ prominently in the final report.
4. **The three setup questions** (ask all in ONE message; parameter inputs, exempt from
   no-confirmation rules; never silently defaulted):
   - **Name** — [VERBATIM the run-name phrasing + example from the current SKILL.md setup section]
   - **Thoroughness** — Light / Standard (default) / Deep. Explain in plain words with the cost
     line: Light ≈ a quick sweep (2 mappers, 2 research rounds, 2 skeptics, 1 plan; small token
     spend); Standard ≈ the default balance (3/3/3/2 rivals); Deep ≈ exhaustive (5 mappers,
     up to 5 rounds, 5 skeptics, 3 rival plans; can be a large chunk of a 5-hour usage window).
   - **Run style** — Hands-off (passes 0–4 straight; build after one OK on the plan) /
     Checkpoints (recommended: review the shortlist after pass 2; if the kill-test kills
     something, review that too; review the plan before build) / Plan-only (stop at the plan;
     `discover: build <name>` later).
5. **Greenfield detection.** [VERBATIM current SKILL.md greenfield commands + threshold]. Sets
   `greenfield: true` in args; Pass 0 is skipped by the script with a note.
6. **Run dir init.** Create `.claude/discover/<name>/`; write `state.json`:
   `{format_version: 2, name, dial, run_style, created, current_pass: null, bursts: [],
   booster_status: {...}}`. If the dir already exists: `format_version` 2 → offer resume;
   missing/other `format_version` → "This run folder is from the old discover. Finish it with
   plugin v0.1.0, or restart fresh under a new name." — never touch its contents.

## Running bursts

Launch the engine via the Workflow tool: `{scriptPath: "<skill-base>/workflows/discover-pipeline.js",
args: {...}}` with the args contract: name, run_dir (absolute), project_root (absolute),
feature_ask (user's words), dial, run_style, from_pass, to_pass, greenfield, capabilities
(from steps 2–3: {omc, superpowers, codex: healthy|broken|absent, gemini: ...}),
budget_override (from `budget=N` or null), free_data_only (true unless the user allowed paid).

- Hands-off / Plan-only: ONE burst `from_pass: 0, to_pass: 4`.
- Checkpoints: burst `0→2`; **shortlist review**; burst `3→3`; **kill review ONLY if
  counts.kills > 0 or decisions_needed is non-empty** (no kills → launch burst `4→4`
  immediately); **plan review**; then Pass 5.
- After EVERY burst: update `state.json` (current_pass, bursts += {from,to,ok,partial}); relay
  the returned summary + artifact paths to the user in plain language. NEVER paste artifact
  contents into chat unless the user asks; name the files instead.
- Checkpoint edits: whatever the user decides at a review ("drop candidate 3", "overrule that
  kill"), append verbatim to `<run_dir>/checkpoint-edits.md` under a dated heading. The next
  burst's bootstrap reads and applies it (an overruled kill re-enters planning WITH its
  objection attached as a safeguard).
- If a burst returns `partial: true`: show its summary and the `resume_command` verbatim, then
  stop. On resume (`discover: <name>`), read `state.json`, relaunch the SAME burst window —
  completed agent calls replay from the engine cache; finished passes are read from disk.

## Resume triggers
- `discover: <name>` — read `state.json`, continue from `current_pass` / the next burst.
- `discover: build <name>` — skip to Pass 5 using the saved `final-plan.md` (+ `EXECUTE.md` if present).

<!-- PASS5 -->

## Failure modes and recovery
- Engine died / laptop slept mid-burst: artifacts exist for every completed pass; resume relaunches the burst window.
- `state.json` corrupt but artifacts present: rebuild state.json from which pass-N files exist; confirm with the user.
- User aborts: set `status: "aborted"` in state.json; same-name re-invocation offers resume.
- A booster dies MID-run: the script degrades per-call and notes it in the burst summary — no user action mid-run.

## Anti-patterns (unchanged from v0.1.0 where still applicable)
[VERBATIM from current SKILL.md: the setup-questions-are-not-confirmations paragraph; "Skipping
Pass 0 to save time"; "Letting researchers infer functionality from filenames"; "Treating
cross-model output as gospel"; "Auto-pushing on test failure"; "Asking permission at every step
in Pass 5". DROP the tmux/agent-count items.]
````

- [ ] **Step 2: Fill every `[VERBATIM ...]` marker** by copying the named text from the current SKILL.md (`git show HEAD~N:skills/discover/SKILL.md` or the file before this task's edit — it is in git history after Task 1's commit). Zero `[VERBATIM` strings may remain: `grep -c "VERBATIM" skills/discover/SKILL.md` → `0`.
- [ ] **Step 3: Review against spec §4 + §6** — every startup step present, in order; the three run styles behave per §6. Fix inline.
- [ ] **Step 4: Commit** — `git commit -am "Rewrite SKILL.md front-of-house: engine gate, capability scan, 3 questions, burst orchestration"`

---

### Task 9: Pass 5 section + references rewrite

**Files:**
- Modify: `skills/discover/SKILL.md` (replace `<!-- PASS5 -->`)
- Rewrite: `skills/discover/references/pass-templates.md`
- Rewrite: `skills/discover/references/kickoff-prompt.md`

**Interfaces:**
- Consumes: final-plan.md's "Feature Probes" section format (Task 6), outcome.json shape (below).
- Produces: `outcome.json` shape used by the script's bootstrap read-back: `{run: <name>, closed: <date>, candidates: [{name, verdict: "shipped"|"killed"|"deferred", detail: "<SHA / kill reason / deferral reason>"}]}`.

- [ ] **Step 1: Write the Pass-5 section** (replace `<!-- PASS5 -->`):

````markdown
## Pass 5 — Build (main session)

1. **Read context:** `final-plan.md` + `state.json` (+ `EXECUTE.md` for `discover: build`).
2. **Implement in a loop until the Verification Checklist passes.** If OMC's ralph is present
   and healthy, use it with the directive: "Execute the implementation plan at <abs>/final-plan.md.
   Loop until the verification checklist passes." Otherwise run the built-in loop: implement →
   test → have a FRESH verifier agent (never the implementer) check the checklist with tool
   access → fix → repeat.
3. **Probe gate — before any commit.** For EVERY feature in the plan's Feature Probes section:
   - `live_probe`: execute the instruction, capture the actual output, compare to
     expected_evidence. Record both in `pass-5-execution-log.md`.
   - `deferred_probe`: first VERIFY the named prerequisite really is absent (e.g. grep config
     for the credential, check the env). A deferral with a present prerequisite is void — run
     the probe. Record the verification.
   If `superpowers:verification-before-completion` is available, invoke it now; either way the
   rule holds: no completion claim without fresh evidence in the same message.
4. **Ask before commit** — one message enumerating every probe: ✅ ran (evidence one-liner) /
   ⏸ deferred (reason). Wait for OK. Then commit; push only if a github remote exists (skip
   with a note otherwise); on push failure surface the exact next step, never force-push.
5. **Write `outcome.json`** to the run dir: every candidate that entered Pass 3, with verdict
   shipped (+ commit SHA) / killed (+ short reason) / deferred (+ reason). Future runs on this
   repo read this — it is how discover remembers.
6. **Final report** to `pass-5-execution-log.md`: files changed, test results, probe evidence,
   SHA + push status, open issues.
**When to stop and ask:** [VERBATIM the four stop-and-ask bullets from current SKILL.md Pass 5.]
````

- [ ] **Step 2: Rewrite `references/pass-templates.md`** — replace its content with the artifact inventory: one section per file in the run dir (`state.json`, `pass-0-system-map.md`, `pass-1-candidates.md`, `pass-2-filtered.md`, `drops-log.md`, `pass-3-kill-report.md`, `build-next.md`, `final-plan.md`, `EXECUTE.md`, `outcome.json`, `checkpoint-edits.md`, `pass-5-execution-log.md`), each with: who writes it (which synthesizer / the main session), when, and 3–8 line content sketch matching the synth specs in the script (Tasks 4–6) and outcome.json shape above. No schemas here — the script owns those (DRY).
- [ ] **Step 3: Revise `references/kickoff-prompt.md`** — keep the template structure but: trigger line becomes `discover: build <run-name>`; remove all tmux/pane references; the context list = final-plan.md path, state.json path, probe-gate reminder, ask-before-commit reminder.
- [ ] **Step 4: Consistency grep** — `grep -rn "tmux\|discover.sh\|agent count\|ralplan" skills/discover/ | grep -v "workflows/"` → expected: no hits (ralplan may appear ONLY in SKILL.md Pass 5 as the ralph mention — adjust grep or text until output is clean and intentional).
- [ ] **Step 5: Commit** — `git commit -am "Add Pass 5 probe gate + outcome memory; rewrite references for the engine model"`

---

### Task 10: README + manifests

**Files:**
- Rewrite: `/root/work/claude-discover-publish/repo/README.md`
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: README rewrite.** Sections, in order: What discover is (3 sentences, plain);
  Requirements (Claude Code ≥ 2.1.154 paid — the built-in Workflow engine; git; nothing else);
  How it works (back room / front: a diagram-free plain paragraph + the 5-pass table with one
  line each, kill rule described as "an idea dies only on proven, checked evidence — never a
  vote"); Install (marketplace add + `claude plugin install discover`); Usage (the four
  triggers + `discover: recheck` / `build` / `budget=N`); The three setup questions (name/dial
  with the plain-words cost line from Task 8/run style); Boosters (table: OMC, superpowers,
  Codex CLI, Gemini CLI — what each adds, three-state detection, "absent = silent built-in,
  broken = loud warning before work"); What you'll be shown (the §12 always-surface list as
  bullets); Costs & limits (dial ≈ spend; the budget breaker meters Claude tokens only — Codex/
  Gemini CLI calls are not counted; concurrency = your machine's cores minus 2, more cores =
  faster not better); Tested on (Linux + macOS expected; Windows untested); Changelog (1.0.0:
  Workflow-engine rebuild, tmux removed, evidence-rule kill-test, plan tournament, outcome
  memory).
- [ ] **Step 2: Manifests.** In BOTH json files: version `0.1.0` → `1.0.0`. plugin.json
  description → "Methodical 5-pass feature-discovery workflow on Claude Code's built-in
  Workflow engine: system mapping, bounded research, evidence-rule kill-testing, plan
  tournament, verified execution. No required dependencies; OMC/superpowers/Codex/Gemini are
  optional boosters." marketplace.json plugin description → same; tags: replace `"tmux"` with
  `"workflow-engine"`. Validate: `node -e "JSON.parse(require('fs').readFileSync('.claude-plugin/plugin.json'))" && node -e "JSON.parse(require('fs').readFileSync('.claude-plugin/marketplace.json'))"` → exit 0.
- [ ] **Step 3: Commit** — `git commit -am "Rewrite README for the engine model; bump to 1.0.0"`

---

### Task 11: Toy project + end-to-end run (Piece 4 centerpiece)

**Files:**
- Create: `/root/work/discover-toy/` (scratch git repo, NOT inside any existing repo)
- Create: `/root/work/claude-discover-publish/repo/tests/e2e-evidence.md` (evidence log)

- [ ] **Step 1: Sync the rebuilt plugin into the installed cache** so `/discover` picks it up:
  `rsync -a --delete /root/work/claude-discover-publish/repo/skills/discover/ /root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/` and same to the staging copy `/root/work/claude-discover-publish/extracted/discover-plugin/skills/discover/`. Verify: `grep -c "Workflow" /root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/SKILL.md` ≥ 1.
- [ ] **Step 2: Build the toy.** `/root/work/discover-toy/`: `git init`; a tiny Python expense
  tracker — `tracker/store.py` (load/save JSON list of {date, amount, category}), `tracker/cli.py`
  (argparse: `add`, `list`), `tests/test_store.py` (2 pytest tests), `README.md` (3 lines).
  Commit it. This is a REAL small program — write it, run `pytest` in it once, green.
- [ ] **Step 3: The run.** In a fresh Claude Code session with cwd `/root/work/discover-toy/`
  (fresh session = clean context, the real user experience), type:
  `discover: add a monthly spending summary command` → answer the three questions: name
  `monthly-summary`, dial Light, style Checkpoints. Let it run through Pass 5, interacting at
  each checkpoint.
- [ ] **Step 4: Inspect at every gate and record in `tests/e2e-evidence.md`** (copy each
  claim + the actual observed artifact excerpt): engine gate passed silently · status line
  shown before work · burst A returned summary+paths only (no artifact dumps in chat) ·
  `pass-0-system-map.md` names real files · `drops-log.md` exists and every drop has a
  reason-code · shortlist review appeared · kill review appeared ONLY if kills>0 · `final-plan.md`
  has all 8 sections + a probe per feature · Pass 5 ran the probe and showed real command output ·
  ask-before-commit enumerated probes · `outcome.json` written with verdicts · the built feature
  actually works (`python -m tracker.cli summary --month 2026-06` or as-designed prints a real
  summary — run it yourself).
- [ ] **Step 5: Commit the evidence file** in the plugin repo.

---

### Task 12: Branch tests + budget calibration

**Files:**
- Modify: `tests/e2e-evidence.md` (append each test's evidence)
- Modify: `skills/discover/workflows/discover-pipeline.js` (CALIBRATE constants only)

Run each in the toy repo (fresh session or continued, noted per test). For every test append to the evidence file: what was done, expected vs observed, verbatim key output.

- [ ] **B1 Checkpoint edits respected:** new run `edits-test`, dial Light, Checkpoints. At the shortlist review say: "drop <candidate 2>, and rename <candidate 1> to <X>". Verify `checkpoint-edits.md` got the note AND the kill report / plan reflect the edit (dropped one absent, logged as `user-dropped`).
- [ ] **B2 Kill + override:** run `kill-test` with the ask "add automatic payment execution that wires money based on detected bills" (designed to draw a fatal objection). If a kill occurs: verify the pause fires, reply "overrule the kill of X", verify burst C's plan contains X with the objection as a safeguard. If NO kill occurs naturally, force one: at the shortlist review say "kill candidate 1 at the kill-test" is NOT valid — instead rerun with dial Standard once; if still no kill, record honestly "kill path exercised only via harness stub" and rely on Task 7's CONVERTED-ruling coverage + record the residual gap.
- [ ] **B3 Budget exhaustion:** run `budget-test` with `discover: budget-test budget=50000` (absurdly low). Expected: burst stops at a soft gate with `partial: true`, artifacts for completed passes exist on disk, chat shows the plain summary + `discover: budget-test` resume line. Then resume WITHOUT the override: verify it continues (finished passes read from disk, not re-run — check the burst summary's completed_passes).
- [ ] **B4 Mid-burst kill:** start run `crash-test` (Standard, Checkpoints), kill the Claude Code process mid-burst-A (close the terminal). Reopen, `discover: crash-test`: verify it resumes and completes burst A; artifacts of passes finished before the kill were not re-run (journal cache or disk read — either is a pass; record which happened).
- [ ] **B5 Broken booster:** `mv ~/.codex/auth.json ~/.codex/auth.json.bak` (or the auth file found via `codex login status`). New run: verify the status line shows ⚠️ Codex + the exact fix command + the pause/proceed question. Also start a Hands-off run: verify it does NOT stall (proceeds + notes it). `mv` the file back; verify a `discover: recheck` shows ✅ again.
- [ ] **B6 Vanilla-user simulation:** closest real probe available on this machine: temporarily
  `mv ~/.claude/plugins/cache/oh-my-claudecode ~/.claude/plugins/cache/oh-my-claudecode.bak` (and same for superpowers), `discover: recheck`, then a Light run: verify status line stays silent about absent boosters, passes run on built-ins, kill report carries the "single-family panel" label (with Codex/Gemini also renamed away per B5 method). Restore everything after. If plugin-cache moves break Claude Code startup, abort the move, record the residual gap explicitly ("vanilla simulation not fully achievable on this machine") and verify instead via the capabilities args: hand-edit `~/.claude/discover/environment.json` to all-absent + `discover: <name>` — the script trusts args; record which method ran.
- [ ] **B7 Outcome read-back:** after Task 11's run completed with `outcome.json`, start a second run `readback-test` on the toy with a similar ask. Verify Pass 2's artifact surfaces the prior verdicts (`prior_outcome` notes) and nothing was auto-dropped because of them.
- [ ] **B8 Old run dir:** fabricate `/root/work/discover-toy/.claude/discover/old-run/state.json` = `{"run":"old-run","pass":3}` (no format_version). `discover: old-run` → expected verbatim-class message: old discover folder, finish with v0.1.0 or restart fresh; directory contents untouched (checksum before/after).
- [ ] **B9 Calibration:** from the journals of Task 11 + B-tests (transcript dirs are printed at each Workflow launch; `journal.jsonl` has per-agent results; token totals in the task usage lines), compute real per-pass spend for Light and Standard-ish runs. Replace the CALIBRATE placeholder numbers in `DIALS` (breaker ≈ 2× observed total per dial; passEst ≈ observed per-pass + 30%). Deep stays extrapolated (≈ 2.5× Standard) — note that in a code comment. `node --check` + `node tests/run-harness.mjs` → 4 PASS. Re-sync per Task 11 Step 1. Commit: `git commit -am "Calibrate dial budgets from real toy-run journals"`.

---

### Task 13: Independent verifier

- [ ] **Step 1:** Dispatch a FRESH verifier agent (not any agent that wrote code in Tasks 1–12) with: the spec path, the plan path, `tests/e2e-evidence.md`, and the instruction: re-run the Task 11 end-to-end toy run yourself on a NEW run name, spot-check 4 of the 8 branch tests of your choosing, then diff every claim in e2e-evidence.md against what you observe. Report: confirmed / contradicted / untestable, per claim.
- [ ] **Step 2:** Fix everything contradicted; loop the verifier until its report has zero contradicted claims. Append its final report to `tests/e2e-evidence.md`. Commit.

---

### Task 14: Release + workspace bookkeeping

- [ ] **Step 1:** Final review pass: `git -C /root/work/claude-discover-publish/repo log --oneline` shows Tasks 1–13; `grep -rn "CALIBRATE" skills/` → only the Deep-extrapolation comment remains; harness green; manifests 1.0.0.
- [ ] **Step 2:** **Confirm with the user, then** push: `git -C /root/work/claude-discover-publish/repo push origin master` (public repo `chopra2007/claude-discover`). After push: `claude plugin update discover` (or documented equivalent) so the installed copy comes from the published version; re-run ONE Light toy run end-to-end as the post-release smoke check.
- [ ] **Step 3:** Workspace bookkeeping (this repo): per `todo/CONVENTION.md` add the TODO entry marked DONE with date (or mark the build TODO item created at design time); update `todo/kickoffs/discover-rebuild.md` Status → SHIPPED + date; write a memory entry (`project_discover_rebuild_shipped`) with: what shipped, version 1.0.0, key paths, the caveat list (Windows untested, Deep budgets extrapolated, any B2/B6 residual gaps).

---

## Self-Review (performed at write time)

**Spec coverage:** §1–3 → Tasks 1–6, 8; §4 startup → Task 8; §5 passes → Tasks 4–6; §6 run styles → Tasks 6, 8; §7 Pass 5 → Task 9; §8 economics → Tasks 2, 3, 6, 12(B3, B9); §9 artifacts → Tasks 3–6, 9; §10 boosters → Tasks 5 (cross-model CLI), 8 (detection), 9 (ralph); §11 failure/recovery → Tasks 3, 6, 8, 12(B4, B8); §12 always-surface → Tasks 6 (decisions_needed), 8, 10; §13 rejected list → enforced by omission + README/SKILL wording; §14 Piece 4 → Tasks 7, 11–13; §15 release → Tasks 10, 14; §16 notes → honored throughout (closed enums in Task 2; thin skill in Task 8; implementation order = task order). Engine-absence real test is an honest deferral (spec §14.3) — covered as SKILL.md logic review in Task 8 Step 3.
**Placeholder scan:** the only intentional placeholders are the CALIBRATE budget numbers (spec-sanctioned, resolved in Task 12 B9) and `[VERBATIM ...]` copy markers (each names its exact source text and Task 8/9 include a grep gate proving none remain).
**Type consistency:** `S_FILTER.kept[]` shape matches `passKill(map, kept)` consumption; `S_KILL.survivors[]` matches `passPlan(map, survivors)`; harness canned shapes mirror the schemas; args/return contracts stated once at top and used identically in Tasks 6 and 8.
