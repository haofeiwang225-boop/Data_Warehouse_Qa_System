from pydantic import BaseModel, Field


class QuerySchema(BaseModel):
    query: str = Field(min_length=1)
