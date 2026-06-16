#!/usr/bin/env python3
"""Front-line text-scorer CALIBRATION test (2026-06-15).

The text chain's FIRST model (gpt-4.1-nano) fires on every tweet-score, so the
question isn't 'does it work' but 'does it score SENSIBLY'. Uses the EXACT
_SYSTEM_PROMPT from consensus_engine/analysis/llm_scorer.py and 5 structured
scenarios tiered to that prompt's own 0-100 guideline bands. For each model we
check: ordering (A>B>C>D>E), how many scores land in their guideline band,
spread (A-E), self-consistency (A run twice), clean JSON, latency, cost.
"""
import json, time, urllib.request, urllib.error, socket
from concurrent.futures import ThreadPoolExecutor

API="https://openrouter.ai/api/v1/chat/completions"
KEY=None
for p in ("/root/.openclaw/.env.service","/root/.openclaw/.env",
          "/home/openclaw/.openclaw/.env.service","/home/openclaw/.openclaw/.env"):
    try:
        for ln in open(p):
            if ln.startswith("OPENROUTER_API_KEY="):
                KEY=ln.split("=",1)[1].strip().strip('"').strip("'"); break
    except Exception: pass
    if KEY: break
assert KEY

PRICE={}
for m in json.load(open("/tmp/or_models_20260615.json"))["data"]:
    pr=m.get("pricing") or {}
    def f(x):
        try:return float(x)
        except:return 0.0
    PRICE[m["id"]]=(f(pr.get("prompt"))*1e6, f(pr.get("completion"))*1e6)

# EXACT system prompt from llm_scorer.py
SYS="""You are a stock market analyst AI. You evaluate whether a stock ticker
represents a high-confidence early-stage breakout opportunity.

Given the following multi-source signal data, provide:
1. A confidence score from 0-100 (where 70+ means high-confidence breakout)
2. A brief 1-2 sentence reasoning

Respond ONLY in this exact JSON format:
{"confidence": <number>, "reasoning": "<string>"}

Scoring guidelines:
- 80-100: Strong multi-source agreement, clear catalyst, strong technicals, high conviction
- 70-79: Good agreement across sources, identifiable catalyst, decent technicals
- 50-69: Mixed signals, weak catalyst, or incomplete confirmation
- 30-49: Mostly hype, no clear catalyst, or bearish technicals
- 0-29: Likely noise, conflicting signals, or pump-and-dump risk"""

# 5 scenarios tiered to the bands above (built in _build_user_prompt style)
SCEN={
 "A": ("""Evaluate breakout potential for $AMD:

TWITTER/X SIGNALS:
- 6 analysts mentioned within 18 minutes
- Analysts: @LomahCrypto, @unusual_whales, @DeItaone, @Stocktwits, @zerohedge, @Mr_Derivatives
  > "AMD MI400 launch is a monster, loading calls, target 210"
  > "Data-center revenue +73% YoY, this breaks out today"

SEC/EDGAR FILINGS:
- Form 4: CEO bought 50,000 shares at $176 two days ago

NEWS CATALYST:
- Type: earnings_beat
- Summary: AMD beat Q1 EPS by 8.2% and raised full-year guidance
- Sources: Reuters, Bloomberg, CNBC
- Catalyst confidence: 92%

TECHNICAL DATA:
- Price: $178.45 (+4.1%)
  [PASS] RSI: 61 (threshold: <70)
  [PASS] Volume: 2.3x avg (threshold: >1.5x)
  [PASS] EMA9>EMA21: yes
  [PASS] Breakout above resistance $176: yes
- Filters passed: 6/6
""", (80,100)),

 "B": ("""Evaluate breakout potential for $SOFI:

TWITTER/X SIGNALS:
- 3 analysts mentioned within 35 minutes
- Analysts: @Stocktwits, @Mr_Derivatives, @falacy
  > "SOFI member growth strong, watching for a move over 12"

NEWS CATALYST:
- Type: analyst_upgrade
- Summary: Morgan Stanley upgraded SOFI to overweight, PT 14
- Sources: Benzinga, MarketWatch
- Catalyst confidence: 70%

TECHNICAL DATA:
- Price: $11.40 (+2.0%)
  [PASS] RSI: 58 (threshold: <70)
  [PASS] Volume: 1.7x avg (threshold: >1.5x)
  [FAIL] EMA9>EMA21: no
  [PASS] Breakout above resistance: yes
- Filters passed: 4/6
""", (70,79)),

 "C": ("""Evaluate breakout potential for $PLTR:

TWITTER/X SIGNALS:
- 2 analysts mentioned within 50 minutes
- Analysts: @Stocktwits, @random_trader
  > "PLTR maybe setting up, not sure yet"

NEWS CATALYST:
- Type: rumor
- Summary: unconfirmed chatter about a possible government contract
- Sources: Reddit
- Catalyst confidence: 35%

TECHNICAL DATA:
- Price: $24.10 (+0.6%)
  [PASS] RSI: 55 (threshold: <70)
  [FAIL] Volume: 1.1x avg (threshold: >1.5x)
  [FAIL] EMA9>EMA21: no
  [PASS] Price > 50d MA: yes
- Filters passed: 2/6
""", (50,69)),

 "D": ("""Evaluate breakout potential for $GME:

TWITTER/X SIGNALS:
- 4 analysts mentioned within 25 minutes
- Analysts: @wsb_chair, @diamondhands, @apemonkey, @yolo_trader
  > "GME squeeze incoming!! buy now"
  > "to the moon"

TECHNICAL DATA:
- Price: $21.30 (-2.4%)
  [FAIL] RSI: 74 (threshold: <70)
  [PASS] Volume: 3.0x avg (threshold: >1.5x)
  [FAIL] EMA9>EMA21: no
  [FAIL] Breakout above resistance: no (rejected)
- Filters passed: 1/6
""", (30,49)),

 "E": ("""Evaluate breakout potential for $XYZ:

TWITTER/X SIGNALS:
- 1 mention within 60 minutes
- Analysts: @pump_alerts_paid
  > "🚀🚀 $XYZ TO THE MOON 1000% GUARANTEED BUY NOW 🚀🚀"

TECHNICAL DATA:
- Price: $0.84 (+38.0%)
  [FAIL] RSI: 91 (threshold: <70)
  [PASS] Volume: 12x avg (threshold: >1.5x)
  [FAIL] EMA9>EMA21: no
  [FAIL] Sustainable move: no (vertical spike)
- Filters passed: 1/6
""", (0,29)),
}

