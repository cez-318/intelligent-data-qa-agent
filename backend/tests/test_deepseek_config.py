from pathlib import Path
import pytest


def test_template_defaults_to_official_deepseek():
    template = Path(__file__).resolve().parents[1] / ".env.example"
    values = dict(line.split("=", 1) for line in template.read_text(encoding="utf-8").splitlines()
                  if line and not line.startswith("#"))
    assert values["LLM_MODEL"] == "deepseek-flash"
    assert values["LLM_BASE_URL"] == "https://api.deepseek.com"
    assert values["LLM_PROVIDER"] == "deepseek"
    assert values["LLM_API_KEY"] == ""


@pytest.mark.parametrize("provider,expected", [("deepseek", {"thinking": {"type": "disabled"}}), ("openai_compatible", None)])
def test_client_uses_configured_provider_without_network(monkeypatch, provider, expected):
    from app.agent.llm import get_model
    from app.conf.app_config import app_config
    monkeypatch.setattr(app_config.llm, "model_name", "deepseek-flash")
    monkeypatch.setattr(app_config.llm, "api_key", "test-only-not-a-real-key")
    monkeypatch.setattr(app_config.llm, "base_url", "https://api.deepseek.com")
    monkeypatch.setattr(app_config.llm, "provider", provider)
    monkeypatch.setattr(app_config.llm, "thinking", "disabled")
    get_model.cache_clear()
    try:
        client = get_model()
        assert client.model_name == "deepseek-flash"
        assert client.extra_body == expected
        assert client.use_responses_api is False
    finally:
        get_model.cache_clear()
