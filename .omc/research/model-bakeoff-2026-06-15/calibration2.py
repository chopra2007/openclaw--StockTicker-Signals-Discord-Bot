#!/usr/bin/env python3
"""Expanded text-scorer calibration (2026-06-16) — 9 scenarios, finer tiers.

Ranks candidates for the text chain's FRONT-LINE scorer by ORDERING QUALITY
(pairwise inversions on an intended strength rank S1>...>S9), band adherence,
self-consistency, spread, then price. Same real _SYSTEM_PROMPT from llm_scorer.py.
"""
import json, time, urllib.request, urllib.error, socket
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

API="https://openrouter.ai/api/v1/chat/completions"
KEY=None
for p in ("/root/.openclaw/.env.service","/root/.openclaw/.env",
          "/home/openclaw/.openclaw/.env.service","/home/openclaw/.openclaw/.env"):
    try:
        for ln in open(p):
            if ln.startswith("OPENROUTER_API_KEY="): KEY=ln.split("=",1)[1].strip().strip('"').strip("'"); break
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

def tech(price,chg,passes,total,lines):
    s=f"\nTECHNICAL DATA:\n- Price: ${price} ({chg})\n"
    for l in lines: s+=f"  {l}\n"
    s+=f"- Filters passed: {passes}/{total}\n"; return s

# 9 scenarios, intended strength DESCENDING S1..S9. band = guideline band.
SCEN=[
 ("S1",(80,100),"Evaluate breakout potential for $AMD:\n\nTWITTER/X SIGNALS:\n- 6 analysts within 18 min\n  > \"MI400 launch is huge, loading calls target 210\"\n\nSEC/EDGAR FILINGS:\n- Form 4: CEO bought 50,000 shares at 176\n\nNEWS CATALYST:\n- Type: earnings_beat; beat EPS 8.2%, raised guidance; Sources: Reuters, Bloomberg, CNBC; confidence 92%\n"+tech("178.45","+4.1%",6,6,["[PASS] RSI 61 (<70)","[PASS] Vol 2.3x (>1.5x)","[PASS] EMA9>EMA21","[PASS] breakout > resistance 176"])),
 ("S2",(80,100),"Evaluate breakout potential for $MSFT:\n\nTWITTER/X SIGNALS:\n- 5 analysts within 25 min\n  > \"Azure reaccelerating, breaking out\"\n\nNEWS CATALYST:\n- Type: guidance_raise; raised FY cloud guidance; Sources: Bloomberg, CNBC; confidence 80%\n"+tech("415.2","+2.6%",5,6,["[PASS] RSI 64 (<70)","[PASS] Vol 1.9x (>1.5x)","[PASS] EMA9>EMA21","[FAIL] new 52w high","[PASS] breakout > resistance"])),
 ("S3",(70,79),"Evaluate breakout potential for $SOFI:\n\nTWITTER/X SIGNALS:\n- 3 analysts within 35 min\n  > \"member growth strong, watching over 12\"\n\nNEWS CATALYST:\n- Type: analyst_upgrade; Morgan Stanley overweight PT 14; Sources: Benzinga, MarketWatch; confidence 70%\n"+tech("11.40","+2.0%",4,6,["[PASS] RSI 58 (<70)","[PASS] Vol 1.7x (>1.5x)","[FAIL] EMA9>EMA21","[PASS] breakout > resistance"])),
 ("S4",(50,69),"Evaluate breakout potential for $UBER:\n\nTWITTER/X SIGNALS:\n- 3 analysts within 45 min\n  > \"mobility numbers solid, could run\"\n\nNEWS CATALYST:\n- Type: analyst_note; mixed sell-side commentary; Sources: Seeking Alpha; confidence 55%\n"+tech("71.3","+1.2%",3,6,["[PASS] RSI 57 (<70)","[FAIL] Vol 1.2x (>1.5x)","[PASS] EMA9>EMA21","[FAIL] breakout > resistance"])),
 ("S5",(50,69),"Evaluate breakout potential for $PLTR:\n\nTWITTER/X SIGNALS:\n- 2 analysts within 50 min\n  > \"maybe setting up, not sure yet\"\n\nNEWS CATALYST:\n- Type: rumor; unconfirmed contract chatter; Sources: Reddit; confidence 35%\n"+tech("24.10","+0.6%",3,6,["[PASS] RSI 55 (<70)","[FAIL] Vol 1.1x (>1.5x)","[FAIL] EMA9>EMA21","[PASS] price > 50d MA"])),
 ("S6",(30,49),"Evaluate breakout potential for $F:\n\nTWITTER/X SIGNALS:\n- 2 analysts within 55 min\n  > \"watching for a bounce\"\n\nNo news catalyst found.\n"+tech("11.9","-0.3%",2,6,["[FAIL] RSI 48","[FAIL] Vol 0.9x (>1.5x)","[PASS] EMA9>EMA21","[PASS] price > 50d MA"])),
 ("S7",(30,49),"Evaluate breakout potential for $GME:\n\nTWITTER/X SIGNALS:\n- 4 retail accounts within 25 min\n  > \"squeeze incoming!! buy now\" > \"to the moon\"\n\nNo news catalyst found.\n"+tech("21.3","-2.4%",1,6,["[FAIL] RSI 74 (<70)","[PASS] Vol 3.0x (>1.5x)","[FAIL] EMA9>EMA21","[FAIL] breakout (rejected)"])),
 ("S8",(0,29),"Evaluate breakout potential for $BBBYQ:\n\nTWITTER/X SIGNALS:\n- 1 mention within 60 min\n  > \"cant believe how cheap this is, lotto\"\n\nNo news catalyst. Conflicting signals (delisting risk).\n"+tech("0.32","-8%",1,6,["[FAIL] RSI 33","[PASS] Vol 5x","[FAIL] EMA9>EMA21","[FAIL] downtrend"])),
 ("S9",(0,29),"Evaluate breakout potential for $XYZ:\n\nTWITTER/X SIGNALS:\n- 1 mention within 60 min\n  > \"🚀🚀 $XYZ TO THE MOON 1000% GUARANTEED BUY NOW 🚀🚀\"\n\nNo catalyst.\n"+tech("0.84","+38%",1,6,["[FAIL] RSI 91 (<70)","[PASS] Vol 12x","[FAIL] EMA9>EMA21","[FAIL] vertical spike unsustainable"])),
]
RANK={k:i for i,(k,_,_) in enumerate(SCEN)}  # 0=strongest

