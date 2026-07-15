# Discover plugin — living record (versions, insights, next changes)

**Status:** LIVING RECORD — v1.3.0 PUBLISHED + LIVE (2026-07-12) on `chopra2007/claude-discover` (main `f42e784`, tag `v1.3.0`); local install refreshed to the 1.3.0 cache. v1.3 is now the live/installed version.
**Created:** 2026-07-06

**CURRENT STATUS (2026-07-14 — v1.3.0 LIVE; first real run on the bot repo exposed 2 gaps, NOT yet
fixed):** v1.3 works as designed — run `menu-top10` (TODO #76) found no cache on this repo, so it paid
for one full scan and wrote the cache; future runs get the savings. But trying to seed the cache by
hand from an older run's map surfaced two real weaknesses, both written up in the 2026-07-14 session
notes at the bottom of this file: **(1)** the 100-file staleness cap counts **documentation** — 41 of
the 126 changed files on this repo were markdown the map never inventoried, so doc churn expires the
cache far sooner than the code justifies; **(2) the dangerous one** — the cache stores whatever Pass 0
produced, and **Pass 0 is feature-flavoured**. The Jul-11 map is a legitimate full scan whose output
covers ONLY #55/#20 and has zero coverage of `options.py` / `embed.py` / `cross_asset.py` /
`commands.py`. It predates v1.3 by a day, so it never became the cache — **had it done so, the next run
would have silently delta-patched a map that is blank exactly where the new work lives** ("keep
everything else verbatim"), and nothing would have flagged it. Fix (a): cache a NEUTRAL repo inventory,
separate from the run's feature-scoped map. **Owed: both fixes.**

**CURRENT STATUS (2026-07-12, later — v1.3.0 SHIPPED + LIVE):** the reusable-codebase-map change is
built, tested, published (main `f42e784`, tag `v1.3.0`), and the installed copy refreshed to the 1.3.0
cache (32/32 harness tests green on the live copy; takes effect next session). All four paths were
proven with real engine runs on the toy repo: full scan writes the per-repo map cache with the true git
commit; an unchanged repo reused the map verbatim with ZERO mapper agents; a 1-file change ran exactly
one delta mapper that correctly picked up the new function; a same-run restart reparsed the run's own
saved map instead of re-paying the fan-out. **Nothing owed — v1.3 is live.** Details in the v1.3.0
changelog entry below; original spec kept below for history.

**CURRENT STATUS (2026-07-12, superseded same day):** v1.2.0 is live and nothing is owed on it. **Next change queued for a
fresh session: v1.3 — stop re-mapping the codebase from scratch on every run.** Measured on the last two
real runs: the map phase (Pass 0) ate ~23% of the tokens of the Jul-11 run (`todo-55-20-plan`, 3 mappers,
~4.6M of ~20M) and ~50% of the Jul-6/7 run (`next-features-jul2026`, 5 mappers, ~100M of ~200M — because
the map was rebuilt from zero **three times** across that run's restarts). Build-ready spec below:
**"v1.3 spec — reusable codebase map"**. Straightforward change (~30–50 lines in one file); no need for a
stronger model. Sized/scoped 2026-07-12; SHIPPED later the same day (see block above).

**CURRENT STATUS (2026-07-07, later — `from_pass=1` was a ONE-RUN-ONLY edit, now reverted):** To finish
TODO #67 the plugin needed a "skip straight to the research pass" resume (reuse a saved Pass-0 map,
skip the codebase re-scan). That path didn't exist, so it was added + used for that single run
(validated live: Deep `from_pass:1→2` → `[1,2]`, 39 agents, 0 errors, 40 grounded ideas), then — per
the user — **reverted from the repo** because it was wanted for that run only, NOT as a permanent
feature. The plugin repo is back at **clean v1.2.0** (`9dca67e`; nothing pushed, no v1.2.1). The exact,
build-ready recipe to make it permanent later is in **"Optional future change — `from_pass=1` resume"**
below — if the user ever decides they want it, that section is copy-paste-able.

**CURRENT STATUS (2026-07-07):** v1.2 is fully built + committed on branch `v1.2-per-seat-model-effort`
in the repo — 5 commits, 24 stub-harness tests green, adversarial code-review done (0 crit / 0 high;
all 2-medium + low findings fixed). Ships: the **systemic** silent-corruption guard (now IN the repo +
git, closing the old deployment gap and superseding the Pass-0-only band-aid), per-seat model+effort
via a 3-layer resolver (Quick/Balanced/Max ceiling + optional per-judge pins; Fable only on the two
judges), the batched-AskUserQuestion setup + review-point rework, CHANGELOG.md, README updates, and the
version bump to 1.2.0. **Real end-to-end run DONE (2026-07-07):** a full Light 0→4 hands-off run on the
expense-tracker toy (`v12-smoke`, model_tier=balanced, 400k output-cap) completed ALL 5 passes — 21
agents, 0 errors / 0 empty results, ~786k tokens / ~17 min — the Fable judges + every per-seat model
ran live, and the artifacts are real + evidence-grounded (a coherent minimal-diff CSV-export build plan
that read the actual cli.py/store.py; kill-report correctly single-family-labeled; 5 scope-creep drops,
3 survivors). A separate model-id check confirmed haiku/sonnet/opus/fable are all valid engine ids incl.
fable:max. (The 400k cap never tripped — real output stayed under it, so the "smoke" run became a full
validation.) **PUBLISHED + LIVE (2026-07-07):** merged to `main` (`9dca67e`, via `-s ours` over two
band-aid commits that had landed on remote main — `1fe2dd8` gemini flags + `300da7e` null-map/dry-judge
— which v1.2 fully subsumes: gemini flags + dry-judge verbatim, `if(!map)` superseded by the systemic
guard), tagged `v1.2.0`, pushed to origin. Live install refreshed: registry `discover@discover` → new
`.../cache/discover/discover/1.2.0` dir + marketplace clone pulled to v1.2 (24-test harness green on the
live copy). Takes effect in the next session (plugins load at startup). **Nothing owed — v1.2 is live.**

**What this item is:** the single home for the discover plugin's evolution — every version, what
changed, what worked / didn't and why, the reusable facts, and the spec for the next version.
Update it on every release. Consolidates the history previously split across #7 (old tmux-era
skill mods, DONE) and #60 (the v1.1.0 rebuild, DONE) — those two remain as detailed build records;
this is the canonical ongoing log.

---

## Where the code + docs live

- **Source of truth (edit here):** `/root/work/claude-discover-publish/repo/` (branch `main`).
  - Pipeline script (every agent seat is spawned here): `skills/discover/workflows/discover-pipeline.js`
  - Front-of-house: `skills/discover/SKILL.md` · artifact inventory: `skills/discover/references/pass-templates.md`
  - README: `README.md` (+ mirror `/root/work/claude-discover-publish/extracted/discover-plugin/README.md`)
  - Version: `.claude-plugin/plugin.json` (currently `1.3.0`) + `.claude-plugin/marketplace.json`
  - Test rig: `tests/run-harness.mjs` (stub harness, keep green) · `tests/e2e-evidence.md`
- **Installed/live copy (read to compare, do NOT edit):** `/root/.claude/plugins/cache/discover/discover/1.3.0/skills/discover/`
- **Design docs (in the WORKSPACE, not the plugin repo):**
  - Plan (14 tasks + code): `docs/superpowers/plans/2026-07-02-discover-rebuild.md`
  - Spec (authority on ambiguity): `docs/superpowers/specs/2026-07-02-discover-rebuild-design.md`
  - Why-decisions history: `todo/kickoffs/discover-rebuild.md` · pressure-test: `.omc/research/discover-rebuild-pressure-test-2026-07-01.json`
- **Toy test project:** `/root/work/discover-toy/`
- Remote: `chopra2007/claude-discover` (public, user-owned). Publish flow: edit repo → re-run stub
  harness → bump `plugin.json` version → commit + push (push only with user OK).

---

## Version history / changelog (newest first)

### v1.3.0 — SHIPPED + LIVE (2026-07-12; main `f42e784`, tag `v1.3.0` on chopra2007/claude-discover)
Reusable codebase map. The last FULL scan is cached per repo at `<project>/.claude/discover/_map/`
(system-map.md + meta.json with the git commit it was built from). Next run auto-decides: nothing
changed → reuse verbatim, zero mappers; ≤100 changed files → ONE sonnet `delta-mapper` re-reads only
those and patches the map; else (missing cache / too stale / git unknown / `remap=fresh`) → full
fan-out, which is the only thing that rolls the cache forward (delta-patch errors can never compound).
Also fixed the same-run-restart hole: a `from_pass:0` relaunch whose run dir already holds
`pass-0-system-map.md` reparses it instead of re-running mappers (the Jul-6 run had paid for its map 3×).
Inline overrides `remap=fresh` / `remap=reuse`. Implementation notes vs the spec: the pipeline script
can't touch disk/git itself, so the cache probe (read `_map/` + `git diff --name-only sha..HEAD` +
`git status --porcelain`) rides the existing haiku `bootstrap` agent (new S_BOOT fields: map_cache,
map_cache_sha, git_diff_ok, changed_since_cache); noise paths (`.claude/`, `.omc/`, `.git/`) are
filtered in-script so artifact churn never defeats the cache; the reuse path copies the cached file
verbatim (no lossy re-render). +8 harness tests (32 total). Live-validated on the toy repo: full→cache
(real sha `f412635`), reuse (2 agents, ~62k tokens vs ~216k full), delta (picked up the new `count()`
function), restart-reuse. Commit `f42e784`.

