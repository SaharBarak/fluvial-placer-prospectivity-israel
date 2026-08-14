"""Immutable application settings injected at composition roots (PRD §17.4)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOLDFLOW_", env_file=".env", frozen=True, extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://goldflow:goldflow_dev@localhost:5433/goldflow"
    database_url_sync: str = "postgresql+psycopg://goldflow:goldflow_dev@localhost:5433/goldflow"
    object_store_root: Path = Path("data/objects")
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "goldflow-research"
    gsi_arcgis_root: str = "https://egozi.gsi.gov.il/arcgis/rest/services"
    stac_root: str = "https://stac.dataspace.copernicus.eu/v1"
    datagov_root: str = "https://data.gov.il/api/3/action"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-5"
    run_token_budget: int = 200_000
    run_http_budget: int = 500
    api_cors_origins: str = "http://localhost:5173"


def load_settings() -> Settings:
    return Settings()
