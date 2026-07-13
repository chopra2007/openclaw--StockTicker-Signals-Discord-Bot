"""#59: the AI half of the CI auto-fixer — parsing, edit safety, path gates.

Nothing here calls a model. What is tested is the part that decides whether a
model's output is allowed to touch the repo.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ci_ai_fixer", Path(__file__).resolve().parent.parent / "scripts" / "ci_ai_fixer.py")
fixer = importlib.util.module_from_spec(_SPEC)
sys.modules["ci_ai_fixer"] = fixer
_SPEC.loader.exec_module(fixer)


# --- response parsing -------------------------------------------------------

def test_parses_a_plain_json_object():
    out = fixer.parse_response('{"classification": "flaky", "reason": "network"}')
    assert out["classification"] == "flaky"
    assert out["edits"] == []


def test_strips_a_markdown_fence():
    out = fixer.parse_response('```json\n{"classification": "flaky"}\n```')
    assert out["classification"] == "flaky"


def test_recovers_json_buried_in_prose():
    out = fixer.parse_response('Sure!\n{"classification": "real_logic_bug", "edits": []}\nHope that helps.')
    assert out["classification"] == "real_logic_bug"


def test_rejects_an_unknown_classification():
    with pytest.raises(fixer.FixerError, match="classification"):
        fixer.parse_response('{"classification": "vibes"}')


def test_rejects_a_missing_classification():
    with pytest.raises(fixer.FixerError, match="classification"):
        fixer.parse_response('{"reason": "dunno"}')


def test_rejects_unparseable_output():
    with pytest.raises(fixer.FixerError):
        fixer.parse_response("I could not figure it out, sorry.")


def test_rejects_edits_that_are_not_a_list():
    with pytest.raises(fixer.FixerError, match="list"):
        fixer.parse_response('{"classification": "real_logic_bug", "edits": {"a": 1}}')


# --- edit application: the safety gate --------------------------------------

@pytest.fixture
def repo(tmp_path):
    (tmp_path / "consensus_engine").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "pkg.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "dup.py").write_text("a = 1\na = 1\n")
    (tmp_path / "config" / "consensus.yaml").write_text("scoring: {}\n")
    return tmp_path


def test_applies_one_exact_edit(repo):
    touched = fixer.apply_edits(
        [{"file": "pkg.py", "search": "x = 1", "replace": "x = 42"}], repo)
    assert touched == ["pkg.py"]
    assert (repo / "pkg.py").read_text() == "x = 42\ny = 2\n"


def test_applies_two_edits_to_the_same_file(repo):
    fixer.apply_edits([
        {"file": "pkg.py", "search": "x = 1", "replace": "x = 9"},
        {"file": "pkg.py", "search": "y = 2", "replace": "y = 8"},
    ], repo)
    assert (repo / "pkg.py").read_text() == "x = 9\ny = 8\n"


def test_an_ambiguous_search_is_rejected_not_guessed(repo):
    """Two matches means the model does not know which line it meant."""
    with pytest.raises(fixer.FixerError, match="appears 2 times"):
        fixer.apply_edits([{"file": "dup.py", "search": "a = 1", "replace": "a = 2"}], repo)
    assert (repo / "dup.py").read_text() == "a = 1\na = 1\n"   # untouched


def test_a_search_that_matches_nothing_is_rejected(repo):
    with pytest.raises(fixer.FixerError, match="appears 0 times"):
        fixer.apply_edits([{"file": "pkg.py", "search": "z = 3", "replace": "z = 4"}], repo)


def test_nothing_is_written_when_any_edit_fails(repo):
    """All-or-nothing: a good edit must not land beside a rejected one."""
    with pytest.raises(fixer.FixerError):
        fixer.apply_edits([
            {"file": "pkg.py", "search": "x = 1", "replace": "x = 99"},
            {"file": "pkg.py", "search": "nope", "replace": "!"},
        ], repo)
    assert (repo / "pkg.py").read_text() == "x = 1\ny = 2\n"


@pytest.mark.parametrize("path", [
    "config/consensus.yaml",
    ".github/workflows/ci.yml",
    "scripts/pre-push",
    "scripts/session_close.sh",
    ".claude/go-live-evidence/x.md",
    ".git/config",
])
def test_forbidden_paths_are_refused(repo, path):
    with pytest.raises(fixer.FixerError, match="forbidden"):
        fixer.apply_edits([{"file": path, "search": "a", "replace": "b"}], repo)


def test_the_config_file_is_never_written_even_though_it_exists(repo):
    before = (repo / "config" / "consensus.yaml").read_text()
    with pytest.raises(fixer.FixerError, match="forbidden"):
        fixer.apply_edits(
            [{"file": "config/consensus.yaml", "search": "scoring: {}", "replace": "boom"}], repo)
    assert (repo / "config" / "consensus.yaml").read_text() == before


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "a/../../etc/passwd"])
def test_paths_cannot_escape_the_repo(repo, path):
    with pytest.raises(fixer.FixerError):
        fixer.apply_edits([{"file": path, "search": "a", "replace": "b"}], repo)


def test_a_missing_file_is_rejected(repo):
    with pytest.raises(fixer.FixerError, match="no such file"):
        fixer.apply_edits([{"file": "ghost.py", "search": "a", "replace": "b"}], repo)


def test_an_incomplete_edit_is_rejected(repo):
    with pytest.raises(fixer.FixerError, match="needs file, search and replace"):
        fixer.apply_edits([{"file": "pkg.py", "search": "x = 1"}], repo)


# --- cross-family guard -----------------------------------------------------

def test_the_code_author_family_is_refused():
    """A model cannot review its own work (same reasoning as the Wolf verifier)."""
    with pytest.raises(fixer.FixerError, match="same family"):
        fixer.call_model("anthropic/claude-opus-4-8", "hi")


# --- context assembly -------------------------------------------------------

def test_relevant_files_picks_up_the_test_file_from_the_id(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): pass\n")
    files = fixer.relevant_files("tests/test_a.py::test_x", "", tmp_path)
    assert "tests/test_a.py" in files


def test_relevant_files_picks_up_source_files_named_in_the_traceback(tmp_path):
    (tmp_path / "consensus_engine").mkdir()
    (tmp_path / "consensus_engine" / "m.py").write_text("code\n")
    files = fixer.relevant_files("", "consensus_engine/m.py:41: in _write\n", tmp_path)
    assert "consensus_engine/m.py" in files


def test_relevant_files_never_includes_a_forbidden_file(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "consensus.yaml").write_text("x\n")
    files = fixer.relevant_files("", "config/consensus.yaml:1: boom\n", tmp_path)
    assert files == {}


def test_relevant_files_skips_paths_that_do_not_exist(tmp_path):
    assert fixer.relevant_files("tests/nope.py::test_x", "", tmp_path) == {}


def test_huge_files_are_truncated(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "big.py").write_text("z" * (fixer.MAX_FILE_CHARS + 500))
    content = fixer.relevant_files("tests/big.py::t", "", tmp_path)["tests/big.py"]
    assert "truncated" in content
    assert len(content) < fixer.MAX_FILE_CHARS + 200


def test_prompt_carries_the_failing_ids_the_error_and_the_files():
    prompt = fixer.build_prompt("tests/t.py::x", "AssertionError: boom", {"tests/t.py": "code"})
    assert "tests/t.py::x" in prompt
    assert "AssertionError: boom" in prompt
    assert "code" in prompt


def test_the_system_prompt_pins_the_three_classes():
    for cls in fixer.CLASSES:
        assert cls in fixer.SYSTEM


# --- prompt trimming (Phase 1 v3) -------------------------------------------

def test_trim_drops_a_deep_file_but_keeps_the_protected_one(monkeypatch):
    monkeypatch.setattr(fixer, "MAX_PROMPT_CHARS", 2000)
    big = "P" * 5000          # protected file, over budget alone
    deep = "D" * 5000         # import-followed file, should be dropped
    prompt = fixer.build_prompt(
        "tests/t.py::x", "boom",
        {"tests/t.py": big, "consensus_engine/deep.py": deep},
        protected={"tests/t.py"})
    assert "tests/t.py" in prompt          # protected file is present (truncated)
    assert "consensus_engine/deep.py" not in prompt   # deep file dropped for budget
    assert "truncated" in prompt


# --- context guard (Phase 1 v3) ---------------------------------------------

def test_run_skips_a_model_whose_window_is_too_small(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x():\n    assert False\n")
    monkeypatch.setattr(fixer, "model_meta", lambda slug: {"context_length": 100})
    with pytest.raises(fixer.FixerError, match="context_length"):
        fixer.run("tests/test_a.py::test_x", "AssertionError", "vendor/tiny", tmp_path)


# --- the one repair round (Phase 1 v3) --------------------------------------

def _repo_with_bug(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "consensus_engine").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "from consensus_engine import m\ndef test_x():\n    assert m.val() == 2\n")
    (tmp_path / "consensus_engine" / "__init__.py").write_text("")
    (tmp_path / "consensus_engine" / "m.py").write_text("def val():\n    return 1\n")
    return tmp_path


def _replies(monkeypatch, *texts):
    """Feed run() a scripted sequence of model replies with no network."""
    seq = list(texts)
    monkeypatch.setattr(fixer, "model_meta", lambda slug: {})   # no context guard, no json

    def fake(model, messages, temperature=0.0, deadline_s=0.0):
        return {"text": seq.pop(0), "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "latency_s": 0.1, "finish_reason": "stop", "provider": "test"}
    monkeypatch.setattr(fixer, "call_messages", fake)


def test_repair_round_recovers_from_unparseable_first_reply(tmp_path, monkeypatch):
    repo = _repo_with_bug(tmp_path)
    good = json.dumps({"classification": "real_logic_bug", "reason": "off by one",
                       "edits": [{"file": "consensus_engine/m.py",
                                  "search": "return 1", "replace": "return 2"}]})
    _replies(monkeypatch, "I think the bug is subtle, let me...", good)
    out = fixer.run("tests/test_a.py::test_x", "AssertionError", "vendor/x", repo)
    assert out["touched"] == ["consensus_engine/m.py"]
    assert len(out["attempts"]) == 2                       # first + repair
    assert out["usage"]["completion_tokens"] == 10         # summed across both calls
    assert (repo / "consensus_engine" / "m.py").read_text() == "def val():\n    return 2\n"


def test_repair_round_recovers_from_a_search_string_miss(tmp_path, monkeypatch):
    repo = _repo_with_bug(tmp_path)
    miss = json.dumps({"classification": "real_logic_bug", "reason": "x",
                       "edits": [{"file": "consensus_engine/m.py",
                                  "search": "return 999", "replace": "return 2"}]})
    good = json.dumps({"classification": "real_logic_bug", "reason": "x",
                       "edits": [{"file": "consensus_engine/m.py",
                                  "search": "return 1", "replace": "return 2"}]})
    _replies(monkeypatch, miss, good)
    out = fixer.run("tests/test_a.py::test_x", "AssertionError", "vendor/x", repo)
    assert out["touched"] == ["consensus_engine/m.py"]
    assert len(out["attempts"]) == 2


def test_no_repair_round_when_the_first_reply_is_clean(tmp_path, monkeypatch):
    repo = _repo_with_bug(tmp_path)
    good = json.dumps({"classification": "real_logic_bug", "reason": "x",
                       "edits": [{"file": "consensus_engine/m.py",
                                  "search": "return 1", "replace": "return 2"}]})
    _replies(monkeypatch, good, "SHOULD NOT BE CALLED")
    out = fixer.run("tests/test_a.py::test_x", "AssertionError", "vendor/x", repo)
    assert len(out["attempts"]) == 1


def test_a_second_failure_after_repair_gives_up(tmp_path, monkeypatch):
    repo = _repo_with_bug(tmp_path)
    _replies(monkeypatch, "garbage one", "garbage two")
    with pytest.raises(fixer.FixerError):
        fixer.run("tests/test_a.py::test_x", "AssertionError", "vendor/x", repo)
