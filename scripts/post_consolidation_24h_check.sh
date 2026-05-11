#!/usr/bin/env bash
# 24h post-consolidation health check. Runs ~24h after VPS consolidation
# (2026-05-11). Posts a single summary message to Discord #chat.
#
# Checks (all must pass):
#   1. consensus-engine.service + openclaw-gateway.service both active
#   2. /root/.openclaw resolves to /home/openclaw/.openclaw (symlink intact)
#   3. Engine logged "boot drift check: gateway chain matches" since last restart
#   4. No "Permission denied" or "Traceback" in last 24h of engine journal
#   5. SearXNG cron has fired at least once in the last hour (proves cron migration is working)
#   6. @-mention path responds (one small query)
#
# Posts the summary to #chat regardless of result, so the user always gets a heartbeat.
set -uo pipefail

WEBHOOK="WEBHOOK_REDACTED"
LOG="/home/openclaw/.openclaw/workspace/.omc/logs/post_consolidation_24h.log"
mkdir -p "$(dirname "$LOG")"

result=()
ok=true

check() {
    local label="$1"
    local pass="$2"
    local detail="${3:-}"
    if [[ "$pass" == "1" ]]; then
        result+=("✅ $label")
    else
        result+=("❌ $label — $detail")
        ok=false
    fi
}

# 1. Services
e_state=$(systemctl is-active consensus-engine.service 2>&1)
g_state=$(systemctl is-active openclaw-gateway.service 2>&1)
[[ "$e_state" == "active" && "$g_state" == "active" ]] && check "both services active" 1 \
    || check "services" 0 "engine=$e_state gateway=$g_state"

# 2. Symlink
real=$(realpath /root/.openclaw 2>&1)
[[ "$real" == "/home/openclaw/.openclaw" ]] && check "symlink intact" 1 \
    || check "symlink" 0 "/root/.openclaw → $real"

# 3. Boot drift
drift_ok=$(journalctl -u consensus-engine.service --since "26 hours ago" --no-pager 2>&1 | grep -c "boot drift check: gateway chain matches")
drift_bad=$(journalctl -u consensus-engine.service --since "26 hours ago" --no-pager 2>&1 | grep -c "boot drift check FAILED")
[[ "$drift_ok" -ge 1 && "$drift_bad" -eq 0 ]] && check "boot drift OK" 1 \
    || check "boot drift" 0 "ok=$drift_ok bad=$drift_bad"

# 4. No fatal errors
perm_denied=$(journalctl -u consensus-engine.service --since "24 hours ago" --no-pager 2>&1 | grep -ciE "Permission denied")
tracebacks=$(journalctl -u consensus-engine.service --since "24 hours ago" --no-pager 2>&1 | grep -c "Traceback")
[[ "$perm_denied" -eq 0 && "$tracebacks" -eq 0 ]] && check "no Permission denied / Traceback in 24h" 1 \
    || check "engine errors" 0 "permission_denied=$perm_denied tracebacks=$tracebacks"

# 5. SearXNG cron fired (every 5 min — should have many entries in last hour)
searxng_log="/home/openclaw/.openclaw/workspace/.omc/logs/searxng_health.log"
recent_searxng=$(tail -200 "$searxng_log" 2>/dev/null | awk -v cutoff="$(date -d '1 hour ago' -Is)" '$1 > cutoff' | wc -l)
[[ "$recent_searxng" -ge 6 ]] && check "searxng cron firing (cron migration to openclaw user OK)" 1 \
    || check "searxng cron" 0 "only $recent_searxng entries in last hour"

# 6. @-mention path (timeout 90s; success = non-empty stdout)
mention_out=$(sudo -u openclaw timeout 90 openclaw agent --agent main --message "say 'consolidation 24h check ok' in 5 words" --timeout 60 2>&1 | head -c 500)
if [[ -n "$mention_out" && "$mention_out" != *"FailoverError"* && "$mention_out" != *"Error"* ]]; then
    check "@-mention path responds" 1
else
    check "@-mention path" 0 "$(echo "$mention_out" | head -c 150)"
fi

# Compose summary
ts=$(date -Is)
if [[ "$ok" == "true" ]]; then
    header="🟢 **VPS consolidation 24h check — ALL GREEN**"
else
    header="🔴 **VPS consolidation 24h check — REGRESSION DETECTED**"
fi

body=$(printf '%s\n' "${result[@]}")
content=$(cat <<EOF
$header
\`$ts\`

$body
EOF
)

# Log
{
    echo "=========================================="
    echo "post_consolidation_24h_check  $ts"
    echo "=========================================="
    echo "$content"
} >> "$LOG"

# Post to #chat (Discord 2000 char limit; we're well under)
payload=$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1], 'username': 'ConsolidationCheck'}))" "$content")
curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) ConsolidationCheck/1.0" \
    -d "$payload" \
    "$WEBHOOK" >> "$LOG" 2>&1

echo "$content"
