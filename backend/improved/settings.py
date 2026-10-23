"""Load a local .env as plain data (never execute shell syntax)."""
import os
from pathlib import Path
import re

BACKEND = Path(__file__).resolve().parents[1]


def load_env_file(path=None):
    path = Path(path or BACKEND / ".env")
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("INVALID_LOCAL_ENV_FORMAT")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def missing_configuration(config):
    required = {"LLM_MODEL": config.llm.model_name, "LLM_API_KEY": config.llm.api_key,
                "LLM_BASE_URL": config.llm.base_url, "META_DB_PASSWORD": config.db_meta.password,
                "DW_DB_PASSWORD": config.db_dw.password, "DATA_AGENT_API_TOKEN": os.getenv("DATA_AGENT_API_TOKEN")}
    return [name for name, value in required.items() if not value]
