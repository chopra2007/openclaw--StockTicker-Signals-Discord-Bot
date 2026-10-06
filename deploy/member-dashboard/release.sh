#!/bin/bash
# Copy the dashboard code from the repo into /opt/member-dashboard/current and restart.
# Run as root. Add --web to also rebuild the website (npm ci + next build, ~2 min).
set -euo pipefail
REPO=/home/openclaw/.openclaw/workspace
CUR=/opt/member-dashboard/current
COPY=(rsync -a --delete --exclude __pycache__ --chown=root:root --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r)
"${COPY[@]}" "$REPO/member_dashboard" "$REPO/consensus_engine" "$CUR/"
"${COPY[@]}" "$REPO"/scripts/member_dashboard_*.{py,mjs} "$CUR/scripts/"
if [ "${1:-}" = "--web" ]; then
  "${COPY[@]}" --exclude node_modules --exclude .next --exclude .e2e "$REPO/web/member-dashboard" "$CUR/web/"
  (cd "$CUR/web/member-dashboard" && npm ci --no-audit --no-fund && NEXT_TELEMETRY_DISABLED=1 npm run build)
  chmod -R go+rX "$CUR/web/member-dashboard"
  install -d -o md-frontend -g md-frontend -m 0700 "$CUR/web/member-dashboard/.next/cache"
fi
systemctl restart member-dashboard-api member-dashboard-worker
[ "${1:-}" = "--web" ] && systemctl restart member-dashboard-frontend
systemctl is-active member-dashboard-api member-dashboard-worker
