"""
Centralized configuration.

Reads from environment variables. In Azure, these come from App Service config
or Function App settings (which can be backed by Key Vault references for
secrets like MONGODB_URL and AZURE_KEY).

Locally, they come from a .env file via python-dotenv (loaded once here).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env once at import time. In Azure Web Apps / Functions there is no
# .env file, but env vars are already populated by App Service config — this
# call is a no-op there.
load_dotenv()


def _required(name: str) -> str:
    """Read an env var that must be present, with a friendly error if missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file (local) or in App Service / Function App "
            f"configuration (Azure)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # MongoDB Atlas
    mongodb_url: str
    mongodb_db: str = "kib_db"
    mongodb_collection: str = "web_chunks_bilingual"
    vector_index_name: str = "vector_index"

    # Azure OpenAI
    azure_endpoint: str = ""
    azure_key: str = ""
    azure_api_version: str = "2024-08-01-preview"
    embedding_deployment: str = "text-embedding-3-small"
    chat_deployment: str = "gpt-4.1-mini"

    # Azure Translator (optional — GPT can also translate)
    translator_key: str = ""
    translator_region: str = ""

    # Entra ID / MSAL (Phase 5.3)
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8501"

    # Role gating (Phase 5.4)
    # Comma-separated lists of Entra ID Object IDs. The simplest mechanism that
    # works without needing app roles configured: maintain two security groups
    # in Entra ID and put the Object IDs of those groups here.
    ai_trainer_group_ids: str = ""

    # Phase 6 — pages to scrape on each scheduled run
    scrape_urls: tuple = (
        "https://www.kib.com.kw/en/home/Personal",
        "https://www.kib.com.kw/en/home/Personal/Bank",
        "https://www.kib.com.kw/en/home/Real-Estate",
        "https://www.kib.com.kw/en/offers",
        "https://www.kib.com.kw/en/promotions",
    )


def _build() -> Settings:
    return Settings(
        mongodb_url=_required("MONGODB_URL"),
        azure_endpoint=_required("AZURE_ENDPOINT"),
        azure_key=_required("AZURE_KEY"),
        azure_api_version=_optional("AZURE_API_VERSION", "2024-08-01-preview"),
        embedding_deployment=_optional("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        chat_deployment=_optional("AZURE_CHAT_DEPLOYMENT", "gpt-4.1-mini"),
        translator_key=_optional("AZURE_TRANSLATOR_KEY"),
        translator_region=_optional("AZURE_TRANSLATOR_REGION"),
        tenant_id=_optional("AZURE_TENANT_ID"),
        client_id=_optional("AZURE_CLIENT_ID"),
        client_secret=_optional("AZURE_CLIENT_SECRET"),
        redirect_uri=_optional("AZURE_REDIRECT_URI", "http://localhost:8501"),
        ai_trainer_group_ids=_optional("AI_TRAINER_GROUP_IDS"),
    )


# Lazy singleton — settings only validate when first accessed, so test code
# that imports the package without a full .env doesn't crash.
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = _build()
    return _settings


class _SettingsProxy:
    """Lazy proxy so `from core.config import settings` works but doesn't
    eagerly read env vars at import time."""

    def __getattr__(self, item):
        return getattr(_get_settings(), item)


settings = _SettingsProxy()
