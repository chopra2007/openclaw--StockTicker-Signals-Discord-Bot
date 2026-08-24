"""Safety tests for the TODO #93 auction-pressure research scripts.

These fail if a research script could spend money, read a paid-data API key,
reach the network, or write outside the allowed research paths.
"""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO / "scripts" / "research"

# The scripts this plan is allowed to add.
SCRIPT_GLOBS = ["auction_pressure_*.py", "check_auction_pressure_gate.py"]

ALLOWED_WRITE_ROOTS = [
    str(REPO / ".omc" / "research" / "opening-auction-pressure-response"),
    str(REPO / "scripts" / "research"),
    str(REPO / "tests" / "research"),
]

READ_ONLY_DATA_ROOTS = [
    "/home/openclaw/.openclaw/research-data/databento/opening-auctions",
    str(REPO / ".omc" / "research" / "opening-auction-imbalance"),
]

# Anything that could reach a paid endpoint or read a key.
FORBIDDEN_PATTERNS = [
    (r"\bHistorical\s*\(", "instantiates an online Databento Historical client"),
    (r"\bLive\s*\(", "instantiates an online Databento Live client"),
    (r"DATABENTO_API_KEY", "reads the Databento API key"),
    (r"\bos\.environ\b", "reads environment variables"),
    (r"\bgetenv\s*\(", "reads environment variables"),
    (r"\.timeseries\b", "uses the Databento timeseries (paid download) API"),
    (r"\bbatch\.submit_job\b", "submits a paid Databento batch job"),
    (r"\bfrom_dbn_url\s*\(", "reads DBN over the network"),
    (r"\bimport\s+requests\b", "imports a network HTTP client"),
    (r"\bimport\s+httpx\b", "imports a network HTTP client"),
    (r"\bimport\s+aiohttp\b", "imports a network HTTP client"),
    (r"\bimport\s+urllib\b", "imports a network HTTP client"),
    (r"\bmetadata\.get_cost\b", "requests an online cost estimate"),
]

PATH_LITERAL = re.compile(r"['\"](/[A-Za-z0-9_.\-/]{4,})['\"]")


def research_scripts():
    found = []
    for pattern in SCRIPT_GLOBS:
        found.extend(sorted(SCRIPT_DIR.glob(pattern)))
    return found


def test_at_least_one_research_script_exists():
    assert research_scripts(), (
        "no auction-pressure research script found; the safety tests would "
        "otherwise pass vacuously"
    )


@pytest.mark.parametrize("script", research_scripts(), ids=lambda p: p.name)
def test_script_has_no_paid_or_network_access(script):
    text = script.read_text()
    for pattern, why in FORBIDDEN_PATTERNS:
        assert re.search(pattern, text) is None, f"{script.name} {why}"


@pytest.mark.parametrize("script", research_scripts(), ids=lambda p: p.name)
def test_script_only_reads_local_dbn_files(script):
    text = script.read_text()
    if "DBNStore" in text:
        assert "DBNStore.from_file" in text, (
            f"{script.name} uses DBNStore without from_file"
        )


@pytest.mark.parametrize("script", research_scripts(), ids=lambda p: p.name)
def test_script_paths_stay_inside_allowed_roots(script):
    text = script.read_text()
    allowed = ALLOWED_WRITE_ROOTS + READ_ONLY_DATA_ROOTS
    for match in PATH_LITERAL.finditer(text):
        path = match.group(1)
        if path.startswith("/usr/") or path.startswith("/bin/"):
            continue  # shebang-style interpreter paths
        assert any(path.startswith(root) for root in allowed), (
            f"{script.name} references {path}, which is outside the allowed "
            f"research paths"
        )


@pytest.mark.parametrize("script", research_scripts(), ids=lambda p: p.name)
def test_script_never_names_a_network_or_spend_capable_symbol(script):
    """Scan the parsed code for any name that could reach the network or spend
    money. This reads the code rather than running it: these scripts do real
    work at module level, and a test must never regenerate research evidence.
    """
    tree = ast.parse(script.read_text(), filename=str(script))
    banned = {
        "socket", "create_connection", "urlopen", "Request", "Session",
        "Historical", "Live", "timeseries", "submit_job", "get_cost",
        "from_dbn_url", "environ", "getenv", "putenv",
    }
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in banned:
            hits.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in banned:
            hits.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or ""
            names = [a.name for a in node.names]
            for candidate in [mod] + names:
                root = candidate.split(".")[0]
                if root in banned:
                    hits.add(root)
    assert not hits, f"{script.name} references {sorted(hits)}"


@pytest.mark.parametrize("script", research_scripts(), ids=lambda p: p.name)
def test_script_reads_dbn_only_from_a_local_file(script):
    """Every Databento read must be DBNStore.from_file against a local path."""
    tree = ast.parse(script.read_text(), filename=str(script))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr.startswith("from_") and "DBN" in ast.dump(node.func):
                assert node.func.attr == "from_file", (
                    f"{script.name} opens DBN data with {node.func.attr}, not from_file"
                )
