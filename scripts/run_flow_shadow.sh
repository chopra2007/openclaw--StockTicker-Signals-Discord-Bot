#!/bin/bash
# TODO #57: run the Schwab-vs-yfinance flow-loop shadow compare, and if the two
# feeds agree, finish the job on its own — flip flow_loop_enabled ON and restart
# the engine so the autonomous unusual-options alert loop uses the real-time feed.
#
# The compare + config edit run as the openclaw user (so a Schwab token refresh
# or a consensus.yaml write never flips ownership). The engine restart + the
# confirmation post run as root (this script's caller). One-shot: always exits 0
# so run_task.sh never retries the flip.
set +e

# Load creds + CLAUDECODE_WEBHOOK for the confirmation post (root side).
set -a; . /home/openclaw/.openclaw/.env.service 2>/dev/null; set +a

OUT=$(sudo -n -u openclaw bash -c 'set -a; . /home/openclaw/.openclaw/.env.service; set +a; cd /home/openclaw/.openclaw/workspace; python3 scripts/schwab_flow_shadow_compare.py --apply --notify')
echo "$OUT"

ACTION=$(printf '%s\n' "$OUT" | grep -oE 'SHADOW_ACTION=[A-Z_]+' | tail -1 | cut -d= -f2)

post() {  # post $1 to #chat (best effort) + notifications.log
    echo "[schwab-flow-shadow] $1" >> /root/task_system/notifications.log
    [ -n "${CLAUDECODE_WEBHOOK:-}" ] && \
        curl -sf -m 10 -H 'Content-Type: application/json' \
             -d "{\"content\": \"$1\"}" "$CLAUDECODE_WEBHOOK" >/dev/null 2>&1
    return 0
}

if [ "$ACTION" = "FLIPPED" ]; then
    systemctl restart consensus-engine.service
    sleep 8
    if systemctl is-active --quiet consensus-engine.service; then
        post "✅ Schwab flow-loop is now LIVE — autonomous unusual-options alerts run on the real-time feed (engine restarted, active). NOTE for next session: commit consensus.yaml (flow_loop_enabled flipped to true)."
    else
        post "⚠️ Flipped flow_loop_enabled but consensus-engine is NOT active after restart — needs attention."
    fi
fi

exit 0
