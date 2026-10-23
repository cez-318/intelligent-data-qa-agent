"""Local synthetic-data demo; intentionally not a production authentication system."""
import json
from pathlib import Path
import time
from collections import deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from tests.legacy.demo import DemoService, seed_demo

DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / "data" / "synthetic_hr.sqlite3"


class QueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)


def create_app(database=None):
    database = Path(database or DEFAULT_DATABASE)
    # No seeding on import; startup is local-only and never overwrites files.
    service = DemoService(database)
    app = FastAPI(title="智能问数 · 虚构人力数据演示")
    requests = deque(maxlen=30)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "synthetic_data_only", "llm_enabled": False}

    @app.post("/api/query")
    async def query(body: QueryInput):
        now = time.monotonic()
        while requests and requests[0] < now - 60:
            requests.popleft()
        if len(requests) >= 30:
            raise HTTPException(429, "演示服务每分钟最多30次查询")
        requests.append(now)
        async def events():
            yield "data: " + json.dumps({"type": "progress", "step": "校验口径并执行只读查询", "status": "running"}, ensure_ascii=False) + "\n\n"
            try:
                result = await service.ask(body.query)
            except Exception:
                result = {"type": "error", "message": "查询未完成，请检查服务端配置或联系维护者。"}
            yield "data: " + json.dumps({"type": "progress", "step": "校验口径并执行只读查询", "status": "error" if result["type"] == "error" else "success"}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps(result, ensure_ascii=False) + "\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    frontend = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")
    return app


app = create_app()

if __name__ == "__main__":
    raise SystemExit("Test fixture only. Start the application with backend/main.py.")
