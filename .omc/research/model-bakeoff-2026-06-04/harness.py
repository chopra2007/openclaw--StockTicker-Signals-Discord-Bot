#!/usr/bin/env python3
"""Model bake-off harness. Hits OpenRouter directly; mirrors the bot's success
rule (HTTP 200 AND non-empty message.content; empty content from a reasoning
model = failure, exactly like consensus_engine/llm_client.py)."""
import os, json, time, concurrent.futures as cf, urllib.request, urllib.error, re

API = "https://openrouter.ai/api/v1/chat/completions"
# load key
kv = open("/tmp/model_test/.k").read().strip()
KEY = kv.split("=",1)[1].strip().strip('"').strip("'")

PRIMARY = [
    "deepseek/deepseek-v4-flash",
    "qwen/qwen3-235b-a22b-2507",
    "qwen/qwen3-235b-a22b-thinking-2507",
    "openai/gpt-oss-120b",
    "google/gemini-2.5-flash-lite",
    "z-ai/glm-4.7-flash",
    "nvidia/nemotron-3-super-120b-a12b",
    "deepseek/deepseek-v3.2",
    "openai/gpt-5-nano",
    "minimax/minimax-m2.1",
    "qwen/qwen3.5-flash-02-23",
    "meta-llama/llama-4-maverick",
]
TEXT = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-oss-20b",
    "amazon/nova-micro-v1",
    "mistralai/ministral-3b-2512",
    "mistralai/ministral-8b-2512",
    "nvidia/nemotron-nano-9b-v2",
    "qwen/qwen3.5-9b",
    "openai/gpt-4.1-nano",
    "openai/gpt-5-nano",
    "cohere/command-r7b-12-2024",
    "mistralai/mistral-nemo",
    "meta-llama/llama-3.2-3b-instruct:free",
]
EXTRAS = ["openrouter/owl-alpha", "minimax/minimax-m2.5", "xiaomi/mimo-v2-flash"]
REF = ["openrouter/free", "openai/gpt-oss-120b:free"]

FIN_PROMPT = """You are a financial analyst. Based ONLY on the data below, write a concise trade thesis for NVDA.
DATA:
- Price: $182.40, +2.1% today, relative volume 1.8x
- 52-week range: $86.62 - $195.95 (near highs)
- Options: call/put volume ratio 2.3; unusual call sweeps at $190 and $200 strikes expiring Friday; max pain $180
- Catalyst: announced new Rubin GPU architecture at GTC; 3 analysts raised price targets (avg new target $220)
- Technicals: above 9/21 EMA, RSI 68 (approaching overbought); support $176, resistance $186 then $195
- Peer strength: SMH semiconductor ETF +1.4%; NVDA outperforming AMD (+0.3%) today
OUTPUT (strict format):
DIRECTION: <bullish/bearish/neutral>
THESIS: <2-3 sentences citing the specific catalysts and levels>
KEY LEVELS: entry, stop, target
RISK: <1 sentence>
Keep under 120 words. Do not invent any data not provided."""

TXT_PROMPT = """You score stock-mention tweets for a trading-signal bot. Return ONLY compact JSON, no prose.
TWEET: "$TSLA breaking out above 250 on huge volume, next leg to 270 imo. robotaxi event next week"
Return exactly: {"ticker":"...","direction":"bullish|bearish|neutral","score":0-100,"reason":"<=8 words"}"""

def call(model, prompt, max_tokens, uid=None):
    # uid (non-None) appends a unique marker so providers can't serve a cached
    # response to an identical repeated request -> real latency + reliability.
    msg = prompt if uid is None else f"{prompt}\n(request id: {uid}; ignore this line)"
    body = json.dumps({
        "model": model,
        "messages": [{"role":"user","content":msg}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://local.test", "X-Title": "model-bakeoff",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            dt = time.time()-t0
            j = json.loads(r.read())
            ch = (j.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning") or "")
            err = j.get("error")
            if err:
                return {"ok":False,"dt":dt,"why":f"apierr:{str(err)[:60]}","content":""}
            if not content:
                return {"ok":False,"dt":dt,"why":f"empty-content(reasoning={len(reasoning)})","content":""}
            return {"ok":True,"dt":dt,"why":"","content":content,"finish":ch.get("finish_reason")}
    except urllib.error.HTTPError as e:
        dt=time.time()-t0
        try: detail=e.read().decode()[:120]
        except: detail=""
        return {"ok":False,"dt":dt,"why":f"http{e.code}:{detail}","content":""}
    except Exception as e:
        dt=time.time()-t0
        return {"ok":False,"dt":dt,"why":f"{type(e).__name__}:{str(e)[:60]}","content":""}

_ctr=[0]
def test_model(model, prompt, max_tokens, n_seq=2, burst=3):
    calls=[]
    # call 0: CLEAN prompt -> captured for competence grading + true cold latency
    c0=call(model, prompt, max_tokens, uid=None)
    c0["kind"]="cold"; calls.append(c0)
    # extra sequential call(s): unique nonce -> uncached latency
    for i in range(n_seq-1):
        _ctr[0]+=1
        c=call(model, prompt, max_tokens, uid=f"{abs(hash(model))%9999}-{_ctr[0]}")
        c["kind"]="seq"; calls.append(c)
    # concurrency burst: unique nonce each -> reliability under parallel load
    def _b(i):
        _ctr[0]+=1
        return call(model, prompt, max_tokens, uid=f"{abs(hash(model))%9999}-b{i}-{_ctr[0]}")
    with cf.ThreadPoolExecutor(max_workers=burst) as ex:
        burst_res=list(ex.map(_b, range(burst)))
    for c in burst_res: c["kind"]="burst"
    calls.extend(burst_res)
    oks=[c for c in calls if c["ok"]]
    lat=sorted(c["dt"] for c in oks)
    p50 = lat[len(lat)//2] if lat else None
    sample = c0["content"] if c0["ok"] else next((c["content"] for c in calls if c["ok"]), "")
    return {
        "model":model,
        "n":len(calls), "n_ok":len(oks),
        "success_rate":round(len(oks)/len(calls),2),
        "cold_latency": round(c0["dt"],1),
        "cold_ok": c0["ok"],
        "p50_latency": round(p50,1) if p50 else None,
        "min_latency": round(lat[0],1) if lat else None,
        "max_latency": round(lat[-1],1) if lat else None,
        "fails":[c["why"] for c in calls if not c["ok"]],
        "sample": sample,
    }

def run(label, models, prompt, max_tokens):
    for m in models:
        print(f"[{label}] testing {m} ...", flush=True)
        r=test_model(m, prompt, max_tokens)
        print(f"   ok={r['n_ok']}/{r['n']} cold={r['cold_latency']}s p50={r['p50_latency']}s fails={r['fails'][:2]}", flush=True)
        results[label].append(r)
        json.dump(results, open("/tmp/model_test/results.json","w"), indent=1)

results={"meta":{"fin_max_tokens":8000,"txt_max_tokens":512},"financial":[],"text":[]}
json.dump(results, open("/tmp/model_test/results.json","w"), indent=1)

# Primary candidates + extras + free incumbent get the FINANCIAL prompt
run("financial", PRIMARY + EXTRAS + ["openai/gpt-oss-120b:free"], FIN_PROMPT, 8000)
# Text candidates + extras + incumbents get the SCORING prompt
run("text", TEXT + EXTRAS + REF, TXT_PROMPT, 512)
print("DONE", flush=True)
