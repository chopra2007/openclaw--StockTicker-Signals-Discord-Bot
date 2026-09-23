# Turn command-output savings on and off in Codex

**Status:** DONE 2026-09-23
**Created:** 2026-09-23

**CURRENT STATUS (2026-09-23):** DONE. A local Codex skill now recognizes
`enable savings` and `disable savings`. The explicit `$savings` trigger also
works. Fresh Codex sessions verified both keywords. Savings stay off in every
new conversation until enabled.

## Goal

Make the tested `bounded-run` helper easy to use during long Codex builds
without installing a permanent instruction or changing the build controller.
The helper keeps the full command output in a private file and shows a smaller
view containing status, test counts, errors, warnings, the beginning and end.

## How to use it

- Say `enable savings` to turn it on for the current conversation.
- Say `disable savings` to turn it off for the current conversation.
- Explicit form: `$savings enable`, `$savings disable`, or `$savings status`.
- A new conversation starts with savings off.

When enabled, Codex uses the helper only for commands likely to print more than
120 lines, such as verbose builds and tests. Short searches, interactive
commands, and commands whose exact output feeds another program stay direct.
Saved output is reopened with `bounded-run --show LOGFILE START END`; the
original command is not rerun just to recover omitted output.

This switch changes output handling only. It does not grant permission to start
new work, retry a command that may have run, spend money, change file access, or
perform live operations. Controller-created Codex workers use isolated prompts
and do not inherit the setting unless their own prompt explicitly invokes it.

## What was built

| Item | Path |
|---|---|
| Keyword-aware Codex skill | `/root/.codex/skills/savings/SKILL.md` |
| Skill display and automatic matching setting | `/root/.codex/skills/savings/agents/openai.yaml` |
| Output helper | `/root/.local/share/cli-token-efficiency/bin/bounded-run` |
| Helper tests | `/root/.local/share/cli-token-efficiency/bin/test_bounded_run.py` |
| Repair, comparison, and rollback record | `/root/.local/share/cli-token-efficiency/projects/-home-openclaw--openclaw-workspace/20260923-021202-codex-repair/` |

The skill deliberately avoids writing logs into the live OpenClaw production
workspace. It selects a private directory already inside a confirmed writable
build run or sandbox. If no safe log directory exists, Codex runs the command
directly.

## Proof

- The skill structure validator passed.
- A fresh Codex session given `enable savings` loaded the skill and returned
  `/root/.local/share/cli-token-efficiency/bin/bounded-run` plus the exact
  retrieval form `bounded-run --show LOGFILE START END`.
- A separate fresh session given `disable savings` loaded the skill and replied
  `Savings disabled for this conversation.`
- The helper has 13 passing focused tests. Its sandbox checks cover writable and
  denied log folders, long lines, warnings, nonzero exits, interruption, and a
  later saved-log read.
- One matched noisy diagnosis used 110,910 total tokens with the helper versus
  145,750 directly, a 23.9% reduction. Command output fell 91.0%. This is one
  preliminary pair, not a promise that every build saves 23.9%.

## What failed during development

The original helper always wrote outside the Codex writable folder, so the log
open failed before the command started. The repair added optional `--log-dir`
and a clear exit-125 failure that confirms the command was not started. An
early retrieval check also used unsupported `--lines` wording. The verified
form is `--show LOGFILE START END`.

## How to revert

### Disable without removing anything

Say `disable savings`. Existing logs remain available.

### Disable the keyword and `$savings` triggers

Move the skill out of the discovery folder, then start a new Codex conversation:

```bash
mv /root/.codex/skills/savings /root/.codex/skills/savings.disabled
```

Restore it with:

```bash
mv /root/.codex/skills/savings.disabled /root/.codex/skills/savings
```

### Undo the Codex helper repair

```bash
R=/root/.local/share/cli-token-efficiency/projects/-home-openclaw--openclaw-workspace/20260923-021202-codex-repair
$R/rollback.sh status
$R/rollback.sh --dry-run
$R/rollback.sh --apply
```

The script refuses to overwrite either helper file if it changed after this
build. This restores the helper to Claude's earlier version; it does not delete
Claude's helper.

### Remove the helper completely

First apply the Codex rollback above. Then use Claude's guarded helper rollback:

```bash
C=/root/.local/share/cli-token-efficiency/projects/-home-openclaw--openclaw-workspace/20260922
$C/rollback.sh status
$C/rollback.sh --dry-run --group helpers
$C/rollback.sh --group helpers
```

### Undo this public TODO record

Find and revert the dedicated commit without touching later work:

```bash
git log --all --grep='record Codex savings mode' -1 --format='%H'
git revert <the-hash-printed-above>
git push origin master
```

## Open questions

None. Permanent global instructions remain disabled. A future change would be
needed if controller-created workers should inherit savings automatically.
