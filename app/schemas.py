from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=8000)
    candidate_k: int | None = Field(
        default=None, ge=5, le=200, description="Override retrieval count before LLM"
    )
    final_n: int | None = Field(
        default=None, ge=1, le=20, description="Override number of results returned"
    )
    use_llm: bool = Field(
        default=True,
        description="If false, skip LLM (much faster; embedding scores only, placeholder text)",
    )


class SearchHit(BaseModel):
    case_id: int
    source_uri: str
    public_url: str | None
    title: str | None
    neutral_citation: str | None
    court: str | None
    decision_date: str | None
    outcome_label: str | None
    similarity: float
    short_summary: str
    why_similar: str
    chunk_excerpt: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]
    used_llm: bool
    query: str
