# Implementation plan for TODO #83-#87

## 1. Lock the starting point

- Save the current test baseline before feature edits.
- Record the existing shared-tree changes and do not include or alter them.
- Preserve the existing unfinished trade-quality Ultragoal artifacts before starting this separate run.
- Create the new aggregate Codex goal from the TODO kickoff brief.

Proof: baseline command finishes; preserved artifacts are byte-for-byte copied; `git status` still
shows the same unrelated files; Ultragoal status points at this plan.

## 2. Analyst-group alert (#83 and #84)

- Write focused tests for title/footer, all four bias states, missing reasons, long text, size limits,
  Pacific/elapsed time, links, price, and ping.
- Add the smallest stored-post lookup needed to attach direction and reason to each exact group member.
- Keep detection and internal `swarm` names unchanged.
- Build the all-history replay and price audit artifact.
- Fix systematic mismatches, rerun the whole replay, render all-bullish and mixed examples, then post
  and read a safe Discord test card.
- Restart the signal engine if the live proof needs newly loaded code.
- Save the change locally and checkpoint the Ultragoal story.

Proof: focused/affected tests, zero reversed directions, zero unsupported reasons, unexplained replay
mismatches = 0, saved audit artifact, inspected Discord card, services active.

## 3. Grounded feature answers (#85)

- Extract the complete recoverable feature-question corpus and multi-turn pairs from the selected
  latest 100 `#chat` messages without exposing credentials or IDs.
- Create independent expected answers from current code/data before seeing candidate answers.
- Add a repeatable grader around the real mention/`!ask` path.
- Run the current model as control, then a strong-first live-catalog race. Change only the separate
  agent chain if the control does not pass.
- Tighten the steering text only for specific measured failures.
- Run the multi-turn test, exact breadth question, and two other real questions in Discord; read the replies.
- Save the change locally and checkpoint the Ultragoal story.

Proof: every concrete claim matches current code/data, all required question parts are answered,
false premises are corrected, no false change claims, model/config scope is isolated, inspected live replies.

## 4. VVIX/VIX lead and streak (#86)

- Add pure calculation tests first for up/down streaks, mixed/equal moves, weekends, stale/missing rows,
  and zero prior values.
- Read enough ordered rows in the existing market path and add the conclusion-first line.
- Keep the calculation out of scoring, gates, and alert generation.
- Build and run the all-row replay plus the separate forward-value study.
- Render and read the real `!market` card.
- Save the change locally and checkpoint the Ultragoal story.

Proof: every stored row independently matches, predictive sample is reported honestly, display-only
guard passes, inspected Discord card, services active.

## 5. Morning card and expected-move charts (#87)

- Write tests for the stable five-section card, empty sections, limits, deterministic fallback,
  daily/weekly data and image failures, retry, no duplicate post, and archive details.
- Add structured/validated section handling while preserving a plain fallback.
- Reuse the existing daily/weekly expected-move calculation and chart renderer.
- Extend the sender to attach the main card and daily/optional weekly PNGs in one recorded delivery.
- Replay all archived briefs and all saved daily SPY snapshots; fix every systematic failure.
- Generate current daily and weekly output from the real option-chain path, inspect both PNGs, post/read
  a clearly labeled `#chat` test, then inspect the next scheduled brief.
- Restart the signal engine if needed, save locally, and checkpoint the Ultragoal story.

Proof: all archived texts retain the five requested sections without silent truncation, saved daily
numbers match, live weekly path matches `!emw`, inspected PNGs and Discord cards, delivery state remains safe.

## 6. Close records and run the final gate

- Update all five detail files from their newest session notes, then mark them DONE only after their
  own proof gates pass.
- Update `TODO.md` through the required sync path and run both TODO check scripts.
- Run focused tests, affected tests, full repository tests, service/symlink/model-health checks, and
  a final real user-visible path check.
- Run the anti-slop cleaner on changed files only, then rerun verification.
- Prove every architecture invariant from the kickoff and coordinated specification.
- Obtain separate code-reviewer APPROVE and architect CLEAR evidence. Fix findings and repeat as needed.
- Mark the aggregate Codex goal complete only after the gate is clean, then write the final Ultragoal checkpoint.

Proof: TODO checks clean; tests clean against the recorded baseline; both services active; final quality
gate JSON contains cleaner PASS, verification PASS, code-reviewer APPROVE, architect CLEAR, and every
architecture invariant proved.
