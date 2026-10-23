from pydantic import BaseModel, Field, ConfigDict


class QuerySchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
