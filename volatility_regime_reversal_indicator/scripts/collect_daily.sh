#!/usr/bin/env bash
# Daily forward-collection of the two FREE feeds for TODO #47 Track B:
#   - CBOE_PUTCALL  (put/call ratios, via src.data.fetch_putcall)
#   - NYSE_BREADTH  (adv/dec issues + up/down volume, via src.data.fetch_nyse_breadth)
#
# Idempotent: both fetchers are append-only, so re-running on the same day is a
# no-op (the date already exists). Logs to logs/collect_daily.log. Exits non-zero
# on a hard failure so the systemd timer's retry/restart can trigger.
set -uo pipefail

REPO="/home/openclaw/.openclaw/workspace/volatility_regime_reversal_indicator"
LOG_DIR="${REPO}/logs"
LOG="${LOG_DIR}/collect_daily.log"
mkdir -p "$LOG_DIR"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

cd "$REPO" || { log "FATAL: cannot cd to $REPO"; exit 1; }

log "=== collect_daily start ==="

MAX_ATTEMPTS=3
RETRY_SLEEP=120  # seconds between attempts (rides out transient 429/timeout)

RC=0
for FETCHER in src.data.fetch_putcall src.data.fetch_nyse_breadth; do
    ok=0
    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        log "running ${FETCHER} (attempt ${attempt}/${MAX_ATTEMPTS})"
        if python3 -m "$FETCHER" >>"$LOG" 2>&1; then
            log "OK ${FETCHER}"
            ok=1
            break
        fi
        log "FAIL ${FETCHER} attempt ${attempt}"
        [[ $attempt -lt $MAX_ATTEMPTS ]] && sleep "$RETRY_SLEEP"
    done
    [[ $ok -eq 0 ]] && { log "GAVE UP ${FETCHER} after ${MAX_ATTEMPTS} attempts"; RC=1; }
done

log "=== collect_daily done (rc=${RC}) ==="
exit "$RC"
