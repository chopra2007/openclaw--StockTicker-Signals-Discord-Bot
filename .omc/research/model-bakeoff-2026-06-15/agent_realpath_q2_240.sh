#!/bin/bash
set -u
OUT=/tmp/agentrt; OCBIN=/usr/bin/openclaw
MSG="Give me a quick read on NVDA today — bullish or bearish, and why?"
declare -A MODELS=(
  [oss120]="openrouter/openai/gpt-oss-120b"
  [qwen30]="openrouter/qwen/qwen3-30b-a3b-instruct-2507"
)
run_one(){
  local mtag="$1" model="$2" tag="${1}__q2" start end
  start=$(date +%s)
  sudo -u openclaw -H "$OCBIN" agent --local --json --agent main \
    --model "$model" --session-id "bakeoff-rt240-$tag" \
    --message "$MSG" --timeout 240 \
    >"$OUT/$tag.json" 2>"$OUT/$tag.err"
  local rc=$?; end=$(date +%s)
  echo "tag=$tag model=$model rc=$rc secs=$((end-start)) bytes=$(wc -c <"$OUT/$tag.json")" >"$OUT/$tag.meta"
}
for mtag in "${!MODELS[@]}"; do run_one "$mtag" "${MODELS[$mtag]}" & done
wait
echo "=== Q2-240 RERUN DONE ===" > "$OUT/_q2240complete"
cat "$OUT/oss120__q2.meta" "$OUT/qwen30__q2.meta" >> "$OUT/_q2240complete"
