#!/usr/bin/env python3
"""Cheap, fair model bake-off harness — 2026-06-15.

Usage:  python harness.py <model_id> <usecase>   where usecase in {text, primary, agent}

Runs FIXED prompts per use case (identical across models = fair) with SMALL token
caps and few calls (cheap). Prints one JSON blob to stdout: per-call status,
latency, content/reasoning lengths, usage, computed $ cost, and the live
/models metadata (price, context, max_completion_tokens, tools, reasoning).

Profiles mirror production:
  text    = !all narrator sanitize (max_tokens=512, 5s = THE decider) + a JSON
            scorer call + a 3x concurrency burst. Scorer 8k-floor checked via
            metadata max_completion_tokens (no need to GENERATE 8k tokens).
  primary = financial narrative synthesis (1 call, full content captured for
            quality judging) + 3x concurrency burst.
  agent   = tool-calling under tool_choice='auto' with a ~4k-token agent-style
            system prompt (PROXY for the real 25-50k path, to stay cheap) +
            instruction-follow/no-leak check + 2x concurrency. Context window
            for the real 50k path is checked via metadata, not generated.
"""
import json, sys, time, socket, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

MODEL = sys.argv[1]
USECASE = sys.argv[2]
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- key ---
KEY = None
for p in ("/root/.openclaw/.env.service", "/root/.openclaw/.env",
          "/home/openclaw/.openclaw/.env.service", "/home/openclaw/.openclaw/.env"):
    try:
        for line in open(p):
            if line.startswith("OPENROUTER_API_KEY="):
                KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
    except Exception:
        pass
    if KEY:
        break
assert KEY, "no OPENROUTER_API_KEY found"

# --- live metadata (pricing/caps) ---
META = {}
try:
    cat = json.load(open("/tmp/or_models_20260615.json"))["data"]
    for m in cat:
        if m["id"] == MODEL:
            pr = m.get("pricing") or {}
            def ff(x):
                try: return float(x)
                except: return 0.0
            tp = m.get("top_provider") or {}
            params = m.get("supported_parameters") or []
            META = dict(pin=ff(pr.get("prompt")) * 1e6, pout=ff(pr.get("completion")) * 1e6,
                        ctx=m.get("context_length"), maxc=tp.get("max_completion_tokens"),
                        tools=("tools" in params),
                        reasoning=("reasoning" in params or "include_reasoning" in params),
                        modality=(m.get("architecture") or {}).get("modality"))
            break
except Exception as e:
    META = {"meta_error": str(e)}

PIN = META.get("pin") or 0.0
POUT = META.get("pout") or 0.0


def call(messages, max_tokens, timeout, tools=None, tool_choice=None, temperature=0.3):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    data = json.dumps(body).encode()
    req = urllib.request.Request(API_URL, data=data, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
        "HTTP-Referer": "https://bakeoff.local", "X-Title": "bakeoff"})
    t = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        el = time.time() - t
        j = json.loads(resp.read())
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        usage = j.get("usage") or {}
        ctd = usage.get("completion_tokens_details") or {}
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        ptok = usage.get("prompt_tokens", 0); ctok = usage.get("completion_tokens", 0)
        cost = (ptok * PIN + ctok * POUT) / 1e6
        return dict(status=200, latency=round(el, 2), finish=ch.get("finish_reason"),
                    content_len=len(content), content_head=content[:600],
                    reasoning_len=len(msg.get("reasoning") or ""),
                    reasoning_tokens=ctd.get("reasoning_tokens"),
                    tool_calls=[{"name": (tc.get("function") or {}).get("name"),
                                 "args_head": ((tc.get("function") or {}).get("arguments") or "")[:120]}
                                for tc in tool_calls],
                    prompt_tokens=ptok, completion_tokens=ctok, cost_usd=round(cost, 6))
    except urllib.error.HTTPError as e:
        el = time.time() - t
        return dict(status=e.code, latency=round(el, 2), error=e.read()[:300].decode("utf-8", "replace"))
    except (socket.timeout, TimeoutError):
        return dict(status=0, latency=round(time.time() - t, 2), error="TimeoutError")
    except Exception as e:
        return dict(status=-1, latency=round(time.time() - t, 2), error=f"{type(e).__name__}: {e}"[:300])


OUT = {"model": MODEL, "usecase": USECASE, "meta": META, "calls": {}}

