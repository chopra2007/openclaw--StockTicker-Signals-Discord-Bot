#!/bin/bash
# TODO #57 data-collection: run the Schwab-vs-yfinance flow shadow compare in
# REPORT-ONLY mode (NO --apply, so it never flips flow_loop_enabled) and post the
# result. The compare now emits per-contract numbers (volume / OI / vol-OI ratio /
# premium) for every disagreed contract + writes a CSV, so a human can judge which
# feed was right by the actual size of each bet, not just which side flagged it.
#
# Runs the python as the openclaw user (owns config + Schwab creds, so a token
# refresh or CSV write never flips ownership). One-shot: always exits 0 so
# run_task.sh does not retry. The python's --notify handles the #chat + log post.
set +e

sudo -n -u openclaw bash -c 'set -a; . /home/openclaw/.openclaw/.env.service; set +a; cd /home/openclaw/.openclaw/workspace; python3 scripts/schwab_flow_shadow_compare.py --notify'

exit 0
