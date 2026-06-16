#!/bin/bash
# Agent real-path matrix: 4 candidate leads x 3 heavy questions, real openclaw
# agent path. 150s SCREEN timeout (converging models finish <50s; runaway
# tool-loop models get cut, saving tokens). Run as openclaw (no ownership flip).
# Max 4 concurrent (one wave per question).
set -u
OUT=/tmp/agentmx; mkdir -p "$OUT"; rm -f "$OUT"/*
OCBIN=/usr/bin/openclaw
declare -A MODELS=(
  [oss120]="openrouter/openai/gpt-oss-120b"
  [msmall]="openrouter/mistralai/mistral-small-3.2-24b-instruct"
  [nano]="openrouter/openai/gpt-4.1-nano"
  [qwen235]="openrouter/qwen/qwen3-235b-a22b-2507"
)
declare -A Q=(
  [qA]="Give me a read on NVDA today — bullish or bearish, and why?"
  [qB]="What is moving the market today and what should I watch?"
  [qC]="What are the latest catalysts for AMD and is the setup actionable?"
)
run_one(){
  local mtag="$1" qtag="$2" model="$3" msg="$4" tag="${1}__${2}" start end
  start=$(date +%s)
  sudo -u openclaw -H "$OCBIN" agent --local --json --agent main \
    --model "$model" --session-id "bakeoffmx-$tag" \
    --message "$msg" --timeout 150 \
    >"$OUT/$tag.json" 2>"$OUT/$tag.err"
  local rc=$?; end=$(date +%s)
  echo "tag=$tag rc=$rc secs=$((end-start)) bytes=$(wc -c <"$OUT/$tag.json")" >"$OUT/$tag.meta"
}
for qtag in qA qB qC; do          # one wave per question = max 4 concurrent
  for mtag in "${!MODELS[@]}"; do
    run_one "$mtag" "$qtag" "${MODELS[$mtag]}" "${Q[$qtag]}" &
  done
  wait
done
echo "=== MATRIX DONE ===" > "$OUT/_complete"
cat "$OUT"/*.meta >> "$OUT/_complete"
