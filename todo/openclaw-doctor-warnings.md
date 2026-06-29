# Fix remaining openclaw doctor warnings

**Status:** RESOLVED 2026-06-29 — last actionable warning (orphan transcripts) cleared; only intentional/risky-to-touch warnings remain
**Created:** 2026-06-12

### Session note — 2026-06-29 (run `todo-55-47-research`)
The remaining **orphan transcript** warning is CLEARED. The count had already dropped 142→**7**
(not the 132 the old note implied). Verified the 3 real channel chat transcripts (1468/1496/1510)
have **completed summaries** in `chat_memory_rollups` (content preserved); the other 4 are agent
`.trajectory` logs. Archived all 7 to `/home/openclaw/.openclaw/transcript-archive-2026-06-29/`
(restricted) then deleted; `openclaw doctor` no longer lists orphan transcripts. The leftover
warnings — task-registry sidecar, OAuth dir, **state-dir permissions** (changing `~/.openclaw`
perms risks the documented ownership traps), and "1/5 recent sessions missing transcripts" — are
intentional or risky-to-touch and left as-is. #38 effectively done.

## What was done this session (2026-06-12)

**`openclaw gateway restart` fixed** — added a shell function to `/root/.bashrc` that intercepts `openclaw gateway restart/start/stop` and routes to `systemctl restart/start/stop openclaw-gateway.service`. Uses a poll loop (1s intervals, up to 15s) waiting for port 18789 to be listening before running `openclaw gateway status`. Tested: confirmed 8s to ready, "Connectivity probe: ok".

**`openclaw update` + `openclaw doctor --fix` wrapper** — same bash function also detects when `openclaw update` or `doctor --fix` leaves port 18789 unreachable and auto-restarts `openclaw-gateway.service`. This fixes "Gateway: restart skipped (no installed service found)" after updates.

**Memory search provider** — changed from `local` (not configured) to `github-copilot` via `openclaw config set agents.defaults.memorySearch.provider github-copilot`. Gateway restarted to apply.

**Plugin version drift** — ran `openclaw update`; confirmed both brave and discord at 2026.6.6 matching openclaw version. Drift warning gone.

**Session cleanup** — ran `openclaw sessions cleanup --enforce --fix-missing`: pruned 52 unreferenced session artifacts (entries 54→31). sessions.json was already empty so all 142 transcript `.jsonl` files were orphaned; renamed to `.deleted.<timestamp>.jsonl`.

---

## What's still open

### 1. Brave plugin ownership (one command needed — user must run)

`/home/openclaw/.openclaw/extensions/brave` is owned by `openclaw:openclaw` (uid=998). Openclaw blocks it as a suspicious local extension (expects root ownership). The npm-installed brave plugin **is working fine** from its separate path — this is just a second copy causing a warning.

Auto-mode blocked both approaches. User must run one of:

```bash
# Option A — delete the blocked duplicate (cleanest)
rm -rf /home/openclaw/.openclaw/extensions/brave

# Option B — fix ownership so openclaw accepts it  
chown -R root:root /home/openclaw/.openclaw/extensions/brave && chmod 755 /home/openclaw/.openclaw/extensions/brave
```

After either option: run `openclaw gateway restart` to reload plugins, then `openclaw doctor` to confirm warning is gone.

### 2. Orphan transcript files (cosmetic, low priority)

142 `.deleted.<timestamp>.jsonl` files still show as "orphan transcripts" in doctor output. They are already archived (doctor's own suggested fix). To fully clear this warning, delete them:

```bash
rm /home/openclaw/.openclaw/agents/main/sessions/*.deleted.*.jsonl
```

### 3. Permanent non-fixable warnings

These warnings cannot be eliminated without changing the server architecture:

- **Multiple state directories** — `/root/.openclaw` is a symlink to `/home/openclaw/.openclaw`; doctor sees two paths for one directory. Intentional setup.
- **Task registry sidecar** — doctor left it because 1 existing row was in shared state. Not a real problem.

## Files involved

- `/root/.bashrc` — gateway wrapper function (lines ~131–155)
- `/home/openclaw/.openclaw/openclaw.json` — memory search provider config
- `/home/openclaw/.openclaw/agents/main/sessions/sessions.json` — session store (now empty `{}`)

### Session notes — 2026-06-13 (discover run todo-sweep)
- **DONE: deleted the blocked duplicate Brave plugin** — `rm -rf /home/openclaw/.openclaw/extensions/brave`. Verified safe first: the working Brave search loads from a separate npm path (`.../npm/projects/openclaw-brave-plugin-*/node_modules/@openclaw/brave-plugin`, still present after the delete) and openclaw.json references brave by name, never the deleted path. Both services still active afterward. The ownership warning clears on the next gateway reload.
- **DEFERRED: the 142 orphan `.deleted.*.jsonl` transcripts.** #39 (chat-memory redesign) needs this archive as its recall-backtest/summarizer corpus. Copy-to-archive first, delete after #39's summarizer is built. (Command in .claude/discover/todo-sweep-2026-06-13/research/bounded.md.)
- **Unfixable/intentional, leave:** symlink dual-path (/root/.openclaw→/home/openclaw/.openclaw), task-registry sidecar, missing OAuth dir.