MODELS=["openai/gpt-4.1-nano","mistralai/mistral-nemo","qwen/qwen3-235b-a22b-2507",
        "inclusionai/ling-2.6-flash","google/gemma-3-27b-it"]

def score(model, user):
    body={"model":model,"messages":[{"role":"system","content":SYS},{"role":"user","content":user}],
          "max_tokens":1024,"temperature":0.3}
    req=urllib.request.Request(API,data=json.dumps(body).encode(),headers={
        "Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    t=time.time()
    try:
        j=json.loads(urllib.request.urlopen(req,timeout=40).read())
        el=time.time()-t
        msg=(j.get("choices") or [{}])[0].get("message") or {}
        c=(msg.get("content") or "").strip()
        u=j.get("usage") or {}
        pin,pout=PRICE.get(model,(0,0))
        cost=(u.get("prompt_tokens",0)*pin+u.get("completion_tokens",0)*pout)/1e6
        cc=c
        if cc.startswith("```"):
            import re; cc=re.sub(r'^```(?:json)?\s*','',cc); cc=re.sub(r'\s*```$','',cc)
        conf=None
        try: conf=float(json.loads(cc).get("confidence"))
        except Exception:
            import re; mm=re.search(r'"?confidence"?\s*:\s*(\d+)',cc)
            if mm: conf=float(mm.group(1))
        return dict(conf=conf, lat=round(el,2), cost=round(cost,6),
                    clean=(conf is not None and cc.startswith("{")), head=c[:120])
    except (socket.timeout,TimeoutError):
        return dict(conf=None,lat=round(time.time()-t,2),cost=0,clean=False,head="TIMEOUT")
    except urllib.error.HTTPError as e:
        return dict(conf=None,lat=round(time.time()-t,2),cost=0,clean=False,head=f"HTTP{e.code}:{e.read()[:80].decode('utf-8','replace')}")
    except Exception as e:
        return dict(conf=None,lat=round(time.time()-t,2),cost=0,clean=False,head=f"ERR:{type(e).__name__}")

def run_model(model):
    res={}
    for k,(u,band) in SCEN.items():
        res[k]=score(model,u)
    res["A2"]=score(model,SCEN["A"][0])   # consistency repeat
    return model,res

RESULTS={}
with ThreadPoolExecutor(max_workers=5) as ex:
    for model,res in ex.map(run_model, MODELS):
        RESULTS[model]=res

# ---- analysis ----
print(f"{'model':34} {'A':>5}{'B':>5}{'C':>5}{'D':>5}{'E':>5}  order  inband  spread  A|A2  clean  $/run   lat")
bands={k:SCEN[k][1] for k in SCEN}
summary={}
for model in MODELS:
    r=RESULTS[model]
    cs={k:r[k]["conf"] for k in ["A","B","C","D","E"]}
    vals=[cs[k] for k in ["A","B","C","D","E"]]
    order_ok = all(v is not None for v in vals) and all(vals[i]>vals[i+1] for i in range(4))
    inband=sum(1 for k in ["A","B","C","D","E"] if cs[k] is not None and bands[k][0]<=cs[k]<=bands[k][1])
    spread=(vals[0]-vals[4]) if (vals[0] is not None and vals[4] is not None) else None
    cons=abs(r["A"]["conf"]-r["A2"]["conf"]) if (r["A"]["conf"] is not None and r["A2"]["conf"] is not None) else None
    clean=sum(1 for k in ["A","B","C","D","E","A2"] if r[k]["clean"])
    cost=sum(r[k]["cost"] for k in r)
    lat=round(sum(r[k]["lat"] for k in r)/len(r),2)
    def fmt(x): return f"{int(x):>5}" if x is not None else "  n/a"
    print(f"{model:34} {fmt(cs['A'])}{fmt(cs['B'])}{fmt(cs['C'])}{fmt(cs['D'])}{fmt(cs['E'])}"
          f"   {'OK ' if order_ok else 'BAD'}   {inband}/5    {str(spread):>4}  {str(cons):>4}   {clean}/6  ${cost:.5f} {lat}s")
    summary[model]=dict(scores=cs,order_ok=order_ok,inband=inband,spread=spread,consistency=cons,clean=clean,cost=round(cost,6),avg_lat=lat)

json.dump({"summary":summary,"raw":RESULTS,"bands":bands},
          open("/home/openclaw/.openclaw/workspace/.omc/research/model-bakeoff-2026-06-15/calibration_results.json","w"),indent=2)
print("\nbands: A=80-100 B=70-79 C=50-69 D=30-49 E=0-29  | order=A>B>C>D>E strictly | inband=#scores in their band | A|A2=consistency gap")
print("saved calibration_results.json")
