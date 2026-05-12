# infra/ — systemd units and host-side install

This directory contains the systemd unit files that run the OpenClaw stack
in production. They are checked in so a fresh host (rebuild, disk swap,
Debian PC migration) can be brought back online from `git` alone, without
relying on a backup tarball or a hand-typed recreation.

## What's here

| File | Purpose |
|---|---|
| `systemd/consensus-engine.service` | The signal-pipeline daemon. Runs `python3 -m consensus_engine --live` as the `openclaw` user. Sources `/home/openclaw/.openclaw/.env.service`. |
| `systemd/openclaw-gateway.service` | The agent runtime / WebSocket gateway used by the `@-mention` Discord path and any other client-of-the-runtime. Listens on `127.0.0.1:18789`. |

Both units are byte-identical to the live `/etc/systemd/system/` versions —
the install commands below preserve that contract.

## Install (fresh host)

```bash
# Prerequisites (do these first if not already done):
#   - The 'openclaw' user must exist with home /home/openclaw
#   - /home/openclaw/.openclaw/.env.service must contain API keys and Discord webhooks
#   - The workspace is at /home/openclaw/.openclaw/workspace
#   - /root/.openclaw -> /home/openclaw/.openclaw (symlink, per 2026-05-11 consolidation)
#   - Python 3, docker (for SearXNG), and the `openclaw` CLI are on PATH

# Install both units:
sudo cp infra/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now consensus-engine.service openclaw-gateway.service

# Verify:
systemctl is-active consensus-engine openclaw-gateway
# Expected: both 'active'
```

## Why the non-obvious bits exist

These details were learned the hard way during the 2026-05-11 VPS
consolidation. They're the actual reason this directory exists.

### Gateway unit

- `ExecStart=/usr/bin/openclaw gateway --port 18789 --bind loopback` —
  the entrypoint is `openclaw gateway`, NOT `openclaw gateway start`. The
  latter was an early misread that cost ~hour during consolidation.
- `--bind loopback` keeps the runtime local-only. The Discord plugin in
  the gateway is intentionally disabled (`openclaw.json`) so the only
  thing that talks to the runtime is the consensus engine's
  `_handle_mention` subprocess invocation.
- `RestartPreventExitStatus=78` allows the gateway to exit cleanly on an
  intentional EX_CONFIG (78) without systemd restart-looping.
- `Environment=HOME=/home/openclaw` is required so the runtime resolves
  `~/.openclaw` to the canonical workspace, not to root's home.

### Consensus engine unit

- `ProtectSystem=strict` blocks writes to `/usr`, `/boot`, `/etc`. To let
  the engine still write its database, logs, and `.omc/` state, the unit
  explicitly opens `ReadWritePaths=/home/openclaw/.openclaw /root/.openclaw /tmp`.
- `/root/.openclaw` is listed even though it is a symlink to
  `/home/openclaw/.openclaw`. systemd resolves the symlink separately when
  applying `ProtectSystem=strict`, so both endpoints need to be RW for the
  engine to traverse legacy `/root/.openclaw/...` paths that some older
  imports still produce.
- `OOMScoreAdj=-500` makes the engine harder for the OOM killer to reap.
  On the 8GB host the engine carries the most state in RAM; preferring
  to kill workers first preserves recoverability.
- `LimitNOFILE=65536` accommodates aiohttp's pooled sockets (TCPConnector
  `limit=30` × multiple scanners + sqlite + LLM streams).
- `PrivateTmp=yes` gives the engine its own `/tmp` namespace so debug
  artifacts don't bleed into the host's `/tmp`.
- `Wants=docker.service` (soft) + `After=docker.service` means the engine
  comes up *after* docker if docker is available (for the SearXNG
  container), but doesn't fail to start if docker isn't installed (dev
  hosts).

## How to verify the engine actually came up clean

After `systemctl restart consensus-engine.service`, check for the drift line:

```bash
sudo journalctl -u consensus-engine.service --since "1 minute ago" \
  | grep -i "boot drift check"
# Expected: "boot drift check: gateway chain matches consensus.yaml"
```

Absence of that line, or a `❌ GATEWAY drift` line on Discord, means the
gateway and consensus engine disagree about the active LLM chain. See
`consensus_engine/gateway/drift.py` for resolution steps.

## Updating these files when the live units change

The live units are the source of truth (`systemctl edit` is a common
mid-incident tool). After any live edit, re-sync the checked-in copies:

```bash
sudo systemctl cat openclaw-gateway.service | tail -n +2 \
  > infra/systemd/openclaw-gateway.service
sudo systemctl cat consensus-engine.service | tail -n +2 \
  > infra/systemd/consensus-engine.service
git diff infra/systemd/    # review the delta
git add infra/systemd/ && git commit -m "infra(systemd): sync to live <reason>"
```

The `tail -n +2` strips the leading `# /etc/systemd/system/...` comment
that `systemctl cat` prepends, which otherwise causes a false diff.
