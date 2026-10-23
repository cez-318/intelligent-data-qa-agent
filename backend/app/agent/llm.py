"""Lazy real-model client: missing configuration never enables a rule/demo fallback."""
from functools import lru_cache
from langchain_core.runnables import RunnableLambda


@lru_cache(maxsize=1)
def get_model():
    from langchain_openai import ChatOpenAI
    from app.conf.app_config import app_config
    cfg = app_config.llm
    if not cfg.api_key or not cfg.model_name or not cfg.base_url:
        raise RuntimeError("LLM_CONFIGURATION_MISSING")
    if cfg.provider not in {"deepseek", "openai_compatible"}:
        raise ValueError("INVALID_LLM_PROVIDER")
    extra_body = None
    if cfg.provider == "deepseek":
        if cfg.thinking not in {"enabled", "disabled"}:
            raise ValueError("INVALID_LLM_THINKING_MODE")
        extra_body = {"thinking": {"type": cfg.thinking}}
    return ChatOpenAI(model=cfg.model_name, api_key=cfg.api_key, base_url=cfg.base_url,
                      temperature=0, timeout=20, max_retries=1,
                      use_responses_api=False, extra_body=extra_body)


async def _invoke(value, config=None):
    return await get_model().ainvoke(value, config=config)


llm = RunnableLambda(_invoke)
