#!/bin/bash
# TODO #57: run the Schwab-vs-yfinance flow-loop shadow compare as the openclaw
# user (so a token refresh never flips schwab_token.json ownership) with creds +
# the Discord webhook loaded, and post the verdict to notifications.log + #chat.
sudo -n -u openclaw bash -c 'set -a; . /home/openclaw/.openclaw/.env.service; set +a; cd /home/openclaw/.openclaw/workspace; python3 scripts/schwab_flow_shadow_compare.py --notify'
