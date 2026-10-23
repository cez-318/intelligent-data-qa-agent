from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.services.query_service import QueryService
from improved.auth import require_api_token, query_rate_limit, require_ready

query_router = APIRouter(dependencies=[Depends(require_ready), Depends(require_api_token), Depends(query_rate_limit)])


@query_router.post("/api/query")
async def query(
    query: QuerySchema, query_service: QueryService = Depends(get_query_service)
):
    return StreamingResponse(
        query_service.query(query.query), media_type="text/event-stream"
    )
