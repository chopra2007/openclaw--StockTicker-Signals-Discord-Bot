---
description: Start a durable outcome-loop goal — asks a few questions, writes the mission + pass/fail script for you
---

Set up a new outcome-loop mission by interviewing the user. The user is not a
coder: never ask them for JSON, a file path, a command, a slug, or a script.
Ask in plain English, write every technical artifact yourself.

Background you must read before asking anything:
- `plugins/outcome-loop/skills/outcome-loop/SKILL.md`
- `plugins/outcome-loop/skills/outcome-loop/references/mission-contract.md`
- `plugins/outcome-loop/templates/mission.template.json`
- `.omx/plans/todo-111-outcome-loop-mission.json` (a real, validated example)

User input: `$ARGUMENTS` — may be empty, or may already name a TODO item
(`#111`, `111`, `todo 111`). If it names one, skip Round 1's question and go
straight to reading that item.

## Rules for the whole interview

- Use the **AskUserQuestion** tool with click-cards, batched 2–4 per round.
- **Always ask every question**, even when the TODO item already answers it.
  When it does, make that the FIRST option, label it `(from #N)`, and append
  `(Recommended)` to the label. One click accepts it. Nothing is silently
  decided.
- Every option label and description is plain English. No jargon. If a
  technical word is unavoidable, explain it in the same sentence.
- Never invent a number the user did not give and the TODO item does not
  contain. If a number is missing, ask for it in that round.

## Round 1 — the reference

Ask one free-text question: **"Is there a TODO item to base this on? Give me
its number (like `#111`), or say none."**

If they name one:
1. `grep -n -A8 '^## <N>\.' TODO.md` to get the title, status and detail
   filename.
2. Read `todo/<filename>` in full.
3. Also read any file that item points at under `.omx/plans/`.
4. Tell the user in **3 lines maximum**: what the item is, its status, and
   which of the questions below it already answers.

If they say none, say so in one line and carry on with empty pre-fills.

## Round 2 — the goal and the name

Two cards:

- **"What does success look like?"** One sentence, the outcome — not the
  work. Pre-fill from the TODO item's Goal section. Offer "Other" for their
  own wording.
- **"What should this job be called?"** A short name. You turn it into the
  internal ID yourself: lower-case, hyphens only, 3–64 characters, matching
  `^[a-z0-9][a-z0-9-]{2,63}$`. If the item is `#111`, propose
  `todo-111-<two-or-three-words>`.

## Round 3 — the finish line, in numbers

This is the most important round. The loop freezes a small script that decides
pass or fail, and can never be talked out of it.

Ask, as cards with pre-filled options drawn from the TODO item:

- **"What has to be true to call it done?"** Push for something countable —
  "beats buy-and-hold by at least 40 cents per $100 after costs, over 200 or
  more trades" beats "it's profitable". If their answer is not countable, ask
  one follow-up to make it countable.
- **"What proof do you want to see before it counts?"** Multi-select. Typical
  choices: a fresh untouched test period, someone reproducing the result
  independently, the real posted output at the real time, the full project
  test suite passing.

## Round 4 — permissions

Two cards, both multi-select, both pre-filled with safe defaults:

- **"What is it allowed to do?"** Defaults on: read this project, read local
  data files, search the web, download free data, change code in this
  project, run tests. Defaults off: spend money, use a brokerage account,
  post to Discord.
- **"What must it never do?"** Defaults on: place a real trade, push to
  GitHub, post publicly, print or store a password or key, turn on a live
  alert, weaken the finish line once frozen.

Translate their picks into `allowedActions` / `forbiddenActions` slugs
yourself. `modify_repository` and `run_goal_check` are always in
`allowedActions` — the controller refuses a mission without them. Never put
the same slug in both lists.

## Round 5 — limits

Two cards:

- **"How much money may it spend, at most?"** Default `$0.00`. If they allow
  spending, also state in the goal text that any purchase needs their
  approval first.
- **"How many genuinely different approaches before it gives up?"** Default 5.
  Explain: a new threshold on the same idea does not count as different — the
  loop enforces that.

