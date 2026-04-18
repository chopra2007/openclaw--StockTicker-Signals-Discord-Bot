# Team Spinup Bug: --dangerously-skip-permissions on Root

## Problem
When user requests team spinup (via `/team` or OMC teams command), Claude Code automatically injects `--dangerously-skip-permissions` flag for each agent. This fails with:
```
--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons
```

User is running Claude Code as root, so this flag is incompatible.

## Attempted Fixes
### 1. Claude settings change
**File:** `.claude/settings.json`
**Change:** Removed line 14: `"skipDangerousModePermissionPrompt": true`
**Status:** FAILED - Flag still injected, same error persists

### 2. OMC plugin patch
**Files patched:**
- `/root/.claude/plugins/marketplaces/omc/src/team/model-contract.ts`
- `/root/.claude/plugins/marketplaces/omc/dist/team/model-contract.js`
- `/root/.claude/plugins/marketplaces/omc/bridge/team.js`
- `/root/.claude/plugins/marketplaces/omc/bridge/cli.cjs`
- `/root/.claude/plugins/marketplaces/omc/bridge/runtime-cli.cjs`
- matching cached copies under `/root/.claude/plugins/cache/omc/oh-my-claudecode/4.9.3/`

**Change:** Replaced the hardcoded Claude worker arg:
`['--dangerously-skip-permissions']`

with root-aware logic:
`process.getuid() === 0 ? [] : ['--dangerously-skip-permissions']`

**Status:** FIXED - direct runtime check now returns `[]` for Claude worker launch args when running as root

## Investigation Done
1. Searched workspace for `--dangerously-skip-permissions` string - not found in any project files
2. Flag is being injected by Claude Code CLI itself, not by project code
3. The `skipDangerousModePermissionPrompt` setting was theorized to control this behavior, but removing it did NOT fix the issue

## Root Cause
The flag was being injected by the OMC plugin itself, specifically its Claude team worker launch contract. It was not coming from workspace config or Claude settings.

Primary source:
- `/root/.claude/plugins/marketplaces/omc/src/team/model-contract.ts`

Compiled/runtime entry points also contained the same hardcoded launch arg:
- `/root/.claude/plugins/marketplaces/omc/dist/team/model-contract.js`
- `/root/.claude/plugins/marketplaces/omc/bridge/team.js`
- `/root/.claude/plugins/marketplaces/omc/bridge/cli.cjs`
- `/root/.claude/plugins/marketplaces/omc/bridge/runtime-cli.cjs`

## Additional Finding
There are two separate team-launch paths in this environment:

1. **OMC tmux workers**
   - Patched in OMC as described above
   - These do **not** use Claude's native `--agent-id/--team-name` flags

2. **Claude native teammate mode**
   - This is the path shown by commands like:
     `.../claude/versions/2.1.112 --agent-id ... --team-name ... --parent-session-id ...`
   - That path belongs to Claude Code itself, not OMC's tmux worker runtime
   - If the parent Claude session starts in dangerous mode, native teammate children inherit that mode and keep trying to launch with `--dangerously-skip-permissions`

In this environment, the parent session risk factors were:
- `/root/.claude/settings.json` had `"skipDangerousModePermissionPrompt": true`
- `/root/.openclaw/skip.sh` always launches Claude with `--dangerously-skip-permissions`
- `/root/.bashrc` defines a `skip()` helper that also always launches Claude with `--dangerously-skip-permissions`

## Verification
Direct runtime validation:

```bash
node --input-type=module -e "import { buildLaunchArgs } from '/root/.claude/plugins/marketplaces/omc/dist/team/model-contract.js'; const args = buildLaunchArgs('claude', { teamName: 'demo', workerName: 'worker-1', cwd: '/tmp' }); console.log(JSON.stringify(args));"
```

Output:
```json
[]
```

This confirms OMC will no longer append `--dangerously-skip-permissions` for Claude team workers when running as root.

Additional config verification:
- Removed `"skipDangerousModePermissionPrompt"` from `/root/.claude/settings.json`
- Added safe launcher `/root/.openclaw/claude-team-safe.sh` that starts Claude with:
  - `CLAUDECODE=1`
  - `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
  - no `--dangerously-skip-permissions`

## Environment
- Running as: root
- Claude Code version: 2.1.112
- OMC version: 4.9.3
- Location: `/root/.openclaw/workspace`

## Workaround Status
- Running as non-root user: Not tested by user yet
- Removing `--dangerously-skip-permissions` from CLAUDE.md: Not found (setting doesn't exist there)

## Remaining Risk
- A future OMC plugin update may overwrite this local patch.
- Other non-team OMC commands may still use `--dangerously-skip-permissions` in separate CLI paths; this fix specifically addresses team worker launch behavior.
- If Claude is launched through `skip.sh` or the `skip()` shell helper, native teammate-mode children may still inherit dangerous mode and fail under root.

## Next Steps
1. Spin up a real team through OMC and confirm workers open without the root privilege error.
2. If OMC is upgraded later, re-apply the same root-aware patch unless upstream includes a proper fix.
