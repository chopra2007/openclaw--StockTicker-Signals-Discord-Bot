#!/usr/bin/env bash
# Turn the member dashboard (akash.ignorelist.com) off or on to save memory and CPU. Run as root.
#   off    stop every dashboard program and timer, and keep them off after a reboot
#   on     start them again (fresh Schwab token first, then the programs, then the timers)
#   status show what is running
# The bot itself (consensus-engine) and nginx are never touched.
set -uo pipefail
SERVICES="member-dashboard-authority member-dashboard-quota member-dashboard-api member-dashboard-worker member-dashboard-frontend"
TIMERS="member-dashboard-schwab-sync.timer member-dashboard-archive.timer member-dashboard-size-check.timer"

status() {
  for u in $SERVICES $TIMERS; do printf '  %-36s %s\n' "$u" "$(systemctl is-active "$u")"; done
  curl -s -o /dev/null -w '  website answers with code %{http_code}\n' --max-time 10 https://akash.ignorelist.com/login
}

case "${1:-status}" in
  off)
    systemctl disable --now $TIMERS $SERVICES >/dev/null 2>&1
    systemctl stop member-dashboard-schwab-sync.service member-dashboard-schwab-renew.service >/dev/null 2>&1
    systemctl reset-failed $SERVICES >/dev/null 2>&1  # the web program exits with code 143 on a normal stop
    status ;;
  on)
    systemctl start member-dashboard-schwab-sync.service
    systemctl enable --now $SERVICES $TIMERS >/dev/null 2>&1
    for _ in $(seq 30); do curl -sf -o /dev/null --max-time 5 https://akash.ignorelist.com/login && break; sleep 2; done
    status ;;
  status) status ;;
  *) echo "usage: $0 on|off|status" >&2; exit 2 ;;
esac
