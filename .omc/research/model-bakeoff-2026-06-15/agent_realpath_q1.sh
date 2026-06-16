#!/bin/bash
set -u
OUT=/tmp/agentrt; mkdir -p "$OUT"
OCBIN=/usr/bin/openclaw
MSG="What is AAPL trading at right now?"   # apostrophe-free (quoting-safe)
declare -A MODELS=(
  [oss120]="openrouter/openai/gpt-oss-120b"
  [msmall]="openrouter/mistralai/mistral-small-3.2-24b-instruct"
  [qwen30]="openrouter/qwen/qwen3-30b-a3b-instruct-2507"
)
run_one(){
  local mtag="$1" model="$2" tag="${1}__q1" start end
  start=$(date +%s)
  sudo -u openclaw -H "$OCBIN" agent --local --json --agent main \
    --model "$model" --session-id "bakeoff-rt-$tag" \
    --message "$MSG" --timeout 160 \
    >"$OUT/$tag.json" 2>"$OUT/$tag.err"
  local rc=$?; end=$(date +%s)
  echo "tag=$tag model=$model rc=$rc secs=$((end-start)) bytes=$(wc -c <"$OUT/$tag.json")" >"$OUT/$tag.meta"
}
for mtag in "${!MODELS[@]}"; do run_one "$mtag" "${MODELS[$mtag]}" & done
wait
echo "=== Q1 RERUN DONE ===" > "$OUT/_q1complete"
cat "$OUT"/*q1.meta >> "$OUT/_q1complete"
