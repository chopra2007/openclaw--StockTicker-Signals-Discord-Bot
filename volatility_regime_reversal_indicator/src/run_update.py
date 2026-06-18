"""Refresh the whole data spine, then print a provenance summary.

    python -m src.run_update    (run from the project directory)

Each fetch group is wrapped so one failing series/source doesn't abort the rest.
The summary reads store.provenance(name) for every expected series.
"""
from __future__ import annotations

from .config import get
from .data import fetch_fred, fetch_prices, fetch_vol, store


def _expected_names() -> list[str]:
    names = list(get("data.etfs", []))
    names += list(get("data.vol_indices", {}).keys())
    names += ["BAA10Y"]
    return names


def _run_group(label: str, fn) -> dict[str, bool]:
    print(f"\n=== {label} ===")
    try:
        results = fn()
    except Exception as exc:  # noqa: BLE001 — group-level isolation by design
        print(f"  GROUP FAILED: {type(exc).__name__}: {exc}")
        return {}
    if isinstance(results, bool):
        results = {label: results}
    for name, ok in results.items():
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    return results


def main() -> None:
    # Prices and vol fetch per-series internally; FRED returns a single bool.
    _run_group("ETF prices (yfinance)", fetch_prices.fetch_all_prices)
    _run_group("Vol indices (yfinance)", fetch_vol.fetch_all_vol)
    print("\n=== FRED BAA10Y ===")
    try:
        ok = fetch_fred.fetch_baa10y()
        print(f"  {'OK  ' if ok else 'FAIL'} BAA10Y")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL BAA10Y: {type(exc).__name__}: {exc}")

    # Provenance summary table
    print("\n=== PROVENANCE SUMMARY ===")
    header = f"{'name':<8} {'rows':>7}  {'start':<10} {'end':<10} {'source':<10} adjusted"
    print(header)
    print("-" * len(header))
    for name in _expected_names():
        prov = store.provenance(name)
        if not prov:
            print(f"{name:<8} {'--':>7}  {'MISSING — not in store':<32}")
            continue
        print(
            f"{name:<8} {prov.get('rows', 0):>7}  "
            f"{str(prov.get('start')):<10} {str(prov.get('end')):<10} "
            f"{str(prov.get('source')):<10} {prov.get('adjusted')}"
        )


if __name__ == "__main__":
    main()
