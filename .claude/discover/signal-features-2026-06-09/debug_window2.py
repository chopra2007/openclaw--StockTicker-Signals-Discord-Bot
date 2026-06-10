#!/usr/bin/env python3
"""Debug: what happened to window 2 in the chunked run?
Call _extract_evidence_single_pass directly for window 2 (870–1770s) with verbose output.
1 Gemini call.
"""
import asyncio, os, sys

_env_path = "/root/.openclaw/.env"
with open(_env_path) as f:
    for line in f:
        line = line.strip()
        if line.startswith("export "): line = line[7:]
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, "/home/openclaw/.openclaw/workspace")
os.environ.setdefault("CONSENSUS_CONFIG", "/home/openclaw/.openclaw/workspace/config/consensus.yaml")

async def main():
    from consensus_engine.analysis.gemini_video_parser import _extract_evidence_single_pass
    import logging
    logging.basicConfig(level=logging.INFO)

    print("Calling window 2: start_offset=870s end_offset=1770s")
    bundle, tel = await _extract_evidence_single_pass(
        "e_iCwe2yX14", "LiveStream", "2026-06-10T00:00:00Z",
        media_resolution="low",
        start_offset_sec=870,
        end_offset_sec=1770,
    )
    print(f"\nResult: bundle={'None' if bundle is None else 'OK'}")
    print(f"Telemetry: json_parse_ok={tel.json_parse_ok}, span_count={tel.span_count}")
    print(f"Tokens: input={tel.input_tokens}, output={tel.output_tokens}")
    print(f"f2_failure_category={tel.f2_failure_category}")
    if bundle:
        print(f"Spans: {len(bundle.spans)}")
        for s in bundle.spans[:5]:
            print(f"  @{s.ts_sec}s: {s.quote[:80]!r}")
        print(f"duration_sec reported by Gemini: {bundle.duration_sec}")

if __name__ == "__main__":
    asyncio.run(main())
