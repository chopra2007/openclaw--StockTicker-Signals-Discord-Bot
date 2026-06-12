# Eval Agent 1 — Issue 2 (Gateway crash on reboot) + Issue 4 (web-search-plus-plugin-v2)
Generated: 2026-06-11 — READ-ONLY investigation, no files modified.

---

## 1. Gateway Service Current State

**Status:** FAILED (exit-code). Last failure: 2026-06-10 16:11:42 PDT.
Restart counter hit 9 (StartLimitBurst=10), then tripped "Start request repeated too quickly." Service is now dead and will NOT auto-restart without `systemctl reset-failed`.

**Error message (repeated every attempt):**
```
Gateway failed to start: Startup failed: required secrets are unavailable.
Error: unable to open database file | unable to open database file.
```

---

## 2. Root Cause — The Real Issue Is DB Ownership, Not Just Plugin Drift

### 2a. The State DB is owned by root; the service runs as openclaw

```
/home/openclaw/.openclaw/state/            drwx------  root root
/home/openclaw/.openclaw/state/openclaw.sqlite  -rw-------  root root
```

The service unit has `User=openclaw` (uid=998). The `state/` directory is `drwx------` owned by root, and the DB file inside is `rw-------` owned by root. The openclaw user cannot enter the directory, let alone open or write the SQLite file. This is the direct mechanical cause of "unable to open database file."

This ownership flip almost certainly happened during a root-session plugin install on 2026-06-10 (the extensions/brave and extensions/web-search-plus-plugin-v2 directories are also root-owned). The gateway writes to this DB during startup to store secrets/session state. When it can't open the DB, it surfaces the error as "required secrets are unavailable."

**This is the PRIMARY root cause.** Plugin version drift is a secondary problem that will cause the gateway to warn/fail AFTER the DB issue is resolved, but fixing only plugins without fixing ownership will not start the gateway.

### 2b. Plugin Version Drift (Secondary)

`openclaw gateway status --deep` output:
```
Plugin version drift: 1 active official plugin not on gateway 2026.6.5
- discord: 2026.5.18 (npm) → expected 2026.6.5
```

There are TWO discord installs on disk:
- `/home/openclaw/.openclaw/npm/node_modules/@openclaw/discord` — version **2026.5.18** (this is what the gateway loads; it is the dependency in the base npm `package.json` which pins `"@openclaw/discord": "2026.5.18"`)
- `/root/.openclaw/npm/projects/openclaw-discord-c0892df945/node_modules/@openclaw/discord` — version **2026.6.5** (a project-specific install; NOT loaded by the gateway)

installs.json records discord as `2026.5.28`, but neither the old base install (2026.5.18) nor the project install (2026.6.5) matches that. The gateway binary version is 2026.6.5 and it requires the discord plugin to match.

**Conclusion:** The gateway will refuse to start cleanly with discord at 2026.5.18. This must be updated. But fixing only this without fixing DB ownership also won't start the gateway.

### 2c. web-search-plus-plugin-v2 (Issue 4 — partially removed)

`openclaw gateway status --deep` reports:
```
Config warnings:
- plugins.entries.web-search-plus-plugin-v2: plugin not found: web-search-plus-plugin-v2 (stale config entry ignored; remove it from plugins config)
- plugins.allow: plugin not found: web-search-plus-plugin-v2 (stale config entry ignored; remove it from plugins config)
```

**Meaning:** The files on disk at `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/` are NOT being loaded (the gateway reports "not found"). The gateway treats this as a stale config entry it ignores. However:
- The entry IS still present in `openclaw.json` under both `plugins.entries` and `plugins.allow`
- The entry IS still present in `installs.json` (version 3.0.0 recorded, disk has 3.1.0)
- The disk directory exists at `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/` owned by root

So the prior memory note saying "removed 2026-06-11" is **WRONG** — it has NOT been fully removed. What may have happened: the gateway stopped loading it (possibly due to the root ownership of the disk files, or the gateway detecting the config inconsistency and ignoring it). But it remains in config and installs.json.

