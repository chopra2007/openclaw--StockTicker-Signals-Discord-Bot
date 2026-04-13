import importlib

from models import vision_model


def test_vision_model_parses_tsla_scenarios_json():
    raw = """{
      \"source\": \"Morgan Stanley\",
      \"ticker\": \"TSLA\",
      \"analysis_type\": \"bull/base/bear case report\",
      \"scenarios\": {
        \"bull_case\": {\"price\": 500, \"details\": \"robotaxi upside\"},
        \"base_case\": {\"price\": 300, \"details\": \"execution in line\"},
        \"bear_case\": {\"price\": 150, \"details\": \"margin compression\"}
      },
      \"probabilities\": {\"bull\": 0.25, \"base\": 0.55, \"bear\": 0.20},
      \"sentiment\": \"bullish\",
      \"confidence\": 0.92,
      \"summary\": \"TSLA scenario framework with asymmetric upside\"
    }"""

    parsed = vision_model._parse_json_response(raw)

    assert parsed["source"] == "Morgan Stanley"
    assert parsed["ticker"] == "TSLA"
    assert parsed["scenarios"]["bull_case"]["price"] == 500
    assert parsed["scenarios"]["base_case"]["price"] == 300
    assert parsed["scenarios"]["bear_case"]["price"] == 150
    assert parsed["probabilities"]["base"] == 0.55


def test_vision_model_fallback_returns_valid_schema():
    parsed = vision_model._parse_json_response("not-json")
    assert parsed["source"] == ""
    assert parsed["ticker"] == ""
    assert "bull_case" in parsed["scenarios"]
    assert "base_case" in parsed["scenarios"]
    assert "bear_case" in parsed["scenarios"]


def test_model_config_vision_model_swappable_via_env(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "openai/gpt-4.1-mini")
    from models import model_config
    importlib.reload(model_config)

    assert model_config.VISION_MODEL == "openai/gpt-4.1-mini"


def test_model_config_has_non_empty_defaults():
    from models import model_config
    importlib.reload(model_config)

    assert model_config.TEXT_MODEL_DEFAULT
    assert model_config.VISION_MODEL_DEFAULT
