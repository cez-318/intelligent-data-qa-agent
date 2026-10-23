"""The only supported application entry: real LLM + original RAG + database."""
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.routers.query_router import query_router
from app.api.routers.experiment_router import experiment_router
from improved.experiment_registry import catalog
from app.core.context import request_id_ctx_var
from app.core.lifespan import lifespan
from improved.profiles import active_profile


def create_app():
    app = FastAPI(title="智能问数", lifespan=lifespan)
    app.include_router(query_router)
    app.include_router(experiment_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex
        token = request_id_ctx_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            request_id_ctx_var.reset(token)

    @app.get("/api/health")
    def health():
        return {"mode": "llm_rag", "ready": getattr(app.state, "ready", False),
                "missing_configuration": getattr(app.state, "missing_configuration", []),
                "dependency_error": getattr(app.state, "service_error", None), "rule_fallback": False,
                "dataset": active_profile().public_info(), "experiments":catalog()}

    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