The gateway currently IGNORES it (doesn't crash on it) — but the stale config entry generates warnings and may interfere with the plugin reconciliation pass that happens during startup, which could contribute to the "plugin DB inconsistency" that prevents the state DB write. This should be cleaned up regardless.

### 2d. Brave Plugin (Tertiary)

`openclaw gateway status --deep`:
```
- plugins.entries.brave: plugin not installed: brave — install the official external plugin with: openclaw plugins install @openclaw/brave-plugin
```

installs.json records brave at version **2026.5.27**. On disk at `/home/openclaw/.openclaw/extensions/brave/` the actual package.json says version **2026.6.5**. The directory is owned by **root**, so the gateway (running as openclaw) cannot read it — hence "not installed."

Two issues with brave:
1. Ownership: `drwx------ root root` — openclaw user can't access it
2. installs.json records 2026.5.27, disk has 2026.6.5 — version drift

The gateway warns about brave but does NOT list it as a version-drift blocker (unlike discord). The brave plugin is enabled in `openclaw.json` with a BRAVE_SEARCH_API_KEY reference. If web search via brave is needed, it must be fixed; otherwise it should be removed from config.

---

## 3. Alert De-dup Flags — Reboot-Wipe Confirmed

Current state of `/run/openclaw/`:
```
gateway-watchdog-alerted   (empty file — latch present, prevents repeated gateway-watchdog alerts)
gateway-watchdog-fails     contents: 715 (consecutive fail count since last good probe)
gateway-watchdog-incidents contents: 3 (hit MAX_RESTART_INCIDENTS=3; watchdog stopped restarting)
notifier-state/            (subdirectory for openclaw-notify rate-limit buckets)
```

The watchdog script (`/root/task_system/scripts/gateway-watchdog.sh`) stores all four flags in `/run/openclaw/`. The `openclaw-notify` script stores its rate-limit token-bucket files in `/run/openclaw/notifier-state/`. Both locations are on tmpfs (`/run` is `tmpfs` mounted by systemd at boot), so **every reboot wipes all flags**.

On each reboot:
- `gateway-watchdog-alerted` is gone → watchdog will re-alert after 3 consecutive fails
- `notifier-state/<unit>` is gone → `openclaw-notify` rate limit resets to 0 → will fire immediately on first OnFailure trigger

This confirms the "two alerts per reboot" behavior: both the watchdog and the OnFailure→alert@.service path fire because both token-bucket files are gone after reboot.

---

## 4. Issue 4 Current State — Exact Remaining Artifacts

web-search-plus-plugin-v2 is NOT fully removed. What remains:

| Location | Still present? | What's there |
|---|---|---|
| `openclaw.json` → `plugins.entries.web-search-plus-plugin-v2` | YES | `{"enabled": true}` |
| `openclaw.json` → `plugins.allow[]` | YES | `"web-search-plus-plugin-v2"` string |
| `installs.json` → `installRecords.web-search-plus-plugin-v2` | YES | Full record, version 3.0.0 |
| `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/` | YES | Full directory, owned root, disk version 3.1.0 |

The gateway currently ignores it (reports "stale config entry"), so it is not the active crash cause right now. But it generates startup warnings and should be cleaned.

---

## 5. Fix Evaluation

### 5a. Is the suggested sequence sufficient?

**Suggested:** `openclaw plugins update discord` → resolve Issue 4 → `systemctl restart`

**INSUFFICIENT.** Missing the most critical step: fixing ownership of `/home/openclaw/.openclaw/state/` and `state/openclaw.sqlite`. Without that, the gateway cannot open its state DB regardless of plugin state.

Also missing: `systemctl reset-failed openclaw-gateway.service` before restart (the service has tripped StartLimitBurst and is stuck; a plain `systemctl restart` may not work until the failed state is cleared).

### 5b. Better/Safer Approach

**Step 1 — Fix state DB ownership (ROOT CAUSE):**
```bash
sudo chown openclaw:openclaw /home/openclaw/.openclaw/state
sudo chown openclaw:openclaw /home/openclaw/.openclaw/state/openclaw.sqlite
sudo chmod 700 /home/openclaw/.openclaw/state
sudo chmod 600 /home/openclaw/.openclaw/state/openclaw.sqlite
```

**Step 2 — Fix extensions directory ownership (brave + web-search):**
```bash
sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/extensions/brave
sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2
```

**Step 3 — Remove web-search-plus-plugin-v2 via CLI (preferred over hand-editing):**
```bash
sudo -u openclaw openclaw plugins uninstall web-search-plus-plugin-v2
```
This should handle both installs.json and the extensions directory. If the CLI is unavailable, manually:
- Delete `plugins.entries.web-search-plus-plugin-v2` from `openclaw.json`
- Delete `"web-search-plus-plugin-v2"` from `plugins.allow[]` in `openclaw.json`
- Delete `installRecords.web-search-plus-plugin-v2` from `installs.json`
- `rm -rf /home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2`
- **AFTER ANY MANUAL EDIT:** `sudo chown openclaw:openclaw /home/openclaw/.openclaw/openclaw.json && sudo chmod 600 /home/openclaw/.openclaw/openclaw.json` (ownership trap)

**Step 4 — Update discord plugin:**
```bash
sudo -u openclaw openclaw plugins update discord
```
This must upgrade the base npm install from 2026.5.18 to 2026.6.5. Verify with `cat /home/openclaw/.openclaw/npm/node_modules/@openclaw/discord/package.json | grep version` after.

**Step 5 — Handle brave:**
See section 5c below for the brave verdict.

**Step 6 — Reset failed state and restart:**
```bash
sudo systemctl reset-failed openclaw-gateway.service
sudo systemctl start openclaw-gateway.service
```

**Step 7 — Verify:**
```bash
systemctl status openclaw-gateway.service --no-pager
curl -fsS http://127.0.0.1:18789/ && echo "ALIVE"
```

### 5c. Brave Verdict: UPDATE (not install, not remove)

Brave is already on disk at version 2026.6.5 (correct version), but:
- The directory is owned by root (openclaw can't read it)
- installs.json records it as 2026.5.27 (stale)

The BRAVE_SEARCH_API_KEY is referenced in `openclaw.json` → it has an API key. The gateway won't complain about version drift for brave (it warns "not installed" which is an access issue, not a version mismatch). After fixing the extensions directory ownership in Step 2, the brave plugin should be accessible. However, installs.json will still show 2026.5.27. Run:
```bash
sudo -u openclaw openclaw plugins update brave
```
...to sync installs.json to the on-disk version and confirm compatibility. If the update CLI re-downloads 2026.6.5 (same version), that's fine — it also re-writes installs.json correctly.

**Do NOT remove brave** — it has an API key configured and is used for web search fallback per the config.

### 5d. De-dup Alert Fix

The underlying crash must be fixed first (steps 1–6 above). Once the gateway starts cleanly on reboot, neither alert system will trigger.

If the gateway is still unstable and the user wants to stop duplicate reboot alerts:
- Move `gateway-watchdog-alerted` to a persistent path like `/home/openclaw/.openclaw/state/gateway-watchdog-alerted`. This requires editing `/root/task_system/scripts/gateway-watchdog.sh` (the `ALERTED=` variable).
- Move `openclaw-notify`'s `BUCKET_DIR` to `/home/openclaw/.openclaw/state/notifier-state`. This requires editing `/usr/local/bin/openclaw-notify`.
Both are low-risk edits but the correct fix is making the gateway start cleanly.

---

## 6. Adversarial Risks

1. **State DB ownership flip recurs.** The selfheal drop-in already chowns `openclaw.json` and `sources.json` on each start, but does NOT chown the `state/` directory. Any future root-session plugin install could flip `state/` ownership again. Mitigation: add a `ExecStartPre=+/bin/chown -R openclaw:openclaw /home/openclaw/.openclaw/state` to the selfheal drop-in.

2. **Plugin update fails because the npm base dir is also root-owned.** Check: `ls -la /home/openclaw/.openclaw/npm/` — if that directory is root-owned, `sudo -u openclaw openclaw plugins update discord` will fail to write to it. May need `sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/npm` first.

3. **`systemctl reset-failed` required.** The service has hit StartLimitBurst (counter at 9 of 10). A plain `systemctl restart` after the fix may work (since restart counter resets on a manual start), but `reset-failed` is safer to do first.

4. **installs.json is auto-generated.** The file's header says "DO NOT EDIT" and it is regenerated from manifests. Editing it by hand risks a hash mismatch on next gateway start (policyHash field). Always use `openclaw plugins` CLI to modify it.

5. **openclaw.json ownership trap.** Any direct edit of `openclaw.json` as root must be followed by `chown openclaw:openclaw` + `chmod 600`. The selfheal drop-in does this at each gateway start, but if you restart the gateway immediately after an edit, there's a race window. Safe order: edit as root → chown immediately → then restart.

6. **"Secrets unavailable" could persist for a different reason.** If after fixing ownership the error changes to a different secret (e.g., OPENCLAW_GATEWAY_TOKEN), verify it is present in `.env.service`: it is (confirmed via grep — both OPENCLAW_GATEWAY_TOKEN and DISCORD_AGENT_BOT_TOKEN are present).

---

## 7. Fix Safety Verdict

**Safe to do live: YES, with preconditions.**

Preconditions:
- The gateway is already down (confirmed failed), so no live traffic is at risk.
- The consensus-engine.service (bot polling) does not depend on the gateway being up — it can continue running during the fix.
- The Discord channel plugin is currently disabled (`channels.discord.enabled: false` in openclaw.json), so the bot's Discord Gateway connection is via the separate consensus-engine, not this gateway.

Do NOT edit `openclaw.json` or `installs.json` as root without immediately fixing ownership. Use the CLI (`openclaw plugins uninstall/update`) where possible to avoid manual JSON edits.

Correct fix order:
1. chown state/ + state/openclaw.sqlite to openclaw
2. chown extensions/brave + extensions/web-search-plus-plugin-v2 to openclaw  
3. `sudo -u openclaw openclaw plugins uninstall web-search-plus-plugin-v2`
4. `sudo -u openclaw openclaw plugins update discord`
5. `sudo -u openclaw openclaw plugins update brave`
6. `sudo systemctl reset-failed openclaw-gateway.service && sudo systemctl start openclaw-gateway.service`
7. Verify with `systemctl status` + `curl http://127.0.0.1:18789/`

---

## 8. Summary Table

| Claim in TODO | Verified? | Actual Finding |
|---|---|---|
| Gateway fails with "unable to open database file" | CONFIRMED | Exact error in every journal entry |
| Discord disk version 2026.5.18 | CONFIRMED | `/home/openclaw/.openclaw/npm/node_modules/@openclaw/discord` = 2026.5.18 |
| Gateway requires 2026.6.5 | CONFIRMED | Binary version 2026.6.5, --deep confirms discord drift |
| web-search-plus causes DB conflict | PARTIALLY CONFIRMED | Gateway ignores it as "stale"; it's not loading it. It generates warnings. The real DB crash is ownership. |
| web-search-plus still present | CONFIRMED | Still in openclaw.json (entries + allow), installs.json, and extensions/ dir |
| installs.json discord = 2026.5.28 | CONFIRMED | installs.json records 2026.5.28; disk base has 2026.5.18; neither matches |
| installs.json web-search = 3.0.0, disk = 3.1.0 | CONFIRMED | Exact match to claimed values |
| brave needs to be installed | REFUTED | Brave IS on disk at 2026.6.5; it needs ownership fix + update, not install |
| De-dup flags in /run/openclaw/ wiped on boot | CONFIRMED | All 4 flag files are in /run/openclaw/ (tmpfs) |
| Two alerts fire per reboot | CONFIRMED (mechanism verified) | Both watchdog (ALERTED flag gone) and OnFailure (notifier-state gone) re-trigger |
| PRIMARY root cause = plugin drift | PARTIALLY REFUTED | Plugin drift is real but secondary. State DB owned by root (service runs as openclaw uid=998) is the direct mechanical cause of "unable to open database file" |
