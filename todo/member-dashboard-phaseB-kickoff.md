# Phase B kickoff with build watchdog

**User approval (2026-10-05, given in chat):** the user explicitly approves creating and enabling the build
watchdog below: a systemd timer that, every 5 minutes, reads this Claude session's tmux screen and types into it
only to (a) choose "Stop and wait for limit to reset" on the usage-limit menu, (b) type `continue` after a usage
limit that didn't resume by itself, and (c) relaunch a crashed session with `--continue`. It must never answer any
other question or press anything else. It switches itself off when Phase B finishes.

## Steps

1. **Confirm you are in tmux** (`echo $TMUX_PANE` is non-empty). If not, stop and tell the user to start this
   session with their `teams` shortcut.
2. **Create the watchdog** exactly as specified below. Save the pane id:
   `mkdir -p /root/task_system/state && echo "$TMUX_PANE" > /root/task_system/state/dashboard_build.pane && touch /root/task_system/state/dashboard_build.active`.
   Then `systemctl daemon-reload && systemctl enable --now dashboard-build-watchdog.timer`.
3. **Test it once, harmlessly:** run the script by hand while you're working. The log
   `/root/task_system/logs/dashboard_build_watchdog.log` must show no action, because the screen shows "esc to interrupt".
   Check `systemctl list-timers dashboard-build-watchdog.timer` shows the next run.
4. **Do Phase B** of `todo/member-dashboard-finish.md`.
5. **At the end** (Phase B done, or blocked and needing the user), write one plain-English line of status to
   `/home/openclaw/.openclaw/workspace/.omc/member-dashboard-phaseB.done`. The watchdog then reports it and switches itself off.
   Confirm the timer is inactive.

If the usage limit hits while you're working, nothing is needed from you; the watchdog handles it.

## Watchdog files (create verbatim, mode 755 for scripts)

`/root/task_system/scripts/dashboard_build_claude.sh` launches Claude the way the user's `teams` shortcut does:
```bash
#!/usr/bin/env bash
set -a; source /root/.openclaw/.env; set +a
export PATH="/root/.local/bin:$PATH" CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 IS_SANDBOX=1
cd /home/openclaw/.openclaw/workspace
exec /root/.local/bin/claude --settings '{"teammateMode":"tmux"}' "$@"
```

`/root/task_system/scripts/dashboard_build_watchdog.sh`:
```bash
#!/usr/bin/env bash
# Keeps the dashboard Phase B Claude session moving across usage-limit resets. User-approved 2026-10-05.
set -uo pipefail
W=/home/openclaw/.openclaw/workspace; ST=/root/task_system/state
LOG=/root/task_system/logs/dashboard_build_watchdog.log; NOTE=/root/task_system/notifications.log
DONE=$W/.omc/member-dashboard-phaseB.done; now=$(date +%s)
log()  { echo "$(TZ=America/Los_Angeles date '+%F %T %Z') $*" >> "$LOG"; }
note() { echo "[$(TZ=America/Los_Angeles date -Iseconds)] DASHBOARD BUILD — $*" >> "$NOTE"; log "NOTIFY: $*"; }
get()  { cat "$ST/dashboard_build_$1.state" 2>/dev/null || echo 0; }
put()  { echo "$2" > "$ST/dashboard_build_$1.state"; }
off()  { rm -f "$ST/dashboard_build.active"; systemctl disable --now dashboard-build-watchdog.timer >/dev/null 2>&1; }

[ -f "$ST/dashboard_build.active" ] || { off; exit 0; }
[ -f "$DONE" ] && { note "Phase B finished: $(head -c 300 "$DONE")"; off; exit 0; }
P=$(cat "$ST/dashboard_build.pane" 2>/dev/null)

if [ -z "$P" ] || ! tmux display-message -p -t "$P" '#{pane_id}' >/dev/null 2>&1; then
  n=$(get relaunches)
  [ "$n" -ge 3 ] && { note "session gone, 3 relaunches used; needs a person"; off; exit 0; }
  put relaunches $((n+1)); log "session missing; relaunch $((n+1)) with --continue"
  tmux new-session -d -s dash-build -c "$W" "/root/task_system/scripts/dashboard_build_claude.sh --continue 'Continue Phase B of todo/member-dashboard-finish.md (watchdog per todo/member-dashboard-phaseB-kickoff.md is already running; update its pane file with your TMUX_PANE). Do not redo finished steps.'"
  tmux display-message -p -t dash-build:0.0 '#{pane_id}' > "$ST/dashboard_build.pane"
  exit 0
fi

tail15=$(tmux capture-pane -p -t "$P" -S -40 | tail -15); hash=$(printf '%s' "$tail15" | md5sum | cut -c1-12)

if printf '%s' "$tail15" | grep -q "Stop and wait for limit to reset"; then
  num=$(printf '%s\n' "$tail15" | grep "Stop and wait for limit to reset" | grep -oE '[0-9]+\.' | head -1 | tr -d .)
  if [ -n "$num" ]; then tmux send-keys -t "$P" "$num"; log "limit menu: chose option $num (stop and wait)"
  else note "limit menu shown but its option number wasn't found; needs a person"; fi
  put limit_since $now; exit 0
fi
if printf '%s' "$tail15" | grep -qi "continuing automatically\|continues automatically"; then
  [ "$(get limit_since)" = 0 ] && { put limit_since $now; log "usage limit; Claude will continue by itself"; }
  [ $((now-$(get limit_since))) -gt 21600 ] && [ "$(get warned)" = 0 ] && { note "waiting on usage limit over 6 h"; put warned 1; }
  exit 0
fi
if printf '%s' "$tail15" | grep -qiE "hit your (usage |5-hour |weekly )?limit|usage limit reached|limit will reset|after it resets"; then
  [ "$(get limit_since)" = 0 ] && put limit_since $now
  if [ $((now-$(get nudged_at))) -ge 1800 ]; then tmux send-keys -t "$P" "continue" Enter; put nudged_at $now; log "limit without auto-resume; typed continue"; fi
  exit 0
fi

[ "$(get limit_since)" != 0 ] && { log "running again after usage limit"; put limit_since 0; put warned 0; }
if printf '%s' "$tail15" | grep -q "esc to interrupt"; then put idle_since 0; put idle_hash "$hash"; exit 0; fi
[ "$hash" != "$(get idle_hash)" ] && { put idle_hash "$hash"; put idle_since $now; exit 0; }
[ "$(get idle_since)" = 0 ] && { put idle_since $now; exit 0; }
if [ $((now-$(get idle_since))) -ge 1800 ] && [ "$(get idle_noted)" != "$hash" ]; then
  note "session idle 30+ min without finishing (may be waiting for an answer)"; put idle_noted "$hash"
fi
```

`/etc/systemd/system/dashboard-build-watchdog.service`:
```ini
[Unit]
Description=Keep the member-dashboard Claude build moving across usage-limit resets
[Service]
Type=oneshot
ExecStart=/root/task_system/scripts/dashboard_build_watchdog.sh
```

`/etc/systemd/system/dashboard-build-watchdog.timer`:
```ini
[Unit]
Description=Run the dashboard build watchdog every 5 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```
