import os
from types import SimpleNamespace
import pytest
from improved.settings import load_env_file, missing_configuration


def test_env_is_plain_data_and_process_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_TEST_VALUE", "process")
    monkeypatch.delenv("QA_TEST_QUOTED", raising=False)
    path = tmp_path / ".env"
    path.write_text('# comment\n\nQA_TEST_VALUE=file\nQA_TEST_QUOTED="$(not_a_command)"\n', encoding="utf-8-sig")
    load_env_file(path)
    assert os.environ["QA_TEST_VALUE"] == "process"
    assert os.environ["QA_TEST_QUOTED"] == "$(not_a_command)"
    monkeypatch.delenv("QA_TEST_QUOTED")


@pytest.mark.parametrize("line", ["bad", "lowercase=value", "A B=value"])
def test_env_rejects_invalid_format(tmp_path, line):
    path = tmp_path / ".env"
    path.write_text(line, encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_LOCAL_ENV_FORMAT"):
        load_env_file(path)


def test_missing_settings_reports_names_not_secrets(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_API_TOKEN", "test-private")
    config = SimpleNamespace(llm=SimpleNamespace(model_name="model", api_key="test-private", base_url="https://example.invalid"),
                             db_meta=SimpleNamespace(password=""), db_dw=SimpleNamespace(password="test-private"))
    assert missing_configuration(config) == ["META_DB_PASSWORD"]


def test_llm_configuration_fails_closed(monkeypatch):
    from app.agent.llm import get_model
    from app.conf.app_config import app_config
    monkeypatch.setattr(app_config.llm, "api_key", "")
    get_model.cache_clear()
    with pytest.raises(RuntimeError, match="LLM_CONFIGURATION_MISSING"):
        get_model()
    get_model.cache_clear()
