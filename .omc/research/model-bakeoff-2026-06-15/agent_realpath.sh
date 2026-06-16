#!/bin/bash
# Real-path agent test: run the REAL `openclaw agent --local` path per candidate
# model (no live-config change beyond the temp allow-map). Run as openclaw to
# avoid the root ownership-flip. 3 models x 2 questions, in parallel.
set -u
OUT=/tmp/agentrt
mkdir -p "$OUT"; rm -f "$OUT"/*
OCBIN=/usr/bin/openclaw

declare -A MODELS=(
  [oss120]="openrouter/openai/gpt-oss-120b"
  [msmall]="openrouter/mistralai/mistral-small-3.2-24b-instruct"
  [qwen30]="openrouter/qwen/qwen3-30b-a3b-instruct-2507"
)
declare -A Q=(
  [q1]="What's AAPL trading at right now?"
  [q2]="Give me a quick read on NVDA today — bullish or bearish, and why?"
)

run_one() {
  local mtag="$1" qtag="$2" model="$3" msg="$4"
  local tag="${mtag}__${qtag}"
  local start end
  start=$(date +%s)
  sudo -u openclaw -H bash -lc "$OCBIN agent --local --json --agent main \
    --model '$model' --session-id 'bakeoff-rt-$tag' \
    --message '$msg' --timeout 160" \
    >"$OUT/$tag.json" 2>"$OUT/$tag.err"
  local rc=$?
  end=$(date +%s)
  echo "tag=$tag model=$model rc=$rc secs=$((end-start)) bytes=$(wc -c <"$OUT/$tag.json")" >"$OUT/$tag.meta"
}

for mtag in "${!MODELS[@]}"; do
  for qtag in "${!Q[@]}"; do
    run_one "$mtag" "$qtag" "${MODELS[$mtag]}" "${Q[$qtag]}" &
  done
done
wait
echo "=== ALL DONE ===" > "$OUT/_complete"
cat "$OUT"/*.meta >> "$OUT/_complete"
echo "agent real-path batch complete"