## Round 6 — when it must stop and ask you

One multi-select card, pre-filled with all five: money runs out, it has tried
the agreed number of approaches, it hits a wall it cannot get past (a login
screen, a blocked source), it reaches a decision only you can make (a
payment, turning on a live alert), or the goal itself turns out to be wrong.

These map to `budget_exhausted`, `attempt_limit_reached`,
`permission_or_access_blocked`, `owner_only_decision`, `mission_invalidated`.
Nothing else is valid.

## Then build the two files

Do this without asking — it is what the command is for.

### 1. The pass/fail script

Write `scripts/research/<mission_id_with_underscores>_gate.py`. It takes a
mode as its first argument and one or more evidence files after it:

- Modes `data`, `access`, `cost`, `permission` — the four feasibility checks,
  run before any real building starts. Each takes exactly one evidence file.
  On success each must print JSON to stdout with `status` set to `PASS`, an
  `evidenceSha256` field holding the SHA-256 of the evidence file's bytes, and
  a non-empty `facts` list. Exit non-zero on failure.
- Mode `final` — the finish line from Round 3. It reads the evidence files and
  exits 0 only if every number the user named is met. Exit non-zero otherwise.

Hard-code the user's Round-3 numbers as constants at the top of the file with
a plain-English comment above each one.

### 2. The mission file

Write `.omx/plans/<mission-id>-mission.json`, copying the shape of
`plugins/outcome-loop/templates/mission.template.json`. Rules the controller
enforces — get these right or `validate-mission` refuses it:

- Exactly these top-level keys, no extras: `formatVersion` (1), `missionId`,
  `missionVersion` (1), `domain`, `title`, `goal`, `passCondition`,
  `feasibilityChecks`, `permissions`, `budget`, `allowedEvidence`,
  `stopConditions`.
- Each feasibility command lists exactly one `{evidence}` placeholder.
- The final command's file arguments are all `{evidence:<id>}` placeholders —
  a real path there is refused. Mode words like `final` are fine as long as no
  file of that name exists in the project.
- `checkerFiles` names your gate script, and the command must contain it.
- `timeoutSeconds` is 1–300. `expectedExitCode` is 0.
- `allowedEvidence.roots` must include
  `.omx/outcome-loop/<mission-id>` plus every folder the evidence will come
  from. `requiredKinds` must include the four `feasibility_*` kinds plus
  `plan`, `implementation`, `test`, and one kind per Round-3 proof.

### 3. Prove the script works

Run all three, and show the user the real output:

1. `python3 plugins/outcome-loop/scripts/outcome_loop.py validate-mission
   --root . --mission .omx/plans/<mission-id>-mission.json` — must print
   `"valid": true`.
2. Feed the `final` mode a **fake pass** file built in the scratchpad. It must
   exit 0.
3. Feed it a **fake fail** file — one number just under the line. It must
   exit non-zero.

If either fake test comes out wrong, fix the script and rerun. Do not move on
with a broken finish line.

## Then summarise and ask

Show the user, in plain English and under 15 lines:

- What it will chase (the goal, one sentence).
- The exact finish line, with the numbers.
- What it may and may not do.
- The money cap and how many approaches.
- What will make it stop and come back to you.
- One line confirming the fake-pass and fake-fail tests both behaved.

Then ask one final card: **"Start it now, or save it for later?"**

- **Later** → print the two file paths and the one-line kickoff:
  `Run the outcome-loop mission at .omx/plans/<mission-id>-mission.json`.
  Stop there.
- **Now** → follow `plugins/outcome-loop/skills/outcome-loop/SKILL.md` from
  `init` onwards. The builder must be a different agent and thread from the
  controller, and the reviewer must be a new read-only agent that never edits
  what it reviews. `COMPLETE` only counts when `final-gate` writes it.

## Add it to the TODO list

Whichever they pick, add the mission to the TODO list following
`todo/CONVENTION.md` — unless it belongs to an existing item, in which case
append a session-notes block to that item's detail file instead.
