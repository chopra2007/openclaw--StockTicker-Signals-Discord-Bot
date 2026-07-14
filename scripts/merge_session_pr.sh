#!/usr/bin/env bash
# merge_session_pr.sh — session-close step: merge THIS session's pull request, but only if CI is green.
#
# Usage: merge_session_pr.sh <branch>
#
# Finds the open PR whose head branch is <branch>, takes it out of draft, waits for the
# Regression Gate check to finish, and merges it only if that check passed. A red or missing
# check leaves the PR open and writes a loud line to notifications.log (surfaced at session start).
#
# Only ever touches the PR for <branch> — other open PRs (parallel jobs, deliberately parked
# work) are never merged.

set -uo pipefail

BRANCH="${1:-}"
REPO="chopra2007/openclaw--StockTicker-Signals-Discord-Bot"
NOTIF="/root/task_system/notifications.log"
LOG_DIR="/root/task_system/logs"
LOG="$LOG_DIR/merge_session_pr_$(date +%Y%m%d_%H%M%S).log"

POLL_SECONDS=30
MAX_WAIT_SECONDS=1800   # 30 min: CI run is ~3-5 min, this is a generous ceiling

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
notify() { echo "[$(date -Iseconds)] $*" >> "$NOTIF" 2>/dev/null || true; }

if [ -z "$BRANCH" ]; then
    log "No branch given — usage: merge_session_pr.sh <branch>"
    exit 2
fi

if [ "$BRANCH" = "master" ]; then
    log "On master — no session PR to merge, nothing to do"
    exit 0
fi

# Push the branch from HERE, not from the session. `git push` fires the pre-push hook,
# which runs the WHOLE test suite (~7-8 min). Doing that in the session at close time
# made "bye" block for 12 minutes — the exact opposite of what "bye" is for. Everything
# slow belongs in this background script so the session can be closed immediately.
if [ -n "$(git log "origin/$BRANCH..$BRANCH" --oneline 2>/dev/null || echo push)" ]; then
    log "Pushing '$BRANCH' (runs the pre-push test gate — minutes, but nobody is waiting)"
    if ! git push origin "$BRANCH" >>"$LOG" 2>&1; then
        log "Push of '$BRANCH' was REJECTED — not merging"
        notify "🚨 SESSION-CLOSE PUSH FAILED — branch '$BRANCH' would not push (the pre-push test gate failed, or the branch is behind). Nothing was merged. See $LOG"
        exit 1
    fi
fi

PR=$(gh api "repos/$REPO/pulls?state=open&head=chopra2007:$BRANCH" --jq '.[0].number // empty' 2>>"$LOG")
if [ -z "$PR" ]; then
    # Opening the PR is also slow-ish and used to sit in the session's foreground. Do it here.
    log "No open PR for '$BRANCH' — opening one"
    gh pr create --repo "$REPO" --base master --head "$BRANCH" --fill >>"$LOG" 2>&1 || true
    PR=$(gh api "repos/$REPO/pulls?state=open&head=chopra2007:$BRANCH" --jq '.[0].number // empty' 2>>"$LOG")
fi
if [ -z "$PR" ]; then
    log "No PR for branch '$BRANCH' and one could not be opened — nothing to merge"
    notify "⚠️ SESSION-CLOSE — branch '$BRANCH' was pushed but no PR could be opened, so nothing was merged. See $LOG"
    exit 1
fi
log "Using PR #$PR for branch '$BRANCH'"

if [ "$(gh api "repos/$REPO/pulls/$PR" --jq '.draft')" = "true" ]; then
    log "PR #$PR is a draft — marking it ready for review"
    gh pr ready "$PR" --repo "$REPO" >>"$LOG" 2>&1 || {
        log "Could not take PR #$PR out of draft — leaving it open"
        notify "⚠️ SESSION-CLOSE MERGE SKIPPED — PR #$PR ($BRANCH) is still a draft and could not be marked ready. Merge it by hand."
        exit 1
    }
fi

SHA=$(gh api "repos/$REPO/pulls/$PR" --jq '.head.sha')
log "Waiting for CI checks on $SHA (poll ${POLL_SECONDS}s, give up after $((MAX_WAIT_SECONDS / 60)) min)"

WAITED=0
while [ "$WAITED" -lt "$MAX_WAIT_SECONDS" ]; do
    RUNS=$(gh api "repos/$REPO/commits/$SHA/check-runs" \
        --jq '.check_runs[] | .status + ":" + (.conclusion // "pending")' 2>>"$LOG")

    if [ -n "$RUNS" ] && ! printf '%s\n' "$RUNS" | grep -qv '^completed:'; then
        # Every check has finished. Anything other than success/skipped/neutral is a red check.
        BAD=$(printf '%s\n' "$RUNS" | grep -vE '^completed:(success|skipped|neutral)$' || true)
        if [ -n "$BAD" ]; then
            log "CI FAILED on PR #$PR — not merging. Results: $(printf '%s' "$RUNS" | tr '\n' ' ')"
            notify "🚨 SESSION-CLOSE MERGE BLOCKED — the tests on PR #$PR ($BRANCH) FAILED, so it was NOT merged. The PR is still open: https://github.com/$REPO/pull/$PR"
            exit 1
        fi
        log "CI green on PR #$PR — merging"
        MERGE_OUT=$(gh pr merge "$PR" --repo "$REPO" --merge --delete-branch 2>&1)
        MERGE_RC=$?
        printf '%s\n' "$MERGE_OUT" | tee -a "$LOG"
        if [ "$MERGE_RC" -ne 0 ]; then
            log "Merge of PR #$PR failed (exit $MERGE_RC)"
            notify "🚨 SESSION-CLOSE MERGE FAILED — the tests on PR #$PR ($BRANCH) passed but GitHub refused the merge (likely a conflict with master). Last error: $(printf '%s' "$MERGE_OUT" | tail -2 | tr '\n' ' '). Merge it by hand: https://github.com/$REPO/pull/$PR"
            exit 1
        fi
        log "PR #$PR merged and branch deleted"
        exit 0
    fi

    sleep "$POLL_SECONDS"
    WAITED=$((WAITED + POLL_SECONDS))
done

log "Timed out after $((MAX_WAIT_SECONDS / 60)) min waiting for CI on PR #$PR — not merging"
notify "⚠️ SESSION-CLOSE MERGE TIMED OUT — the tests on PR #$PR ($BRANCH) had not finished after $((MAX_WAIT_SECONDS / 60)) min, so it was NOT merged. The PR is still open: https://github.com/$REPO/pull/$PR"
exit 1
