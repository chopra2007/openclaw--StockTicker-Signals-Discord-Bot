#!/usr/bin/env bash
# Cron wrapper: run the v2 reference-video E2E harness and log the result.
#
# Intended to fire ~00:15 PT daily, 15 min after the Gemini free-tier quota
# resets at Pacific midnight. Logs to .omc/logs/v2_assertions_YYYYMMDD.log.
#
# Autonomy contract: this script must not require any interactive input. It
# sources the project's .env for API keys, runs the python harness, and
# exits. If the budget is still exhausted for any reason, the harness
# returns (None, telemetry) and the assertions fail — the failure is a
# signal in the log, not a crash.

set -u

WORKSPACE="/home/openclaw/.openclaw/workspace"
ENV_FILE="/home/openclaw/.openclaw/.env"
LOG_DIR="${WORKSPACE}/.omc/logs"
LOG_FILE="${LOG_DIR}/v2_assertions_$(date +%Y%m%d).log"

mkdir -p "${LOG_DIR}"

{
    echo "=========================================="
    echo "run_reference_assertions_cron  $(date -Is)"
    echo "=========================================="
    if [ -f "${ENV_FILE}" ]; then
        set -a
        # shellcheck disable=SC1090
        . "${ENV_FILE}"
        set +a
    else
        echo "WARN: ${ENV_FILE} missing — API keys may be unavailable."
    fi
    cd "${WORKSPACE}" || { echo "ERR: cd ${WORKSPACE} failed"; exit 1; }
    /usr/bin/python3 scripts/run_reference_assertions.py
    echo "--- exit $? ---"
} >> "${LOG_FILE}" 2>&1
