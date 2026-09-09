#!/usr/bin/env bash
# Run pytest inside a private process area so a broken signal test cannot reach
# SSH, the live bot, Docker, or any other host process.

set -euo pipefail

# Test the checkout the CALLER is in, not the one this script happens to live in.
# The stop hook calls this by absolute path from a worktree; resolving the root
# from the script's own location silently tested the main checkout's code instead.
# safe.directory: the stop hook runs as root while the checkouts belong to
# openclaw; without this git refuses to answer and we'd silently fall back.
CALLER_ROOT="$(git -c safe.directory='*' -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
REPO_ROOT="${CALLER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRATCH="$(mktemp -d /tmp/openclaw-tests.XXXXXX)"
PYTEST_ENV=(
    "HOME=/tmp"
    "TMPDIR=${SCRATCH}"
    "PYTHONDONTWRITEBYTECODE=1"
    "PYTHONPYCACHEPREFIX=${SCRATCH}/pycache"
)

cd "$REPO_ROOT"
trap 'rm -rf -- "$SCRATCH"' EXIT

if [ "$(id -u)" -eq 0 ]; then
    chown openclaw:openclaw "$SCRATCH"
    unshare --fork --pid --mount-proc -- \
        setpriv --reuid openclaw --regid openclaw --init-groups -- \
        env "${PYTEST_ENV[@]}" python3 -m pytest "$@"
    exit $?
fi

if [ "$(id -un)" = "openclaw" ]; then
    unshare --user --map-root-user --fork --pid --mount-proc -- \
        env "${PYTEST_ENV[@]}" python3 -m pytest "$@"
    exit $?
fi

# Other development machines may not host the live bot or support Linux
# namespaces. Keep their optional local push script portable.
env "${PYTEST_ENV[@]}" python3 -m pytest "$@"
