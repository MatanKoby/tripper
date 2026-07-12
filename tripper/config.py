"""Runtime configuration for the tripper backend.

Loaded from environment variables (and an optional ``.env`` for local dev). Holds tripper's own
runtime settings plus the config it passes through to domain agents (the hotel agent reads the same
names). Constructing ``Settings`` validates that the selected providers/scorer have the config they
need and raises :class:`ConfigError` with a clear message otherwise.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required configuration for the selected providers/scorer is missing."""


class Settings(BaseSettings):
    """Backend settings. Field names map to upper-cased env vars (e.g. ``SCORER``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- tripper runtime ---
    gcp_project: str = ""               # blank = auto-detected in GCP; set it for local/emulator
    firestore_emulator_host: str = ""   # e.g. "localhost:8080" for local dev

    # --- agent selection (passed through to the hotel agent) ---
    enabled_providers: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["mock"])
    scorer: str = "heuristic"           # "heuristic" | "llm"
    llm_backend: str = "auto"           # "auto" | "openai" | "endpoint"

    # --- Nebius Ollama serverless endpoint (no key) ---
    nebius_endpoint_url: str = ""
    nebius_endpoint_token: str = ""
    nebius_endpoint_model: str = ""

    # --- OpenAI-compatible LLM (key path) ---
    llm_base_url: str = ""
    llm_api_key: str = ""

    # --- LiteAPI hotel data ---
    liteapi_api_key: str = ""

    @field_validator("enabled_providers", mode="before")
    @classmethod
    def _split_providers(cls, value: object) -> object:
        """Accept a comma-separated string (``mock,liteapi``) as well as a real list."""
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    @model_validator(mode="after")
    def _check_required(self) -> Settings:
        if "liteapi" in self.enabled_providers and not self.liteapi_api_key:
            raise ConfigError("LITEAPI_API_KEY is required when 'liteapi' is in ENABLED_PROVIDERS")
        if self.scorer == "llm" and not (self.nebius_endpoint_url or self.llm_api_key):
            raise ConfigError(
                "SCORER=llm needs an LLM transport: set NEBIUS_ENDPOINT_URL (endpoint) "
                "or LLM_API_KEY (openai)"
            )
        return self

    def agent_env(self) -> dict[str, str]:
        """The subset of settings the hotel agent reads, keyed by its env-var names.

        The hotel adapter (Batch 10) uses this to build the agent's own ``Settings``. Empty values
        are dropped so the agent falls back to its own defaults.
        """
        env = {
            "ENABLED_PROVIDERS": ",".join(self.enabled_providers),
            "SCORER": self.scorer,
            "LLM_BACKEND": self.llm_backend,
            "NEBIUS_ENDPOINT_URL": self.nebius_endpoint_url,
            "NEBIUS_ENDPOINT_TOKEN": self.nebius_endpoint_token,
            "NEBIUS_ENDPOINT_MODEL": self.nebius_endpoint_model,
            "LLM_BASE_URL": self.llm_base_url,
            "LLM_API_KEY": self.llm_api_key,
            "LITEAPI_API_KEY": self.liteapi_api_key,
        }
        return {key: value for key, value in env.items() if value != ""}