# ---------------- TEXT ----------------
if USECASE == "text":
    SANITIZE = [{"role": "system", "content":
        "You sanitize Discord stock-alert snippets. For EACH numbered snippet: remove @everyone/@here "
        "and markdown links, KEEP every ticker, price and number exactly, keep it under 300 chars. "
        "Return ONLY a numbered list, same count, same order."},
        {"role": "user", "content":
        "1. @everyone $AMD ripping to $178.45, breakout above [resistance](https://x.com/foo) target $192, "
        "data-center rev +73% YoY!!!\n"
        "2. @here $NVDA watching 250 reclaim, see [chart](https://t.co/bar), might add, stop 232."}]
    SCORER = [{"role": "system", "content":
        "Score the stock signal 0-100 for bullish conviction. Return ONLY raw JSON "
        '{"ticker":"","score":0,"direction":"bullish|bearish|neutral","rationale":""}'},
        {"role": "user", "content": "Tweet: 'Watching $NVDA, might add if it reclaims 250.'"}]
    OUT["calls"]["liveness"] = call([{"role": "user", "content": "Reply with exactly: PONG"}], 10, 15)
    OUT["calls"]["tight512_a"] = call(SANITIZE, 512, 5)
    OUT["calls"]["tight512_b"] = call(SANITIZE, 512, 5)
    OUT["calls"]["scorer"] = call(SCORER, 400, 30)
    with ThreadPoolExecutor(max_workers=3) as ex:
        burst = list(ex.map(lambda _: call(SANITIZE, 300, 8), range(3)))
    OUT["calls"]["concurrency_3x"] = burst
    OUT["scorer_floor_ok"] = (META.get("maxc") is None) or (META.get("maxc", 0) >= 8000)

# ---------------- PRIMARY ----------------
elif USECASE == "primary":
    SYNTH = [{"role": "system", "content":
        "You are a financial analyst writing a concise alert narrative. Given the computed signal data, "
        "write 3-5 short paragraphs: (1) opening thesis with price & direction, (2) ## Catalysts, "
        "(3) ## Risks, (4) a one-line trade plan. Be specific, use the numbers, no disclaimer."},
        {"role": "user", "content":
        "Ticker: AMD. Price $178.45. Signal: BULLISH, confidence MEDIUM. Catalysts: data-center revenue "
        "+73% YoY; new MI400 launch; analyst PT raised to $210. Risks: high valuation (38x fwd); export "
        "controls; broad-market drawdown. Levels: support $172, resistance $185, target $192."}]
    OUT["calls"]["liveness"] = call([{"role": "user", "content": "Reply with exactly: PONG"}], 10, 15)
    OUT["calls"]["synthesis"] = call(SYNTH, 1200, 50)
    with ThreadPoolExecutor(max_workers=3) as ex:
        burst = list(ex.map(lambda _: call(SYNTH, 900, 50), range(3)))
    OUT["calls"]["concurrency_3x"] = burst

# ---------------- AGENT ----------------
elif USECASE == "agent":
    # ~4k-token agent-style system prompt (PROXY for the real 25-50k path; full
    # context-window fitness is checked via META['ctx'], not generated).
    pad = ("You are the StockTicker Discord assistant. You answer user questions about stocks, "
           "markets, and the bot's own signals. You have tools; PREFER calling a tool over guessing "
           "when a question needs live data. Never fabricate a price or a filing. Cite the source. "
           "Keep answers short and plain. ") * 60
    TOOLS = [
        {"type": "function", "function": {"name": "get_stock_quote",
            "description": "Get the current price and day change for a stock ticker.",
            "parameters": {"type": "object", "properties": {
                "ticker": {"type": "string", "description": "e.g. AAPL"}}, "required": ["ticker"]}}},
        {"type": "function", "function": {"name": "search_web",
            "description": "Search the web for recent news about a company or topic.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"]}}},
    ]
    SYS = {"role": "system", "content": pad}
    TOOLQ = [SYS, {"role": "user", "content": "What's the current price of AAPL right now?"}]
    INSTRQ = [SYS, {"role": "user", "content": "In one short sentence, what do you do?"}]
    OUT["calls"]["tool_call"] = call(TOOLQ, 300, 40, tools=TOOLS, tool_choice="auto")
    OUT["calls"]["instruction_follow"] = call(INSTRQ, 200, 40, tools=TOOLS, tool_choice="auto")
    with ThreadPoolExecutor(max_workers=2) as ex:
        burst = list(ex.map(lambda _: call(TOOLQ, 300, 40, tools=TOOLS, tool_choice="auto"), range(2)))
    OUT["calls"]["concurrency_2x"] = burst
    OUT["ctx_holds_50k"] = bool(META.get("ctx") and META["ctx"] >= 128000)

else:
    OUT["error"] = f"unknown usecase {USECASE}"

# total spend this run
tot = 0.0
for v in OUT["calls"].values():
    if isinstance(v, dict):
        tot += v.get("cost_usd") or 0.0
    elif isinstance(v, list):
        for c in v:
            tot += (c or {}).get("cost_usd") or 0.0
OUT["total_cost_usd"] = round(tot, 6)
print(json.dumps(OUT, indent=2))
