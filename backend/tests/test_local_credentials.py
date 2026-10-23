import importlib.util
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[2] / "tools" / "configure_local_credentials.py"
spec = importlib.util.spec_from_file_location("local_credentials", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_prepare_preserves_model_key_and_is_idempotent(tmp_path):
    (tmp_path / "backend").mkdir()
    env = tmp_path / "backend" / ".env"
    env.write_text("LLM_API_KEY=keep-test-key\nDATA_AGENT_API_TOKEN=\nMETA_DB_PASSWORD=\nDW_DB_PASSWORD=\n", encoding="utf-8")
    module.prepare(tmp_path)
    before = env.read_bytes()
    values = module.read_env(env)
    assert values["LLM_API_KEY"] == "keep-test-key"
    assert values["META_DB_PORT"] == values["DW_DB_PORT"] == "13306"
    assert len({values[k] for k in module.SECRET_KEYS}) == 3
    assert all(len(values[k]) >= 48 for k in module.SECRET_KEYS)
    module.prepare(tmp_path)
    assert env.read_bytes() == before
    sql = (tmp_path / ".secrets" / "mysql-init.sql").read_text()
    assert "GRANT SELECT ON dw.*" in sql
    assert "DROP" not in sql and "ALTER USER" not in sql


def test_never_replaces_existing_database_credentials(tmp_path):
    (tmp_path / "backend").mkdir()
    env = tmp_path / "backend" / ".env"
    env.write_text("DW_DB_PASSWORD=existing-password\n", encoding="utf-8")
    with pytest.raises(ValueError):
        module.prepare(tmp_path)
    assert env.read_text() == "DW_DB_PASSWORD=existing-password\n"
