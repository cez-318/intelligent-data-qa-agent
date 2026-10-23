"""Single trusted service-token boundary, not employee-level RBAC."""
import os
import secrets
from collections import deque
import time
from fastapi import Header, HTTPException, Request


def require_ready(request: Request):
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(503, "问数服务未就绪，请查看服务状态并完成配置；不会降级为规则演示。")

_recent = deque(maxlen=30)


def require_api_token(authorization: str | None = Header(default=None)):
    expected = os.getenv("DATA_AGENT_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "服务访问凭据未配置")
    value = authorization or ""
    supplied = value.removeprefix("Bearer ") if value.startswith("Bearer ") else ""
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "未授权")


async def query_rate_limit():
    now = time.monotonic()
    while _recent and _recent[0] < now - 60:
        _recent.popleft()
    if len(_recent) >= 30:
        raise HTTPException(429, "请求过于频繁，请稍后重试")
    _recent.append(now)
