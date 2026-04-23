#!/usr/bin/env bash
# Monitor SearXNG container health and alert to Discord on state changes.
#
# Fires on a cron every 5 minutes. Reads current RestartCount and OOMKilled
# from `docker inspect`, compares against the persisted baseline in
# .omc/state/searxng_health.json, and posts to Discord on change.
#
# Autonomy contract: zero user input, no crashes. If docker is down, jq is
# missing, or the container doesn't exist, the script logs and exits 0 so
# cron doesn't spam errors.
set -u

WORKSPACE="/root/.openclaw/workspace"
ENV_FILE="/root/.openclaw/.env"
STATE_DIR="${WORKSPACE}/.omc/state"
STATE_FILE="${STATE_DIR}/searxng_health.json"
LOG_FILE="${WORKSPACE}/.omc/logs/searxng_health.log"
CONTAINER="openclaw-searxng"

mkdir -p "${STATE_DIR}" "$(dirname "${LOG_FILE}")"

log() { echo "$(date -Is) $*" >> "${LOG_FILE}"; }

# ── Load Discord creds from the project .env (not a shell profile) ─────────
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
fi

# ── Read current container state via docker inspect (JSON) ─────────────────
if ! command -v docker >/dev/null 2>&1; then
    log "docker not on PATH — skipping"
    exit 0
fi

CUR_JSON="$(docker inspect "${CONTAINER}" --format '{"restart_count":{{.RestartCount}},"oom_killed":{{.State.OOMKilled}},"status":"{{.State.Status}}","started_at":"{{.State.StartedAt}}"}' 2>/dev/null || true)"
if [ -z "${CUR_JSON}" ]; then
    log "container ${CONTAINER} not found — skipping"
    exit 0
fi

# Fields we'll compare.
CUR_RESTART="$(echo "${CUR_JSON}" | grep -oE '"restart_count":[0-9]+' | grep -oE '[0-9]+')"
CUR_OOM="$(echo "${CUR_JSON}" | grep -oE '"oom_killed":(true|false)' | cut -d: -f2)"
CUR_STATUS="$(echo "${CUR_JSON}" | grep -oE '"status":"[^"]*"' | cut -d'"' -f4)"

# Seed baseline on first run.
if [ ! -f "${STATE_FILE}" ]; then
    echo "${CUR_JSON}" > "${STATE_FILE}"
    log "baseline seeded restart=${CUR_RESTART} oom=${CUR_OOM} status=${CUR_STATUS}"
    exit 0
fi

PREV_RESTART="$(grep -oE '"restart_count":[0-9]+' "${STATE_FILE}" | grep -oE '[0-9]+' || echo 0)"
PREV_OOM="$(grep -oE '"oom_killed":(true|false)' "${STATE_FILE}" | cut -d: -f2 || echo false)"

# ── Detect regressions ────────────────────────────────────────────────────
ALERT_MSG=""
if [ "${CUR_RESTART}" -gt "${PREV_RESTART}" ]; then
    ALERT_MSG="🔄 **SearXNG container restarted** (count ${PREV_RESTART} → ${CUR_RESTART})"
fi
if [ "${CUR_OOM}" = "true" ] && [ "${PREV_OOM}" != "true" ]; then
    ALERT_MSG="💥 **SearXNG OOM-killed** (mem_limit exceeded; container auto-restarted). RestartCount=${CUR_RESTART}"
fi
if [ "${CUR_STATUS}" != "running" ]; then
    ALERT_MSG="⚠️ **SearXNG not running** — status=${CUR_STATUS} RestartCount=${CUR_RESTART}"
fi

# ── Post alert to Discord if needed ───────────────────────────────────────
if [ -n "${ALERT_MSG}" ]; then
    log "ALERT: ${ALERT_MSG}"
    if [ -n "${DISCORD_BOT_TOKEN:-}" ] && [ -n "${DISCORD_CHANNEL_ID:-}" ]; then
        payload=$(printf '{"content": "%s"}' "${ALERT_MSG//\"/\\\"}")
        curl -s -o /dev/null -w "discord_status=%{http_code}\n" \
            -X POST \
            -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
            -H "Content-Type: application/json" \
            --max-time 10 \
            -d "${payload}" \
            "https://discord.com/api/v10/channels/${DISCORD_CHANNEL_ID}/messages" \
            >> "${LOG_FILE}" 2>&1
    else
        log "Discord creds missing — alert only logged locally"
    fi
fi

# ── Persist new baseline ──────────────────────────────────────────────────
echo "${CUR_JSON}" > "${STATE_FILE}"
