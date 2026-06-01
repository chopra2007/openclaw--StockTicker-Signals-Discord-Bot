#!/usr/bin/env python3
"""Cross-model adversarial review of final-plan.md via Gemini (codex substitute — codex is down).
Throwaway probe; lives in run dir, not committed."""
import os, sys
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.openclaw/.env"))
key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY2")
if not key:
    print("NO_GEMINI_KEY"); sys.exit(2)

def rd(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception as e:
        return f"(could not read {p}: {e})"

plan = rd(".claude/discover/wolf-news-brain/final-plan.md")
spec = rd("todo/wolf-macro-brain.md")
p3 = rd(".claude/discover/wolf-news-brain/pass-3-stress-tested.md")

PROMPT = f"""You are an adversarial senior engineer reviewing a BUILD PLAN before code is written, for a production Python stock-signal Discord bot (asyncio, SQLite). Be skeptical and concrete. Do NOT rubber-stamp.

The plan already had a deep local critic+security pass; their findings are summarized in PASS-3 below. Do not just repeat those — find what is STILL wrong, missing, risky, or OVER-ENGINEERED. This is a non-coder's solo project, so "simplest thing that works for a first live #news lane" matters.

Give your output as a prioritized list: BLOCKER / MAJOR / MINOR / SIMPLIFY — each with the concrete issue and a specific fix or simplification. Then one final line: VERDICT: BUILD-READY  or  VERDICT: REVISE (must-fix: ...).

Focus on: (1) correctness of the architecture vs an asyncio+SQLite engine; (2) is the v1 scope too ambitious — should the confluence engine or beneficiary inference be deferred so a thin reader→thesis→#news lane ships first and is verifiable? (3) any new production-safety or data-quality risk the critic missed; (4) whether the phase sequencing hides a late risk.

=== PRODUCT SPEC ===
{spec}

=== PASS-3 (already-found issues; don't just repeat) ===
{p3}

=== THE PLAN UNDER REVIEW ===
{plan}
"""

from google import genai
client = genai.Client(api_key=key)
for m in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-pro"]:
    try:
        resp = client.models.generate_content(model=m, contents=PROMPT)
        print(f"===== GEMINI REVIEW (model={m}) =====\n")
        print((resp.text or "").strip())
        break
    except Exception as e:
        print(f"[model={m}] ERROR: {type(e).__name__}: {str(e)[:200]}")
print("\nREVIEW_DONE")