### v1.2.0 — SHIPPED + LIVE (2026-07-07; main `9dca67e`, tag `v1.2.0` on chopra2007/claude-discover)
Per-seat model + effort via a resolver (L1 auto-from-complexity < L2 Quick/Balanced/Max ceiling < L3
per-seat pin; Fable only on the two judges; approach-enum upgraded haiku→Opus); the **systemic**
dead-agent guard (run-level `failed[]` + boundary halt at every pass, subsuming the Pass-0-only
band-aid); batched-AskUserQuestion setup + review-point rework (run_style derived from the ticks);
CHANGELOG.md, README + version bump to 1.2.0. Also ported the 2 other live-only fixes (dry-judge
"NOT a generator" hardening, Gemini `--skip-trust -y -m gemini-flash-latest`) and fixed the Gemini
booster-health probe. **24 stub-harness tests** (topology + 12 death-halt/floor + 6 resolver).
Adversarial review: 0 crit / 0 high; the 2 medium + lows all fixed (F1 researcher-wipeout floor,
F2 primary-synth cross-burst hand-off, F3 from_pass:4 reparse guard). Commits: `891f109` systemic
guard · `3085d1f` resolver · `5193bd7` setup UI · `02248a0` release docs · `4657655` review fixes.
All release steps DONE (2026-07-07): real Light 0→4 validation passed, merged to `main` (`9dca67e`),
tagged `v1.2.0`, pushed, live install refreshed to the 1.2.0 cache. **Nothing owed.** **Full spec in
the "v1.2 spec" section below.**

