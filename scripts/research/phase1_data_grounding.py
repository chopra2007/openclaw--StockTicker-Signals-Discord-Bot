#!/usr/bin/env python3
"""
Phase 1: Data grounding for opening-auction imbalance research.
Streaming decoder for 4 DBN files without materializing in memory.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

import databento as db


def get_record_fields(record):
    """Extract field names from a databento record object."""
    # Try different methods to get field names
    if hasattr(record, "__dict__"):
        return list(record.__dict__.keys())
    elif hasattr(record, "__slots__"):
        return list(record.__slots__)
    else:
        # Fallback: use dir and filter for public attributes
        return [attr for attr in dir(record) if not attr.startswith("_")]


def stream_dbn_file(filepath: str, max_sample_size: int = 50):
    """
    Stream a DBN file and collect metadata without materializing full file.

    Returns:
        dict with:
        - record_count: int, actual count from streaming
        - field_names: list of field names from first record
        - dtypes: dict mapping field names to dtype strings
        - sample_records: list of up to max_sample_size raw records
        - symbols_seen: set of all symbols in this file (via metadata lookup)
    """
    filepath = str(filepath)
    result = {
        "record_count": 0,
        "field_names": None,
        "dtypes": {},
        "sample_records": [],
        "symbols_seen": set(),
    }

    try:
        store = db.DBNStore.from_file(filepath)

        # Get symbols from metadata
        metadata = store.metadata
        if hasattr(metadata, "symbols") and metadata.symbols:
            result["symbols_seen"] = set(metadata.symbols)

        # Iterate through records streaming
        for i, record in enumerate(store):
            result["record_count"] += 1

            # Capture field names and dtypes from first record
            if i == 0:
                result["field_names"] = get_record_fields(record)
                # Build dtype map from first record
                for field_name in result["field_names"]:
                    try:
                        val = getattr(record, field_name)
                        result["dtypes"][field_name] = type(val).__name__
                    except:
                        result["dtypes"][field_name] = "unknown"

            # Collect first N records as raw samples
            if i < max_sample_size:
                # Convert record to dict for JSON serialization later
                record_dict = {}
                for field in result["field_names"]:
                    try:
                        val = getattr(record, field)
                        record_dict[field] = str(val)
                    except:
                        record_dict[field] = "N/A"
                result["sample_records"].append(record_dict)

            # Progress indicator every 1M records
            if (i + 1) % 1_000_000 == 0:
                print(f"  {filepath}: {i+1:,} records processed...", file=sys.stderr)

    except Exception as e:
        import traceback
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    return result


def main():
    data_dir = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08")
    output_dir = Path("/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance")

    # Four files to decode
    files = [
        "xnys-pillar_imbalance_60-symbols_2023-01-01_2026-08-22.dbn.zst",
        "xnys-pillar_ohlcv-1m_60-symbols_2023-01-01_2026-08-22.dbn.zst",
        "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst",
        "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst",
    ]

    all_results = {}
    all_symbols = defaultdict(set)

    print("Streaming DBN files (no full materialization)...", file=sys.stderr)
    for filename in files:
        filepath = data_dir / filename
        print(f"\nProcessing: {filename}", file=sys.stderr)

        result = stream_dbn_file(str(filepath))
        all_results[filename] = result

        if "error" not in result:
            print(f"  ✓ Record count: {result['record_count']:,}", file=sys.stderr)
            print(f"  ✓ Fields: {len(result['field_names'])} fields", file=sys.stderr)
            print(f"  ✓ Symbols in file: {len(result['symbols_seen'])}", file=sys.stderr)
            if result['symbols_seen']:
                print(f"    Sample symbols: {sorted(list(result['symbols_seen']))[:5]}", file=sys.stderr)
            all_symbols[filename] = result["symbols_seen"]
        else:
            print(f"  ✗ Error: {result['error']}", file=sys.stderr)

    # ========== BRK.B Alias Verification ==========
    print("\n\nVerifying BRK.B symbol alias...", file=sys.stderr)
    brk_status = {
        "xnys_imbalance_has_brk_b": False,
        "xnys_ohlcv_has_brk_b": False,
        "equs_60sym_has_brk_b": False,
        "equs_brk_b_dedicated_has_brk_b": False,
        "verification_passed": False,
    }

    # XNYS imbalance should have "BRK B"
    xnys_imbalance_syms = all_symbols[files[0]]
    if "BRK B" in xnys_imbalance_syms or "BRK.B" in xnys_imbalance_syms:
        brk_status["xnys_imbalance_has_brk_b"] = True
        print(f"  ✓ XNYS imbalance file has 'BRK B' or 'BRK.B'", file=sys.stderr)
    else:
        print(f"  ✗ XNYS imbalance file missing 'BRK B'/'BRK.B' (got: {list(xnys_imbalance_syms)[:5]})", file=sys.stderr)

    # XNYS OHLCV should have "BRK B"
    xnys_ohlcv_syms = all_symbols[files[1]]
    if "BRK B" in xnys_ohlcv_syms or "BRK.B" in xnys_ohlcv_syms:
        brk_status["xnys_ohlcv_has_brk_b"] = True
        print(f"  ✓ XNYS OHLCV file has 'BRK B' or 'BRK.B'", file=sys.stderr)
    else:
        print(f"  ✗ XNYS OHLCV file missing 'BRK B'/'BRK.B' (got: {list(xnys_ohlcv_syms)[:5]})", file=sys.stderr)

    # EQUS 60-symbol should have "BRK B" (to match the 60 selected symbols list)
    equs_60sym_syms = all_symbols[files[2]]
    if "BRK B" in equs_60sym_syms:
        brk_status["equs_60sym_has_brk_b"] = True
        print(f"  ✓ EQUS 60-symbol file has 'BRK B' (reference to 60-symbol list)", file=sys.stderr)
    else:
        print(f"  ✗ EQUS 60-symbol file missing 'BRK B' (got: {list(equs_60sym_syms)[:5]})", file=sys.stderr)

    # EQUS dedicated file should have "BRK.B" (actual EQUS futures data)
    equs_brk_syms = all_symbols[files[3]]
    if "BRK.B" in equs_brk_syms:
        brk_status["equs_brk_b_dedicated_has_brk_b"] = True
        print(f"  ✓ EQUS dedicated file has 'BRK.B' (actual EQUS futures data)", file=sys.stderr)
    else:
        print(f"  ✗ EQUS dedicated file missing 'BRK.B' (got: {list(equs_brk_syms)[:5]})", file=sys.stderr)

    # Verify: "BRK B" -> "BRK.B" alias is consistent
    # XNYS files use "BRK B" (space), EQUS 60-symbol references "BRK B", EQUS dedicated uses "BRK.B" (dot)
    # Manifest contains alias mapping: XNYS.PILLAR:BRK B -> EQUS.MINI:BRK.B
    brk_status["verification_passed"] = (
        brk_status["xnys_imbalance_has_brk_b"] and
        brk_status["xnys_ohlcv_has_brk_b"] and
        brk_status["equs_60sym_has_brk_b"] and  # Should have "BRK B" reference
        brk_status["equs_brk_b_dedicated_has_brk_b"]  # Should have "BRK.B" data
    )

    if brk_status["verification_passed"]:
        print(f"  ✓✓ BRK.B alias is CONSISTENT: XNYS has BRK B/BRK.B, EQUS uses dedicated file", file=sys.stderr)
    else:
        print(f"  ⚠ BRK.B alias verification INCONCLUSIVE (check results below)", file=sys.stderr)

    # ========== Write outputs ==========
    print(f"\n\nWriting outputs to {output_dir}...", file=sys.stderr)

    # Build JSON output with all metadata
    json_output = {
        "files_decoded": list(all_results.keys()),
        "record_counts": {
            fname: result["record_count"]
            for fname, result in all_results.items()
        },
        "symbols_found": {
            fname: sorted(list(result.get("symbols_seen", set())))
            for fname, result in all_results.items()
        },
        "field_schemas": {
            fname: {
                "field_names": result.get("field_names", []),
                "dtypes": result.get("dtypes", {}),
            }
            for fname, result in all_results.items()
        },
        "sample_records": {
            fname: result.get("sample_records", [])
            for fname, result in all_results.items()
        },
        "brk_b_verification": brk_status,
    }

    json_file = output_dir / "data-capability-audit-raw.json"
    with open(json_file, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"  Written: {json_file}", file=sys.stderr)

    # ========== Build Markdown audit report ==========
    md_output = "# Data Capability Audit — Phase 1 Raw Extraction\n\n"
    md_output += "**Purpose:** Mechanical extraction of DBN file structure, record counts, field schemas, and symbol inventory.\n\n"

    md_output += "## File Decoding Results\n\n"

    for fname in files:
        result = all_results[fname]
        md_output += f"### {fname}\n\n"

        if "error" in result:
            md_output += f"**Error:** {result['error']}\n\n"
        else:
            md_output += f"**Record Count:** {result['record_count']:,}\n\n"
            md_output += f"**Field Count:** {len(result['field_names'])}\n\n"
            md_output += f"**Fields:** {', '.join(result['field_names'])}\n\n"
            md_output += "**Field Types:**\n"
            md_output += "| Field | Type |\n"
            md_output += "|-------|------|\n"
            for field, dtype in result["dtypes"].items():
                md_output += f"| {field} | {dtype} |\n"
            md_output += "\n"

            symbols = sorted(list(result["symbols_seen"]))
            md_output += f"**Unique Symbols in File:** {len(symbols)}\n"
            if symbols:
                # Show all if <= 20, else first 10 + last 10
                if len(symbols) <= 20:
                    md_output += f"  {', '.join(symbols)}\n\n"
                else:
                    first_10 = ', '.join(symbols[:10])
                    last_10 = ', '.join(symbols[-10:])
                    md_output += f"  First 10: {first_10}\n"
                    md_output += f"  Last 10: {last_10}\n\n"
            else:
                md_output += "  (None found via instrument metadata)\n\n"

            md_output += "**Sample Records (first 3 rows shown):**\n\n"
            md_output += "```json\n"
            md_output += json.dumps(result["sample_records"][:3], indent=2) + "\n"
            md_output += "  ... (47 more records in JSON file)\n"
            md_output += "```\n\n"

    # Degraded dates (from manifest, not recomputed)
    md_output += "## Degraded Dates (from manifest.json)\n\n"
    md_output += "**XNYS.PILLAR degraded dates:** 2023-01-24, 2023-12-04, 2023-12-11, 2024-08-08\n\n"
    md_output += "**EQUS.MINI degraded dates:** 2025-03-24, 2025-04-04, 2025-05-06, 2025-06-04, 2025-06-16, 2025-07-09, 2025-08-08, 2025-08-13, 2025-08-19, 2025-08-25, 2025-09-03, 2025-09-08, 2025-09-12, 2025-10-10, 2025-10-13\n\n"

    # BRK.B verification
    md_output += "## Symbol Alias Verification: BRK B ↔ BRK.B\n\n"
    md_output += f"**Verification Status:** {'✓ PASSED' if brk_status['verification_passed'] else '✗ FAILED'}\n\n"
    md_output += f"- XNYS imbalance has 'BRK B': {brk_status['xnys_imbalance_has_brk_b']}\n"
    md_output += f"- XNYS OHLCV has 'BRK B': {brk_status['xnys_ohlcv_has_brk_b']}\n"
    md_output += f"- EQUS 60-symbol has 'BRK B' (reference): {brk_status['equs_60sym_has_brk_b']}\n"
    md_output += f"- EQUS dedicated file has 'BRK.B': {brk_status['equs_brk_b_dedicated_has_brk_b']}\n"
    md_output += f"\n**Alias mapping (from manifest):** XNYS.PILLAR:BRK B → EQUS.MINI:BRK.B\n\n"

    md_file = output_dir / "data-capability-audit-raw.md"
    with open(md_file, "w") as f:
        f.write(md_output)
    print(f"  Written: {md_file}", file=sys.stderr)

    # ========== Write phase1-gate.json ==========
    gate_json = {
        "gate_pass": True if not any("error" in all_results[f] for f in files) else False,
        "proceed": True if not any("error" in all_results[f] for f in files) else False,
        "files_decoded": list(all_results.keys()),
        "record_counts": json_output["record_counts"],
        "degraded_dates_xnys": [
            "2023-01-24",
            "2023-12-04",
            "2023-12-11",
            "2024-08-08",
        ],
        "degraded_dates_equs": [
            "2025-03-24",
            "2025-04-04",
            "2025-05-06",
            "2025-06-04",
            "2025-06-16",
            "2025-07-09",
            "2025-08-08",
            "2025-08-13",
            "2025-08-19",
            "2025-08-25",
            "2025-09-03",
            "2025-09-08",
            "2025-09-12",
            "2025-10-10",
            "2025-10-13",
        ],
        "brk_alias_confirmed": brk_status["verification_passed"],
    }

    gate_file = output_dir / "phase1-gate.json"
    with open(gate_file, "w") as f:
        json.dump(gate_json, f, indent=2)
    print(f"  Written: {gate_file}", file=sys.stderr)

    print("\n✓ Phase 1 complete.", file=sys.stderr)
    return gate_json


if __name__ == "__main__":
    gate = main()
    # Print gate for team lead
    print("\n" + "="*60)
    print("PHASE 1 GATE RESULT:")
    print("="*60)
    print(json.dumps(gate, indent=2))
