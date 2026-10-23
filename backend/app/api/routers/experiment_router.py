from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from improved.auth import require_api_token, query_rate_limit
from improved.experiments import ExperimentRejected
from improved.experiment_registry import evaluate_registered

experiment_router = APIRouter(dependencies=[Depends(require_api_token),Depends(query_rate_limit)])


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    experiment_id: str = Field(min_length=1,max_length=80,pattern=r'^[a-z0-9_]+$')


@experiment_router.post('/api/experiments/evaluate')
def evaluate(body: ExperimentRequest):
    try:
        return evaluate_registered(body.experiment_id)
    except ExperimentRejected as error:
        # All ExperimentRejected messages are server-owned codes, never raw input.
        raise HTTPException(422, {'code':str(error),'message':'实验数据或设计未通过校验，未生成因果结论。'}) from None