### v1.1.0 — 2026-07-02 (commit `e975d23`) — the Workflow-engine rebuild
Complete rewrite so passes 0–4 run on Claude Code's built-in Workflow engine (clean context,
reliable hand-offs, crash-proof disk-resume). Added evidence-rule kill-test, plan tournament,
Pass-5 probe gate, and cross-run outcome memory. **tmux removed entirely.** No required
dependencies (OMC/superpowers/Codex/Gemini optional). Key commits: `5ef8380` retire tmux + scaffold ·
`e14b9b0` passes 0–2 · `745cd1b` pass 3 · `c5ee298` pass 4 + burst dispatcher · `af64551` pass-5
probe gate + outcome memory · `5cc70aa` SKILL.md rewrite · `7e49b41` stub harness · `56550c3` README
rewrite (transient bump to 1.0.0) · `0e80f06` args parse-guard fix · `a68a026` e2e evidence +
measured budget · `e975d23` bump to 1.1.0. (Design + build recorded in #60.)

### v0.1.x — original tmux-based skill (superseded by v1.1.0)
The pre-rebuild skill: composed OMC + superpowers via tmux multi-agent panes. Later got 3 QoL
upgrades (commit `86b2383`, = TODO #7): verification-before-completion gate in Pass 5, a non-tmux
native parallel-agent option + free-form agent count, and the one-line kickoff prompt; plus
`53b7cbc` same-session Pass-5 build-now/review-then-build handoff. All of this was then absorbed or
replaced by the v1.1.0 engine rebuild.

---

## Insights ledger — what worked / what didn't and why

### What worked (keep doing)
- **Running passes on the built-in Workflow engine.** Clean per-agent context, reliable hand-offs,
  crash-proof resume; disk artifacts under `.claude/discover/<run>/` are the source of truth, engine
  journal is a throwaway cache. Validated by 3 real runs (full Light 0→4, budget-cap partial-return,
  disk-resume from_pass:4).
- **Evidence-rule kill-test.** An objection only kills if it cites an artifact inspected THIS run
  (file:line / command output / fetched URL); otherwise it auto-downgrades to a "concern." One
  proven fatal objection kills — no majority vote. Kept kills honest.
- **Symmetric, labeled reporting.** Kill report labels a single-AI-family panel prominently ("unanimity
  counts for less"); survivors show their strongest near-miss objection. Prevents false confidence.
- **Light dial is well-behaved:** 21 agents, ~794k output tokens, 18→3 survivors, high-quality
  artifacts (Pass-0 names real files; drops-log coded + evidenced; final-plan has all 8 sections +
  a live_probe per feature).

### What didn't work / gotchas (avoid / carry the fix forward)
- **⚠️ PROCESS SLIP (2026-07-07, running #67 via discover on the bot repo) — skipped the mandatory
  setup questions on a resume.** Two specific misses, both against the skill's own rule that "setup
  answers are parameter inputs, never silently defaulted":
  1. The #67 TODO pre-set Thoroughness / review-style / stop-point but did **not** specify the **model
     tier** — I silently defaulted it to Balanced instead of surfacing it for the user to choose.
  2. The **Gemini booster was down** (transient 503). The skill says to ask the user "pause & fix /
     proceed without it" — I decided to proceed on my own instead of asking.
  Mitigating fact (why the in-flight run wasn't actually harmed, but this is luck not process): a
  `from_pass:1→2` burst runs only research + filter, and neither the model tier (tunes the Pass-3/4
  judges) nor the boosters (Pass-4 cross-model only) touch those passes. **Lesson: present the batched
  setup question — and the booster pause/proceed question — even on a RESUME and even under a global
  "no-confirmation" rule. They are parameter inputs, not yes/no gates; an unspecified one (model tier)
  must be asked, never defaulted.**
- **⚠️ CRITICAL — silent corruption on an API error (the run that burned ~3.9M tokens, 2026-07-06).**
  During a real run, the `architect-merge` step (Pass 0) hit an API *server_error*. Its retry did real
  work, but the result never fed back into the pipeline's internal `map` variable, so `map` came back
  empty/null. Nothing checked for that, so the run continued: every research-agent thunk threw on the
  empty map and was silently swallowed to `null` (0 of 20 ever ran a web search), and the `dry-judge`
  dedup helper — handed nothing — **fabricated candidates out of thin air**, snowballing across all 5
  rounds. The run reported "COMPLETE — 143 ideas, all verified" with ZERO flags; the corruption only
  surfaced at the very end. (Root cause = API error; compounded by the assistant wrongly reassuring
  "nothing was lost" mid-retry instead of verifying — see memory `feedback_dont_reassure_on_inflight_retry`.)
  **Two-part fix (one-line core + a prompt hardening):**
  1. Guard right after `map = await passMap(); completed.push(0)` — **`if (!map) return partialReturn(completed, 'Pass 0 did not return a usable system map (the merge step failed - likely a transient API error) - cannot safely continue into Pass 1 with no map…')`** — fail loud instead of silently continuing.
  2. Harden the `dry-judge` prompt to "cheap dedup — **NOT a generator**": `new_candidates` MUST be a subset of what's literally in "New this round," never invent/rename/synthesize (even if the list is empty), and empty-in ⇒ `new_candidates=[]` + `dry=true`, no exceptions.
  **⚠️ The live fix is a per-STEP band-aid — the correct fix is SYSTEMIC (implement in v1.2).** The
  `if (!map)` guard only catches a death in Pass 0; an API error in Pass 1/2/3/4 corrupts the run the
  same way. Root cause is general: the engine returns `null` when an agent dies on a terminal API error
  (a *real* empty result is still a schema object, so **`null` ALWAYS means "died," never "nothing found"**),
  and the pipeline swallows nulls everywhere via bare `.filter(Boolean)` / unchecked assignments (sites:
  `views` in passMap, `found` in passResearch, `verified` in passFilter, `panel` in passKill, `plans` +
  `xnotes` in passPlan). **Single systemic fix, applied regardless of which step fails:**
  (a) route every `agent()` call through ONE wrapper that pushes to a run-level `failed[]` list when a
      NON-optional call returns null (record the label);
  (b) check `failed.length` at each pass boundary by folding it into the existing
      `if (!gate(n)) return partialReturn(...)` guards → a death at ANY step halts loud + resumable at the
      next boundary (subsumes the `if (!map)` guard);
  (c) for parallel pools, replace silent `.filter(Boolean)` with "require ≥ a floor of survivors (≥1),
      else abort; LOG any partial losses" — so a total wipeout can never fabricate from nothing;
  (d) mark genuinely-advisory calls (`xmodel` cross-model auditor, `coherence-check`) `optional:true` so
      they don't trip the flag. The dry-judge hardening then becomes belt-and-suspenders.
  **✅ DEPLOYMENT GAP — RESOLVED 2026-07-07 (in the v1.2 branch, commit `891f109`).** The v1.2 build
  implemented the SYSTEMIC guard in the repo — a run-level `failed[]` + boundary halt at every pass that
  subsumes the live Pass-0-only `if (!map)` band-aid — and ported the dry-judge hardening + Gemini CLI
  flags. All three live-only fixes are now IN the repo + git on branch `v1.2-per-seat-model-effort`, so a
  publish from the repo no longer re-introduces the bug. It also closed 3 edges the band-aid never had
  (researcher total-wipeout, primary-synth cross-burst hand-off, redundancy-verifier crash). Residual:
  the LIVE installed copy is still v1.1.0 (band-aid only) until v1.2 is published. (Original gap below, for history.)
  **DEPLOYMENT GAP (verified 2026-07-06, ~3h after the fix session):** both fixes are PRESENT in the
  LIVE installed copies — `…/cache/discover/discover/1.1.0/…` (guard at line 292, dry-judge at line 145)
  and the `…/marketplaces/discover/…` copy (both mtime 07-06 18:00 PT) — but **ABSENT from the
  source-of-truth repo** (`/root/work/claude-discover-publish/repo/`, still the 07-02 v1.1.0 state) and
  **not in git history** (`git log -S "if (!map) return partialReturn"` → nothing; tree clean). So the
  fix will be LOST on the next publish/plugin-update from the repo, and a v1.2 build editing the repo
  starts from an unfixed base. **→ Port both fixes into the repo and commit BEFORE / as the first step of v1.2.**
- **`const A = args` crashed instantly.** The Workflow engine delivers `args` as a JSON *string*,
  not an object. Fixed with a parse-guard: `const A = typeof args === 'string' ? JSON.parse(args) : args`.
  Any NEW arg (v1.2's model tier, per-seat pins, review-point list) rides the same channel — keep the guard.
- **Budget metering mismatch.** `budget.spent()` meters OUTPUT tokens, but `passEst` was sized against
  TOTAL spend — mechanism is correct, exact trip point is a calibration nicety. Standard/Deep budgets
  are still EXTRAPOLATED (only Light measured). Changing models (v1.2) shifts per-pass spend → re-measure.
- **tmux as a hard prerequisite (v0.1.x) was a barrier.** Removed in v1.1.0. Lesson: don't hard-require
  an environment tool when a native path exists.
- **Pasting EXECUTE.md contents inline as a kickoff prompt** violated the one-line-kickoff preference.
  Fixed to a single trigger line (`discover: build <name>`); details are read from disk. Keep this.
- **Not yet exercised in real beta (deferred, run if a bug shows):** B1 checkpoint-edit override, B2
  kill+override, B4 mid-burst crash-resume, B5 broken booster, B6 vanilla-user (no boosters), B7
  outcome read-back, B8 old-run-dir message, B9 per-pass budget calibration. Windows untested.

### Design principles established this session (drive v1.2, carry forward)
- **Model fit is per-SEAT, not per-run** — one run contains mechanical, execution, reasoning, and
  judgment work simultaneously, so a single global model choice is the wrong shape.
- **Model and effort are independent dials:** model = the *kind* of thinking (stable per seat);
  effort = *how hard this run is* (varies). For simple-vs-complex, **effort moves first, model second.**
- **Fable only where a single wrong call silently poisons everything** — the two judges.
- **Coarse control = a ceiling filled by measured complexity, not a static level** (see v1.2 spec).

---

## Repo docs & release checklist (per the user: document each version + update README)

Current repo state (2026-07-06): `plugin.json` = **1.1.0**; **no `CHANGELOG.md`**; **no git tags**;
README (150 lines) is accurate for v1.1.0 but says nothing about model/effort or the v1.2 setup UI.

On the v1.2 release (and every release after), do all of:
0. **Fix the silent-corruption bug in the repo FIRST** — two levels (see the ⚠️ CRITICAL gotcha above):
   at minimum port the live band-aid (map-guard + dry-judge hardening) into
   `/root/work/claude-discover-publish/repo/` so the repo isn't worse than production; **better, implement
   the SYSTEMIC dead-agent guard** (one wrapper + a run-level `failed[]` flag checked at every pass
   boundary + parallel-pool survivor floor) so an API death at ANY step halts loud instead of only Pass 0.
   The live fix is absent from git, so without this the next publish re-introduces the bug. Re-verify
   live-vs-repo before starting.
1. **Add/maintain `CHANGELOG.md`** in the repo root (it doesn't exist yet). Seed it from the version
   history above (v0.1.x → v1.1.0 → v1.2), then add one dated entry per release. Keep-a-Changelog style.
2. **Tag the release in git** (`git tag v1.2.0`) — there are currently no tags, so versions are only
   discoverable from commit messages + plugin.json. Tagging makes history navigable.
3. **Bump `plugin.json` + `marketplace.json`** version.
4. **Update `README.md`** (both the repo copy and the `extracted/` mirror) for what v1.2 changes:
   - **Setup questions** section — document the new Model tier (Quick/Balanced/Max) dial and the
     multi-select review points; clarify Thoroughness (breadth) vs Model tier (depth) so they don't blur.
   - **"How it works"** — a short note that discover picks a model + thinking-depth per step (cheap for
     busywork, strongest only for the make-or-break judge calls), auto-tuned to run complexity.
   - **Usage / power-user** — the optional per-seat pin (`judge=fable:max`) alongside the existing `budget=N`.
5. Re-run the stub harness + one real Light 0→4 on the toy project before pushing (spend shifts with
   the new model mix). Push only with user OK.

---

## v1.2 spec — per-seat model/effort + cleaner setup UI (build-ready)

### How the engine picks a model today (starting point)
`agent()` **inherits the session model** when no `model:` is given. The script pins only 6 calls to
`haiku` (`dry-judge-r{round}`, `approach-enum`, `reparse-map`, `reparse-filtered`, `reparse-kill`,
`burst-summary`); everything else floats on whatever model launched the session. Realizing v1.2 =
add `model:` + `effort:` to each `agent()` call, resolved from the 3-layer control below. `agent()`
already accepts both (`opts.model`, `opts.effort` ∈ low|medium|high|xhigh|max).

### CHANGE 1 — Per-seat model allocation
Rule: match the model to (a) the *kind* of thinking and (b) how badly a wrong answer hurts if
nothing downstream catches it. Fable only where both peak.

| Agent label | Model | Why |
|---|---|---|
| `bootstrap`, `reparse-*` | Haiku | Read files / markdown→data. Mechanical. *(reparse already haiku)* |
| `mapper-{i}` (×2/3/5) | Sonnet | Reads real code, faithful inventory; many run at once. |
| `architect-merge` (×1) | Opus | The one foundational map; nothing re-checks it whole. *(Fable-upgrade candidate)* |
| `researcher-{i}-r{round}` (×up to 4/9/20) | Sonnet | Web research + source grading; biggest, cost-sensitive pool. |
| `dry-judge-r{round}` | Haiku | Cheap dedup by design *(already haiku; bump to Sonnet if lists come out thin — it decides when research STOPS)*. |
| `filter-analyst` (×1) | Opus | Ranks the shortlist + sets the cut. **#1 Fable-upgrade candidate** (silently drops below-cut ideas). |
| `redundancy:{name}` (×N) | Sonnet | Reads code to confirm "already exists"; bounded, is itself a safeguard. |
| `skeptic:{lens}` (×2/3/5) | Opus | The flaw-finding muscle; the Fable judge backstops it. |
| `advocate` (×1) | Opus | Must match skeptic strength. |
| `judge` (×1) | **Fable** | One UPHELD silently kills an idea — no vote, no appeal. |
| `xmodel:{fam}` (×0–2) | Sonnet | Claude part only composes a prompt + shells to Codex/Gemini + parses (Haiku ok). |
| `approach-enum` (×0–1) | **Opus** | **Currently haiku — real mis-fit:** it gates whether the plan tournament runs at all. Biggest quality-per-dollar fix. |
| `plan:{stance}` (×1/2/3) | Opus | The actual architecture work. |
| `tournament-judge` (×0–1) | **Fable** | Picks the winning plan; greps code to check claims. Decides what gets built. |
| `plan-reviser` (×0–1) | Opus | Rebuilds the winner into one coherent final spec. |
| `coherence-check` (×0–1) | Opus | Last guard on the deliverable (Sonnet acceptable). |
| all `synth:*`, `burst-summary` | Haiku | Render decided data → markdown. *(burst-summary already haiku)* |

Cost shape: Fable ≤ 2 single calls/run (both judges; Light runs no tournament so ≤1). Opus = a few
single calls + small skeptic/plan pools. Sonnet = the big parallel pools. Haiku = all ~10
formatting/parse calls. Cheapest model on the most calls, dearest on the fewest highest-stakes.

### CHANGE 2 — Effort as a second, independent dial
Effort is primary for simple-vs-complex; model secondary. Effort only pays off on Opus/Fable
reasoning seats — mechanical Haiku seats run `low` always.

| Seat | Simple refactor | Complex / creative |
|---|---|---|
| Tournament judge | Opus·high — or Fable·low | Fable·max |
| Kill judge | Opus·high | Fable·high–max |
| Skeptics | Opus·medium | Opus·high |
| Rival planners | Opus·medium | Opus·high (Fable·high if truly novel) |
| Filter-analyst | Opus·medium | Opus·high |
| Mappers / researchers / all formatting | unchanged · low | unchanged · low |

### CHANGE 3 — The 3-layer control (resolves model + effort)
- **Layer 1 — Automatic (default):** set judge-seat effort from the run's OWN measured complexity —
  tournament judge ← `approach-enum` distinct-architecture count (narrow→medium, wide→max); kill
  judge ← number of kill-eligible objections (one clean→medium, many contested→max).
- **Layer 2 — Coarse control = Quick / Balanced / Max preset (a CEILING, not a level):** how high the
  judgment seats may climb; Layer 1 fills underneath. Quick = cap Opus·high (never Fable); Balanced =
  Opus default, reaches Fable·high only when complex; Max = Fable·max. **Mechanical seats stay
  Haiku·low at every preset** (the invariant — why a single global model question is wrong).
- **Layer 3 — Optional per-seat pin (power user):** typed like `budget=N` → `discover: <name> judge=fable:max`;
  or a guided follow-up AskUserQuestion exposing just the two judges, each defaulting to Auto.
- **Precedence:** pin (L3) > preset ceiling (L2) > auto-from-complexity (L1).
- User-facing: never type an effort number; optionally pick Quick/Balanced/Max; run auto-tunes underneath.

### CHANGE 4 — AskUserQuestion for all fixed-choice selections
Every fixed 2–4-option decision uses AskUserQuestion. Free-text stays prose: the run **Name** (tool
needs ≥2 real options → keep Name a text confirm) and open-ended checkpoint edits ("reword X").
**Batch the setup into ONE call** (≤4 questions): Thoroughness, Model tier, Reviews, After-the-plan.

Setup mock (one call):
```
Thoroughness (single) — how WIDE (how many agents): Light / ●Standard / Deep
Model tier   (single) — how STRONG (a ceiling): Quick / ●Balanced / Max
                        (Quick = cheaper models; distinct from Light = fewer agents)
Reviews  (MULTI-select) — where to pause; tick none = hands-off:
   ☐ After the map (0, usually skip) ☐ After research (1, usually skip)
   ☑ After the shortlist (2)         ☐ After the kill-test (3, auto-pauses if something dies)
After the plan (single) — ●Build it now / Stop at the plan (build later)
```
Fine-override mock (only if user asks to hand-tune): one question per judge —
`Kill judge` / `Plan judge`, options ●Auto / Opus·high / Fable·high / Fable·max.

Run-style rework details:
- Old rigid 3-way (Hands-off/Checkpoints/Plan-only) → multi-select review points + a build-now/stop
  binary. Preserves all three: none-ticked+build = Hands-off; some ticks+build = Checkpoints; build→stop = Plan-only.
- **Label reviews in plain English, NOT "pass N."**
- **Plan review is ALWAYS-ON** (even Hands-off shows the plan for one OK before any code) → not a checkbox.
- **Don't lose Plan-only** — it's the build-later path (writes EXECUTE.md + `discover: build <name>`; keep the one-line kickoff, #7's 7c rule).
- Steps 0/1 are low-value AND each extra stop splits the bundled 0→2 burst (reparse round-trips). Pre-check only "After the shortlist."
- Keep the smart default: kill review auto-fires only if `counts.kills>0` or `decisions_needed` non-empty; honor an explicit tick on top.
- Other AskUserQuestion points: booster-health (pause/proceed), existing-run (resume/restart), shortlist drops (multi-select over the live list). Preset names settled: **Quick / Balanced / Max**.

---

## Optional future change — `from_pass=1` resume (documented, NOT shipped)

**Why this is here (user request 2026-07-07):** TODO #67 needed to resume a discover run at the
*research* pass — reuse an already-saved `pass-0-system-map.md` and run Research + Filter fresh,
skipping the codebase re-scan. The installed plugin can't do that: the burst dispatcher's `else` branch
(any `from_pass>0`) only reparses saved artifacts and jumps to kill/plan, so a `from_pass:1` burst
reparses the map and then runs *nothing*. This capability was added + used for the single #67 run
(validated: Deep `from_pass:1→2` → completed `[1,2]`, 39 agents, 0 errors, 40 grounded ideas) and then
**reverted** — wanted for that run only, not permanent. This is the copy-paste recipe to make it
permanent if ever wanted.

**The change — one spot:** `skills/discover/workflows/discover-pipeline.js`, the `else` branch of the
burst dispatcher (~line 397, right after `if (reparse) map = reparse`). Replace:

```js
    if (A.from_pass <= 3) { // filtered.kept only feeds passKill (from_pass<=3); a from_pass:4 resume never uses it, so don't halt on its reparse
      const refilter = await call(`${PRE}\nParse the saved pass-2 artifact back into {kept, drops} structured form. HUMAN CHECKPOINT EDITS OVERRIDE the artifact - apply them (drop = remove from kept; note rewordings): edits=${JSON.stringify(boot.user_edits)}\nARTIFACT:\n${boot.artifacts.filtered}`, { label: 'reparse-filtered', phase: 'Bootstrap', schema: S_FILTER })
      filtered = refilter || { kept: [], drops: [] }
    }
    if (failed.length) return partialReturn(completed, deathMsg())
```

with (move the death-halt guard to fire right after the map reparse, add a `from_pass===1` branch that
runs the same research→filter tail as a fresh `from_pass:0` run minus `passMap()`, and add a guard after
the filtered reparse):

```js
    if (failed.length) return partialReturn(completed, deathMsg())
    if (A.from_pass === 1) {
      // Resume with the saved Pass-0 map: run Research + Filter fresh (the from_pass:0 tail, minus passMap).
      if (!gate(1)) return partialReturn(completed, 'Budget exhausted before Pass 1.')
      candidates = await passResearch(map)
      if (failed.length) return partialReturn(completed, deathMsg())
      completed.push(1)
      if (!gate(2)) return partialReturn(completed, 'Budget exhausted after Pass 1.')
      filtered = await passFilter(map, candidates, boot.artifacts.outcomes_prior, boot.user_edits)
      if (failed.length) return partialReturn(completed, deathMsg())
      completed.push(2)
    } else if (A.from_pass <= 3) { // filtered.kept only feeds passKill (from_pass<=3); a from_pass:4 resume never uses it, so don't halt on its reparse
      const refilter = await call(`${PRE}\nParse the saved pass-2 artifact back into {kept, drops} structured form. HUMAN CHECKPOINT EDITS OVERRIDE the artifact - apply them (drop = remove from kept; note rewordings): edits=${JSON.stringify(boot.user_edits)}\nARTIFACT:\n${boot.artifacts.filtered}`, { label: 'reparse-filtered', phase: 'Bootstrap', schema: S_FILTER })
      filtered = refilter || { kept: [], drops: [] }
      if (failed.length) return partialReturn(completed, deathMsg())
    }
```

Passes 0/3/4 behave exactly as before. `from_pass:2` (reuse a saved *candidate* list) is still NOT
handled — it falls through to the reparse-filtered branch; add it symmetrically only if needed (reparse
`pass-1-candidates.md`, re-assign `c{i}` ids, then run `passFilter`).

**Tests (`tests/run-harness.mjs`, +2 → 26 total):** a `savedMapBoot` responder returning
`{ found:true, artifacts:{ map:'…', candidates:'', filtered:'', … } }`, then
`from-pass-1-resume-runs-research-and-filter` (assert `completed_passes===[1,2]`, no mapper/architect
ran, researcher + filter-analyst ran, `reparse-map` ran, no skeptic) and `from-pass-1-research-death-halts`
(researcher returns null → run halts, Pass 1 not marked complete).

**Ship steps if adopted:** bump `plugin.json` + `marketplace.json` (→ e.g. 1.2.1), add a CHANGELOG entry,
re-run the harness (26 green), commit + tag + push (user OK), refresh the installed cache. The full patch
+ tests were validated live 2026-07-07 (local commit `e010f53`, since reverted — recoverable from this
recipe or `git reflog` on `/root/work/claude-discover-publish/repo`).

## v1.3 spec — reusable codebase map (SHIPPED 2026-07-12 — kept for history; see the v1.3.0 changelog entry above for what actually landed)

**Goal:** a discover run should never re-read the whole repo when a fresh-enough map already exists.
Reuse the saved map, and only re-read the files that changed since it was built.

**Evidence (measured 2026-07-12 from the real agent transcripts under
`/root/.claude/projects/-home-openclaw--openclaw-workspace/*/subagents/workflows/`):**

| Run | Mappers | Tokens in the map phase | Share of that run |
|---|---|---|---|
| `todo-55-20-plan` (Jul 11, standard) | 3 + architect | ~4.6M (fresh-read portion ~0.8M) | ~23% |
| `next-features-jul2026` (Jul 6–7, deep) | 5 + architect, **run 3×** | ~100M (fresh ~5M) | ~50% |

Most of the volume is cached context re-reads (billed ~10%), but the fresh reading is real and repeats
every run for a repo that barely changes week to week.

**Two holes in `skills/discover/workflows/discover-pipeline.js` (v1.2.0):**

1. **No reuse across runs.** `passMap()` (~line 196) always fans out `DIAL.mappers` agents that read the
   repo from scratch. Prior runs' `pass-0-system-map.md` files are never consulted — `bootstrap()` only
   reads the *current* run dir (plus other runs' `outcome.json`).
2. **No reuse within a run.** The burst dispatcher (~line 385) does `if (A.from_pass === 0) { map = await
   passMap() }` **unconditionally** — even when `boot.artifacts.map` is already on disk from an earlier
   attempt at the same run. This is what paid for the Jul-6 map three times.

**The change:**

- **Repo-level map cache:** `<project_root>/.claude/discover/_map/system-map.md` + `_map/meta.json`
  (`{git_sha, built_at, files_hashed_count, dial}`). `passMap()` writes it on every full map.
- **Delta path.** At the start of `passMap()`: if the cache exists, get the changed files with
  `git diff --name-only <cached_sha>..HEAD` (plus `git status --porcelain` for uncommitted work).
  - 0 changed source files → reuse the cached map verbatim, **zero mapper agents**; log it.
  - 1..N changed (N ≈ 100, tunable — this is the one judgment call) → **one** `delta-mapper` agent that
    reads ONLY those files plus the cached map, and returns the patched map. Then the usual `synth` to
    `pass-0-system-map.md`.
  - more than N changed, cache missing, or `remap=fresh` typed by the user → full `DIAL.mappers` fan-out
    exactly as today.
- **Plug hole 2:** in the dispatcher, `if (A.from_pass === 0)` → reuse `boot.artifacts.map` (reparse it,
  same as the `else` branch does) instead of calling `passMap()` when the current run dir already has a
  map, unless the user forced a fresh map.
- **User control:** honour a typed `remap=fresh` (force full) / `remap=reuse` (force cache, skip the git
  check) in the setup step; default = auto (the rules above). Mention the choice in the burst summary
  ("reused the map from commit abc1234, 12 files changed since — re-read only those").

**Expected saving:** on a typical week-later run (~20 changed files) the map phase drops from
3–5 whole-repo readers to one small delta reader — roughly 90% off Pass 0, which is 20–50% of the run.

**Tests (`tests/run-harness.mjs`):** (a) cache present + no diff → `completed_passes` still includes 0,
zero `mapper-*` agents ran, map artifact written from cache; (b) cache present + small diff → exactly one
`delta-mapper` ran, no full mappers; (c) cache present + huge diff → full fan-out; (d) no cache → full
fan-out (today's behaviour, unchanged); (e) same-run restart with `pass-0-system-map.md` on disk → no
mapper agents.

**Ship steps:** edit in `/root/work/claude-discover-publish/repo/`, bump to 1.3.0 (`plugin.json` +
`marketplace.json`), CHANGELOG entry, harness green, one real Light 0→4 run to prove the delta path,
commit + tag + push, refresh the installed cache at `/root/.claude/plugins/cache/discover/discover/`.

**Open decision for the build session:** the "too stale, just re-map" threshold (files changed, and/or
commits behind). Start at 100 changed source files; note whatever is picked in the script.

## Open questions for the build session
- Exact Layer-1 effort thresholds (architecture-count / objection-count → medium vs high vs max). Pick + note in script.
- Whether to expose `plan writers` / `skeptics` in the fine-override picker (recommendation: no — stop at the two judges).
- Where the resolved (seat → model, effort) table is assembled (a small resolver from preset + pins + Layer-1 signals) and threaded into `agent()` calls.
- Re-measure `passEst`/breaker after wiring models (spend shifts) and re-run the stub harness + one real Light 0→4.

### Session notes — 2026-07-12
- **Worked on:** Built, tested, and shipped v1.3.0 (reusable codebase map) end-to-end: pipeline change (~60 lines), 8 new harness tests (32 green), CHANGELOG/README/SKILL.md/version bumps, 4 real engine runs on the toy repo proving all paths, pushed main `f42e784` + tag `v1.3.0`, refreshed the installed 1.3.0 cache.
- **Decisions:** kept the spec's cache-only-rolls-forward-on-full-scan rule (self-limits patch drift); cache probe rides the existing bootstrap agent (script can't run git itself); reuse path copies the cached file verbatim instead of re-rendering; staleness cap left at 100 changed files; noise paths (.claude/.omc/.git) filtered so artifact churn can't defeat the cache.
- **Next:** nothing owed on v1.3. Next real discover run on the bot repo will build its cache on the first full scan, then get the savings.

### Session notes — 2026-07-14 (first real v1.3 run on the bot repo — 2 weaknesses found)
Run `menu-top10` (TODO #76, pick + build the 10 strongest menu candidates) was the first discover run
on this repo since v1.3 shipped. It behaved exactly as designed — no cache existed, so it paid for one
full scan and wrote the cache — but attempting to seed the cache by hand from an older run's map
surfaced two real gaps. **Neither is fixed yet.**

**GAP 1 — the staleness cap counts files the map does not model.** The `changed_since_cache` filter
drops only `.claude/` `.omc/` `.git/`; everything else counts toward `MAP_DELTA_CAP = 100`. On this
repo, of the 126 files changed since the Jul-6 map, **41 were markdown** (`TODO.md` + `todo/*.md`
churn — this project rewrites those every session). Documentation the map never inventoried burned a
third of the staleness budget and helped push the run over the cap into a needless full re-scan.
**Fix:** count only what the map actually models (source + config), or weight docs at zero. On a
doc-heavy repo the cache will otherwise expire far sooner than the code justifies.

**GAP 2 — the cache stores whatever Pass 0 produced, and Pass 0 is feature-flavoured. This one can
silently poison a run.** Evidence: run `todo-55-20-plan` (2026-07-11) did a legitimate full scan, but
its `pass-0-system-map.md` is titled *"System Map — #55 Catalyst-Classified Analyst Scorecard + #20
Wolf Confluence Timing"* and contains **zero mentions of `options.py`, `embed.py`, `cross_asset.py`,
`sec_edgar.py` or `commands.py`** — it mapped only the two features that run was about. It predates
v1.3 so it never became the cache. **Had it run one day later, it would have.** The next run (this one
— 10 features living in precisely those un-mapped files) would then have hit the delta path, which
instructs the mapper to *"start from the saved map … keep everything else verbatim"* — i.e. inherit a
map that is blank exactly where the new work lives, and never notice. I caught it only because I
opened the file before trusting it; the pipeline would not have.
**Fix (pick one):** (a) have Pass 0 write a *neutral repo inventory* to the cache, separate from the
feature-scoped map the run itself consumes; or (b) record in `meta.json` which areas the scan actually
verified, and force a full re-scan when the new feature ask touches areas the cache never covered.
Option (a) is cleaner — a repo-level cache should not carry one run's framing.

**Also worth knowing:** the "reuse verbatim, nothing changed" path is safe — the risk is concentrated
entirely in the delta path, because that is the one that presents a stale/narrow map as complete.
