"""Application settings (pydantic-settings, env-driven)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration.

    All values have safe defaults so the app boots with no ``.env`` and no LLM
    credentials. Real-LLM integration is opt-in via a provider key (Mistral by
    default); persistence and Supabase auth degrade to in-memory / configured
    defaults when their environment variables are unset.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- app -----------------------------------------------------------------
    app_name: str = "LLM Robotic Task-Planning Agent"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    # -- server / CORS -------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # -- world ---------------------------------------------------------------
    default_scene: str = "default"

    # -- auth (Supabase JWT, always enforced) --------------------------------
    auth_required: bool = Field(
        default=True,
        description="Enforce Supabase JWT auth on every /api/v1/** and /ws/** route.",
    )
    supabase_url: str | None = Field(default=None)
    supabase_anon_key: str | None = Field(default=None)
    supabase_service_role_key: str | None = Field(default=None)
    supabase_jwt_secret: str | None = Field(
        default=None,
        description="HS256 secret from the Supabase dashboard; used to verify user JWTs.",
    )
    supabase_jwt_aud: str | None = Field(
        default="authenticated",
        description="Expected JWT audience; verified only when present on the token.",
    )
    supabase_jwt_iss: str | None = Field(
        default=None,
        description="Expected JWT issuer; verified only when set and present on the token.",
    )

    # -- persistence ---------------------------------------------------------
    database_url: str | None = Field(
        default=None,
        description="Postgres DSN (postgresql+asyncpg://...) for the Supabase database.",
    )
    persistence_backend: str = Field(
        default="auto",
        description="auto | supabase | memory. 'auto' uses SQL when DATABASE_URL + libs present.",
    )

    # -- session registry ----------------------------------------------------
    session_ttl_seconds: int = Field(
        default=3600,
        description="Idle-eviction TTL for in-process per-(user, session) state.",
    )

    # -- LLM planner (real brain) --------------------------------------------
    enable_llm: bool = Field(
        default=True,
        description="Master switch for the real-LLM planner; heuristic fallback always works.",
    )
    llm_backend: str = Field(
        default="mistral",
        description="Which LLM backend to use when enabled: 'mistral' (default) or 'anthropic'.",
    )
    # Mistral (default backend).
    mistral_api_key: str | None = Field(default=None)
    mistral_model: str = Field(
        default="mistral-large-latest",
        description="Mistral model id for the LLM-backed planner.",
    )
    mistral_base_url: str = Field(
        default="https://api.mistral.ai/v1",
        description="Base URL for the Mistral REST fallback (used when the SDK is absent).",
    )
    # Anthropic (alternative backend).
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(
        default="claude-opus-4-8",
        description="Anthropic model id for the LLM-backed planner (alternative backend).",
    )
    llm_max_tokens: int = Field(default=2048)
    llm_timeout_seconds: float = Field(default=30.0)

    # -- plan memory (pgvector few-shot retrieval) ---------------------------
    enable_plan_memory: bool = Field(
        default=True,
        description="Store successful (instruction->plan) pairs and retrieve top-k as few-shot.",
    )
    plan_memory_top_k: int = Field(default=3)
    embedding_dim: int = Field(
        default=384,
        description="Embedding dimension; must match the pgvector column (vector(384)).",
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="sentence-transformers model id when available; hashing fallback otherwise.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins, accepting a comma-separated string from the environment."""

        if isinstance(self.cors_origins, str):  # pragma: no cover - env coercion
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return self.cors_origins

    @property
    def default_planner_mode(self) -> str:
        """Default planner mode: 'llm' when a provider key is present, else 'heuristic'."""

        if not self.enable_llm:
            return "heuristic"
        backend = self.llm_backend.lower()
        if backend == "mistral" and self.mistral_api_key:
            return "llm"
        if backend == "anthropic" and self.anthropic_api_key:
            return "llm"
        return "heuristic"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""

    return Settings()
