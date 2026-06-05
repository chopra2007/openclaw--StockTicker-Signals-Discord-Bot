#!/bin/bash
# v2: robust parse + stderr capture + token usage. Real openclaw agent path.
KEY=$(grep -m1 -oE 'sk-or-[A-Za-z0-9_-]+' /root/.openclaw/.env | head -1)
Q="Read the file consensus_engine/scanners/options.py and tell me in ONE sentence what external data source the options flow uses. You must read the actual file, do not guess."
OUT=/tmp/model_test/agent_results2.jsonl
: > "$OUT"
MODELS=(
  "openai/gpt-oss-120b:free"
  "openai/gpt-oss-120b"
  "openai/gpt-5-nano"
  "openai/gpt-4.1-nano"
  "qwen/qwen3-235b-a22b-2507"
  "qwen/qwen3-235b-a22b-thinking-2507"
  "deepseek/deepseek-v4-flash"
  "minimax/minimax-m2.1"
  "xiaomi/mimo-v2-flash"
  "z-ai/glm-4.7-flash"
  "google/gemini-2.5-flash-lite"
)
for m in "${MODELS[@]}"; do
  slug=$(echo "$m" | tr '/:.' '---')
  echo ">>> $m" >&2
  errf=/tmp/model_test/err_${slug}.log
  raw=$(sudo -u openclaw env HOME=/home/openclaw TMPDIR=/home/openclaw/.openclaw/.octmp OPENROUTER_API_KEY="$KEY" \
    openclaw agent --local --agent main --model "openrouter/$m" \
    --session-id "bo2-${slug}" --message "$Q" --timeout 200 --json 2>"$errf")
  MODEL="$m" ERRF="$errf" RAW="$raw" python3 -c "
import os,sys,json
m=os.environ['MODEL']; raw=os.environ['RAW']
i=raw.find('{')
rec={'model':m}
if i<0:
    err=open(os.environ['ERRF']).read()
    err=[l for l in err.splitlines() if l.strip() and not l.startswith('[secrets]')]
    rec.update(ok=False, why=(err[-1] if err else 'empty stdout')[:140])
else:
    try:
        d=json.loads(raw[i:])
        pay=(d.get('payloads') or [{}])
        text=(pay[0].get('text') or '').strip()
        meta=(d.get('meta') or {}).get('agentMeta') or {}
        u=meta.get('usage') or {}
        ok=bool(text) and text!='(agent returned no content)'
        rec.update(ok=ok, correct=('yfinance' in text.lower()),
            durationMs=(d.get('meta') or {}).get('durationMs'),
            in_tok=u.get('input'), out_tok=u.get('output'), reason_tok=u.get('reasoningTokens'),
            reply=text[:200])
    except Exception as e:
        rec.update(ok=False, why='parse:'+str(e)[:100])
print(json.dumps(rec))
" >> "$OUT"
  tail -1 "$OUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print('   '+('OK ' if d.get('ok') else 'FAIL ')+f\"correct={d.get('correct')} {d.get('durationMs')}ms in={d.get('in_tok')} out={d.get('out_tok')} reason={d.get('reason_tok')} {d.get('why','')}\")" >&2
done
echo "AGENT2_DONE" >&2
