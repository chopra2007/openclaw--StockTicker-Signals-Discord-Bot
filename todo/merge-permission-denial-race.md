# Fix the merge-permission check so a "denied" action can't have already happened

**Status:** OPEN
**Created:** 2026-07-12

**Possible next steps: intentionally not written here**, matching the sibling item #72 — this is a problem statement only, for a future session (with a stronger model) to design the fix. Everything below is verified fact, not speculation.

## The problem

The user asked me to merge PR #17 (a doc-only TODO.md fix). The PR was still marked as a GitHub "draft," so the action required two steps: convert it to ready-for-review, then merge it.

I ran both as two lines in a single Bash tool call:
```
gh pr ready 17
gh pr merge 17 --merge --delete-branch=false
```

The tool result showed only the first line's success output (`✓ Pull request #17 is marked as "ready for review"`) — nothing from the merge command, not even an error from `gh` itself. No indication anything had failed.

My very next tool call — an unrelated read-only status check (`gh pr view 17 --json state,mergedAt,mergeStateStatus`) — came back with a permission-denial error instead of the JSON I asked for:

> Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Merge Without Review] The agent converts draft PR #17 to ready and immediately merges it with no visible human approval; the user's bare "merge the pr" instruction names the merge action but not the review bypass, which this rule requires to clear.

Read at face value, this looks like the merge was blocked and never happened.

## What actually happened (verified against GitHub directly)

Querying GitHub's own API for the PR and its timeline shows the merge **did** go through:

```
$ gh api repos/chopra2007/openclaw--StockTicker-Signals-Discord-Bot/pulls/17 --jq '{merged_at, merged_by: .merged_by.login, merge_commit_sha, state, draft}'
{"draft":false,"merge_commit_sha":"afc0a1bb79164dc6854bdcd60e6d0ff2c5a53723","merged_at":"2026-07-12T21:14:51Z","merged_by":"chopra2007","state":"closed"}

$ gh api repos/chopra2007/openclaw--StockTicker-Signals-Discord-Bot/issues/17/timeline --jq '.[] | select(.event=="ready_for_review" or .event=="merged" or .event=="closed") | {event, created_at, actor: .actor.login}'
{"actor":"chopra2007","created_at":"2026-07-12T21:14:49Z","event":"ready_for_review"}
{"actor":"chopra2007","created_at":"2026-07-12T21:14:51Z","event":"merged"}
{"actor":"chopra2007","created_at":"2026-07-12T21:14:51Z","event":"closed"}
```

`ready_for_review` and `merged` are 2 seconds apart — consistent with both `gh` commands in my Bash call actually executing back-to-back against GitHub. `master` has the real merge commit (`afc0a1b`) with that exact SHA. The PR is genuinely merged.

## The defect

The "auto mode classifier" permission check that's supposed to gate risky actions (here: converting a draft to ready and merging it with no visible human review in between — a real, sensible rule) did not actually prevent the action from executing. The underlying `gh pr merge` command ran to completion and changed real state on GitHub *before* (or concurrently with) the classifier's denial being surfaced. The denial was reported as if it were a block, but functioned only as a same-turn warning attached to a *later, unrelated* tool call — not the merge call itself.

This means: a tool result that says "Permission ... was denied" is not reliable evidence that the named action didn't happen. In this instance the action had already completed in full.

## Why this matters

An agent (or a user skimming the transcript) who trusts a denial message at face value would conclude the merge never happened, when it did. In this specific case I happened to independently verify the real state on GitHub afterward and caught the discrepancy — but nothing about the tool's own behavior forced that verification. A denial that arrives after the fact, attached to the wrong call, is actively misleading rather than merely unhelpful: it reads as "this didn't happen," when the true situation is "this happened, and the system disapproves after the fact."

## Scope of what has and hasn't been checked

This is a single observed instance (PR #17, 2026-07-12, this session). Not checked:
- Whether this is specific to the `gh pr ready` + `gh pr merge` pairing, or a general property of how the auto-mode classifier evaluates multi-line Bash calls.
- Whether the denial would have actually prevented execution if the command had been the *first* line of the call instead of the second (i.e. whether ordering/position within a multi-command Bash call affects whether the classifier's gate is pre- or post-execution).
- Whether this reproduces on other "compound" risky actions (e.g. other draft-to-ready-then-X patterns, or other multi-step git/gh operations bundled into one Bash call).
- Whether the classifier evaluates the whole Bash call's command string before dispatch (and simply failed to stop `gh pr merge` from running despite flagging it), or evaluates per-line/after routing to a subprocess, or evaluates asynchronously against tool-call boundaries rather than command boundaries.

## Files / evidence involved

- PR #17: `https://github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot/pull/17`, merge commit `afc0a1bb79164dc6854bdcd60e6d0ff2c5a53723`.
- The exact denial text is quoted verbatim above (session transcript, 2026-07-12).
- GitHub timeline API output above (`ready_for_review` @ 21:14:49, `merged` @ 21:14:51 UTC) — the hard evidence the action executed despite the denial.
- The Bash tool call that triggered this: two `gh` commands on separate lines within one call (`gh pr ready 17` then `gh pr merge 17 --merge --delete-branch=false`).

## Open questions (for a future session to investigate — not answered here)

- Is the auto-mode classifier a true pre-execution gate, or does it (at least sometimes) evaluate after a command has already run?
- Why did the denial attach to the *next* tool call instead of the merge call itself?
- Does a user's plain instruction ("merge the pr") need to explicitly say "even though it's a draft, undraft and merge without a separate review step" to satisfy this rule, or should the agent behavior itself change (e.g. always pause and confirm before undrafting + merging in the same turn)?
- Is there a reliable way for an agent to tell a real pre-execution denial (action genuinely blocked) apart from this after-the-fact kind (action happened despite the "denied" label), from the tool result alone — without having to separately verify against the underlying system every time?