MODELS=["openai/gpt-4.1-nano","qwen/qwen3-235b-a22b-2507","google/gemma-3-27b-it",
        "mistralai/mistral-nemo","inclusionai/ling-2.6-flash"]

def score(model,user):
    body={"model":model,"messages":[{"role":"system","content":SYS},{"role":"user","content":user}],"max_tokens":1024,"temperature":0.3}
    req=urllib.request.Request(API,data=json.dumps(body).encode(),headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    t=time.time()
    try:
        j=json.loads(urllib.request.urlopen(req,timeout=45).read()); el=time.time()-t
        msg=(j.get("choices") or [{}])[0].get("message") or {}
        c=(msg.get("content") or "").strip(); u=j.get("usage") or {}
        pin,pout=PRICE.get(model,(0,0)); cost=(u.get("prompt_tokens",0)*pin+u.get("completion_tokens",0)*pout)/1e6
        cc=c
        if cc.startswith("```"):
            import re; cc=re.sub(r'^```(?:json)?\s*','',cc); cc=re.sub(r'\s*```$','',cc)
        conf=None
        try: conf=float(json.loads(cc).get("confidence"))
        except Exception:
            import re; mm=re.search(r'"?confidence"?\s*:\s*(\d+)',cc)
            if mm: conf=float(mm.group(1))
        return dict(conf=conf,lat=round(el,2),cost=round(cost,6))
    except Exception as e:
        return dict(conf=None,lat=round(time.time()-t,2),cost=0,err=str(type(e).__name__))

def run_model(model):
    res={}
    for k,_,u in SCEN: res[k]=score(model,u)
    res["S1b"]=score(model,SCEN[0][2]); res["S5b"]=score(model,SCEN[4][2]); res["S9b"]=score(model,SCEN[8][2])
    return model,res

R={}
with ThreadPoolExecutor(max_workers=5) as ex:
    for m,res in ex.map(run_model,MODELS): R[m]=res

bands={k:b for k,b,_ in SCEN}
print(f"{'model':32} "+ " ".join(f"{k:>4}" for k,_,_ in SCEN) + "  inv inband  cons  spread  $out  $run")
summ={}
for model in MODELS:
    r=R[model]; cs={k:r[k]["conf"] for k,_,_ in SCEN}
    inv=0; comp=0
    for a,b in combinations([k for k,_,_ in SCEN],2):
        if cs[a] is None or cs[b] is None: continue
        comp+=1
        # a is stronger than b (lower RANK index) -> expect cs[a] > cs[b]
        if RANK[a]<RANK[b] and cs[a]<cs[b]: inv+=1
        if RANK[a]>RANK[b] and cs[a]>cs[b]: inv+=1
    inband=sum(1 for k,_,_ in SCEN if cs[k] is not None and bands[k][0]<=cs[k]<=bands[k][1])
    cons=[]
    for k,kb in [("S1","S1b"),("S5","S5b"),("S9","S9b")]:
        if r[k]["conf"] is not None and r[kb]["conf"] is not None: cons.append(abs(r[k]["conf"]-r[kb]["conf"]))
    consavg=round(sum(cons)/len(cons),1) if cons else None
    spread=(cs["S1"]-cs["S9"]) if (cs["S1"] is not None and cs["S9"] is not None) else None
    pout=PRICE.get(model,(0,0))[1]
    runcost=sum(r[k]["cost"] for k in r)
    def fmt(x): return f"{int(x):>4}" if x is not None else "  na"
    print(f"{model:32} "+" ".join(fmt(cs[k]) for k,_,_ in SCEN)+
          f"  {inv:>2}/{comp}  {inband}/9   {str(consavg):>4}  {str(spread):>4}  {pout:>4}  ${runcost:.4f}")
    summ[model]=dict(scores=cs,inversions=inv,comparisons=comp,inband=inband,consistency=consavg,spread=spread,price_out=pout,run_cost=round(runcost,5))
json.dump({"summary":summ,"raw":R,"bands":bands,"intended_rank":[k for k,_,_ in SCEN]},
          open("/home/openclaw/.openclaw/workspace/.omc/research/model-bakeoff-2026-06-15/calibration2_results.json","w"),indent=2)
print("\nintended strength rank S1>S2>...>S9 | inv=pairwise inversions (lower=better) | inband=#in guideline band | cons=avg repeat gap | $out=$/M out")
print("saved calibration2_results.json")
