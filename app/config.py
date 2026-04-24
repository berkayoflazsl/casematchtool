from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://berkayoflaz@localhost:5432/project_law"
    # OpenAI-compatible key (OpenAI, OpenRouter sk-or-..., etc.)
    openai_api_key: str | None = None
    # Direct OpenAI or Azure-style override
    openai_base_url: str | None = None
    # Common alias from other projects (e.g. OpenRouter)
    llm_service_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    # Alias: LLM_MODEL=openai/gpt-4o-mini (takes priority over openai_model if set)
    llm_model: str | None = None
    # OpenRouter optional headers
    openrouter_http_referer: str = "http://127.0.0.1:8000"
    openrouter_app_title: str = "CaseMatch MVP"

    fcl_atom_base: str = "https://caselaw.nationalarchives.gov.uk/atom.xml"
    # Retrieval: more chunks fetched, then deduped
    search_candidate_k: int = 40
    search_final_n: int = 8
    # LLM prompt size: fewer = faster, cheaper
    search_llm_max_cases: int = 8
    search_llm_excerpt_chars: int = 500
    # Completion budget: lower = usually faster; raise if JSON truncates
    search_llm_max_output_tokens: int = 1200
    search_llm_timeout_sec: float = 20.0
    fcl_request_sleep: float = 0.15
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("PORT", "port"),
        description="uvicorn port",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def llm_base_url(s: Settings) -> str | None:
    b = (s.llm_service_url or s.openai_base_url or "").strip()
    return b or None


def chat_model_id(s: Settings) -> str:
    return (s.llm_model or s.openai_model or "gpt-4o-mini").strip()
