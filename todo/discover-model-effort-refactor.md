# Refactor discover — per-seat model/effort allocation + cleaner setup UI

**Status:** OPEN
**Created:** 2026-07-06

**CURRENT STATUS (2026-07-06):** Design fully agreed in a Q&A session (no code written). This
file IS the spec — a fresh session can open it cold and implement. Builds on the v1.1.0 plugin
shipped in #60. Four changes: (1) assign a specific model to every agent seat instead of letting
them all inherit the session model; (2) add an independent per-seat *effort* dial; (3) wrap both
in a 3-layer control (auto → coarse Quick/Balanced/Max ceiling → optional per-seat pin); (4) move
every fixed-choice question onto the AskUserQuestion tool, and rework run-style into a multi-select
of review points. Next concrete step: edit the pipeline script + SKILL.md in the source-of-truth
repo, re-run the stub harness, bump the version, publish.

## Where the code lives (edit source, not the cache)

- **Source of truth (edit here):** `/root/work/claude-discover-publish/repo/` (branch `main`).
  - Pipeline script: `skills/discover/workflows/discover-pipeline.js` — this is where every agent
    seat is spawned; model/effort assignment happens here.
  - `skills/discover/SKILL.md` — the setup-questions / run-style / checkpoint front-of-house.
  - `skills/discover/references/pass-templates.md` — artifact inventory (no shapes; don't drift).
- **Installed/live copy (read to compare, do NOT edit):**
  `/root/.claude/plugins/cache/discover/discover/1.1.0/skills/discover/`
- Publish flow: edit repo → re-run `tests/run-harness.mjs` (stub harness, must stay green) → bump
  version in `.claude-plugin/plugin.json` → commit + push to `chopra2007/claude-discover`.
- Remote: `chopra2007/claude-discover` (public). #60's record: `discover_rebuild_build.md`.

## How the engine picks a model today (the starting point)

The Workflow engine's `agent()` call **inherits the session model** when no `model:` is given.
The script currently pins only **6 calls** to `haiku`, everything else floats on whatever model
the user launched the session with. So today: open discover in an Opus session and you pay Opus to
format markdown; open it in a Sonnet session and your kill-judge is only Sonnet. That blunt flood
is the thing this refactor fixes.

Currently-pinned haiku calls: `dry-judge-r{round}`, `approach-enum`, `reparse-map`,
`reparse-filtered`, `reparse-kill`, `burst-summary`. Everything else inherits.

Realizing this refactor = add `model:` and `effort:` to each `agent()` call (and read them from a
resolved config that the 3-layer control below produces). `agent()` already accepts both
(`opts.model`, `opts.effort` ∈ low|medium|high|xhigh|max).

---

## CHANGE 1 — Per-seat model allocation

Guiding rule: match the model to **(a)** the *kind* of thinking (mechanical → read/check →
reasoning → final judgment) and **(b)** how badly a wrong answer hurts if nothing downstream
catches it. Fable only where BOTH peak: a single, irreversible judgment call with no second check.

Model roles (as the user framed them): Fable = best judgment; Opus = architecture/complex
analysis; Sonnet = solid detailed execution; Haiku = mechanical, no reasoning.

### Full seat map (agent label → model → why)

**Bootstrap**
- `bootstrap` (reads saved files back) → **Haiku** — just reads and returns text.
- `reparse-map` / `reparse-filtered` / `reparse-kill` (resume only) → **Haiku** — markdown→data. *(already haiku)*

**Pass 0 — Map**
- `mapper-{i}` ×(2/3/5) → **Sonnet** — reads real code, faithful inventory; many run at once.
- `architect-merge` ×1 → **Opus** — merges into the one foundational map; nothing re-checks it whole. *(top secondary Fable-upgrade candidate)*
- `synth:pass-0-system-map.md` → **Haiku** — renders decided data to markdown.

**Pass 1 — Research**
- `researcher-{i}-r{round}` ×(up to 4/9/20) → **Sonnet** — web research + source-quality grading; biggest pool, cost-sensitive.
- `dry-judge-r{round}` → **Haiku** — cheap dedup by design. *(already haiku; see Change-1 caveat)*
- `synth:pass-1-candidates.md` → **Haiku**.

**Pass 2 — Filter**
- `filter-analyst` ×1 → **Opus** — ranks the shortlist + sets the p3cap cut. **#1 candidate for a Fable upgrade** (its ranking silently drops below-cut ideas; not independently re-verified).
- `redundancy:{name}` ×N → **Sonnet** — reads code to confirm "already exists"; bounded, is itself a safeguard.
- `synth:pass-2-filtered.md`, `synth:drops-log` → **Haiku**.

**Pass 3 — Kill-test**
- `skeptic:{lens}` ×(2/3/5) → **Opus** — the flaw-finding muscle; the Fable judge backstops it.
- `advocate` ×1 → **Opus** — must match skeptic strength.
- `judge` ×1 → **Fable** — one UPHELD silently kills an idea, no vote, no appeal. Highest-stakes single call in the pass.
- `xmodel:{fam}` ×(0–2) → **Sonnet** — the Claude part only composes a prompt, shells out to Codex/Gemini, and parses. (Haiku acceptable.)
- `synth:pass-3-kill-report.md`, `synth:drops-log` → **Haiku**.

**Pass 4 — Plan**
- `approach-enum` ×(0–1) → **Opus** — **currently haiku; real mis-fit.** It judges "how many materially distinct architectures exist" and thereby gates whether the whole plan tournament runs. A haiku lowball silently collapses Pass 4 to a single plan. Upgrade to Opus (Sonnet floor). *(biggest quality-per-dollar fix in the script)*
- `plan:{stance}` ×(1/2/3) → **Opus** — the actual architecture work.
- `tournament-judge` ×(0–1) → **Fable** — picks the winning plan; greps code to check each plan's claims. Decides what gets built.
- `plan-reviser` ×(0–1) → **Opus** — rebuilds the winner as one coherent final spec.
- `coherence-check` ×(0–1) → **Opus** — last guard on the deliverable (Sonnet acceptable).
- `synth:final-plan.md` / `synth:build-next.md` / `synth:EXECUTE.md` → **Haiku** (use Sonnet on final-plan if you want nicer build-spec prose).

**End**
- `burst-summary` → **Haiku**. *(already haiku)*

**Cost shape this produces:** Fable ≤ 2 single calls per full run (kill judge + tournament judge),
and Light runs no tournament (rivals=1) so Fable is at most the kill judge. Opus = a handful of
single calls + the small skeptic/plan pools. Sonnet = the big parallel pools (mappers, researchers,
verifiers). Haiku = all ~10 formatting/parse calls. Cheapest model on the most calls, dearest on
the fewest highest-stakes. (Reference: validated Light run = 21 agents / ~794k output tokens.)

**Caveats to decide at build time:**
- `dry-judge` (haiku) decides when research STOPS. If candidate lists come out thin, bump to Sonnet.
- `filter-analyst` and `architect-merge` are the two seats to raise to Fable first if the user wants to spend more.

---

## CHANGE 2 — Effort as a second, independent dial

Two dials per seat: **model** (kind of thinking — stable per seat) and **effort** (how hard THIS
run is — varies). For "simple vs complex," **effort is the primary lever, model the secondary**:
Fable·low → Fable·max is a bigger, finer swing than dropping Fable→Opus, and it keeps the seat's
reliability. Effort only pays off on the Opus/Fable reasoning seats — mechanical Haiku seats run
`low` always (formatting/parsing barely moves with effort).

Effort profile by seat, and how it shifts with run difficulty (model · effort):

| Seat | Simple refactor | Complex / creative |
|---|---|---|
| Tournament judge | Opus·high — or Fable·low | Fable·max |
| Kill judge | Opus·high | Fable·high–max |
| Skeptics | Opus·medium | Opus·high |
| Rival planners | Opus·medium | Opus·high (Fable·high if truly novel) |
| Filter-analyst | Opus·medium | Opus·high |
| Mappers / researchers / all formatting | unchanged · low | unchanged · low |

---

## CHANGE 3 — The 3-layer control that resolves model + effort

**Layer 1 — Automatic (default).** Set effort on the judgment seats from the run's OWN measured
complexity, mid-flight — no pre-run guess:
- Tournament judge effort ← `approach-enum`'s distinct-architecture count (narrow → medium, wide → max).
- Kill judge effort ← number of kill-eligible objections (one clean → medium, many contested → max).

**Layer 2 — One coarse control = the Quick / Balanced / Max preset (a CEILING, not a level).**
It sets how high the judgment seats are *allowed* to climb; Layer 1 fills in underneath it.
- **Quick** — cap Opus·high; never spends Fable. Small, low-stakes refactors.
- **Balanced (default)** — Opus by default; reaches Fable·high only when the run proves complex.
- **Max** — Fable·max on the judgment calls. Big or creative builds.
- Mechanical seats stay Haiku·low at EVERY preset (the invariant — this is why a single global
  model question is wrong and a spread-preserving ceiling is right).

**Layer 3 — Optional per-seat pin (power user).** Two entry points:
- Typed on invocation, mirroring the existing `budget=N`: `discover: <name> judge=fable:max`.
- Guided follow-up AskUserQuestion (shown ONLY if the user asks to hand-tune) — exposes just the
  two judges, each defaulting to **Auto**, so you override only the seat you care about.

**Precedence (the rule that ties it together):** a pin (L3) wins → else the preset ceiling (L2)
caps it → else Auto (L1) picks a point at/under that cap from measured complexity. An explicit pin
overrides the ceiling for that one seat.

User-facing takeaway: the user never types an effort number. They optionally pick Quick/Balanced/Max;
the run auto-tunes underneath; a power user can pin one judge if they go looking.

---

## CHANGE 4 — AskUserQuestion for all fixed-choice selections

**Rule:** every fixed 2–4-option decision uses AskUserQuestion (clean picker). Free-text values do
NOT (the run **Name** — the tool needs ≥2 real options, so keep Name as a quick text confirm; and
open-ended checkpoint edits like "reword X"). Multi-select (checklist) is available and used below.

**Batch the whole setup into ONE AskUserQuestion call** (tool caps at 4 questions/call), matching
the skill's existing "ask all in one message" rule. Name is a text confirm just before it. The four
batched questions: Thoroughness, Model tier, Reviews, After-the-plan.

### Mock — setup (one call)
```
Q  Thoroughness (single) — "How wide should the search go (how many agents dig in parallel)?"
   ○ Light                  Quick sweep: 2 mappers, 2 research rounds, 2 skeptics, 1 plan. Small spend.
   ● Standard (Recommended) Balanced default: 3 / 3 / 3, 2 rival plans.
   ○ Deep                   Exhaustive: 5 mappers, up to 5 rounds, 5 skeptics, 3 rival plans.

Q  Model tier (single) — "How strong should the agents be? A ceiling — the run spends up to it
                          only on the calls that turn out hard. (Separate from Thoroughness = how MANY.)"
   ○ Quick                  Cheaper models — judges cap at Opus. Small, low-stakes refactors.
   ● Balanced (Recommended) Opus by default; reaches the top model only where the work gets hard.
   ○ Max                    Top model + deepest thinking on every judgment call. Big or creative builds.

Q  Reviews (MULTI-select) — "Where should I pause so you can look before I continue?
                             Tick any, or tick nothing to run straight through (hands-off)."
   ☐ After the map (0)        Inventory of what you already have. Usually skip.
   ☐ After research (1)       Raw, unranked idea list. Usually skip.
   ☑ After the shortlist (2)  Ranked, trimmed candidates. The first real decision point.
   ☐ After the kill-test (3)  What died and what survived. (Auto-pauses anyway if something dies.)

Q  After the plan (single) — "You'll always approve the plan before any code is written —"
   ● Build it now             I implement it this session after your OK.
   ○ Stop at the plan         I hand you the trigger to build later (maybe a fresh session).
```

### Mock — fine-override (shown ONLY if the user asks to hand-tune)
```
These are the make-or-break calls. Leave any on "Auto" to let the run decide from complexity;
change only the ones you care about.

Kill judge (single) — decides whether a feature gets killed
   ● Auto (Recommended)   Let the run choose, based on how contested the call is.
   ○ Opus · high          Solid, cheaper.
   ○ Fable · high         Best model, strong thinking.
   ○ Fable · max          Best model, deepest thinking. Slowest, priciest.

Plan judge (single) — picks the winning plan   (same 4 options)
```

### Run-style rework — the important details
- Old rigid 3-way (Hands-off / Checkpoints / Plan-only) becomes: a **multi-select of review points**
  + a **separate build-now/stop binary**. This preserves all three old modes:
  nothing-ticked + build-now = Hands-off · some ticks + build-now = Checkpoints · build→stop = Plan-only.
- **Label reviews in plain English, NOT "pass N"** (comm rule). Step number in parens is fine.
- **The plan review is ALWAYS-ON** (even Hands-off shows the plan for one OK before any code) — so
  it is NOT a checkbox; only the intermediate passes are.
- **Do NOT lose Plan-only** — it's the "build later / fresh session" workflow (writes EXECUTE.md +
  `discover: build <name>`). It lives in the build-now/stop question, not the checklist.
- Steps 0/1 are low-value review points AND each extra stop splits the bundled 0→2 burst, forcing a
  save/stop/reload (reparse round-trips). Keep them available but pre-check only "After the shortlist".
- Keep the existing smart behavior: kill review auto-fires only if `counts.kills > 0` or
  `decisions_needed` non-empty — honor an explicit "After the kill-test" tick on top of that.

### Other AskUserQuestion adoption points
- Booster health: "pause & fix, or proceed without it?" → AskUserQuestion (2 options).
- Existing run dir: "resume or restart fresh?" → AskUserQuestion.
- Shortlist checkpoint drops: present the live shortlist as a **multi-select** ("tick the ones to
  cut") instead of free-text "drop candidate 3". Free-form rewordings stay text → `checkpoint-edits.md`.

### Preset naming (settled)
Quick / Balanced / **Max** (not "Big bet"). Max is the natural top of a 3-rung scale and parallels
the effort ladder. Watch the Quick↔Light confusion: two 3-way dials now exist (breadth =
Light/Standard/Deep; depth = Quick/Balanced/Max) — the option descriptions must name which axis
each controls ("Quick = cheaper models; Light = fewer of them").

---

## Open questions for the build session
- Exact effort thresholds for Layer-1 auto (what architecture-count / objection-count maps to
  medium vs high vs max). Pick sensible cutoffs, note them in the script.
- Whether to also expose `plan writers` / `skeptics` in the fine-override picker (recommendation:
  no — stop at the two judges; each extra seat is more clicking for less payoff).
- Config surface: where the resolved (seat → model, effort) table is assembled and passed into the
  script's `agent()` calls (probably a small resolver built from preset + pins + Layer-1 signals).
- Re-validate the stub harness + one real Light run after wiring models, since token spend shifts.
