"""KIB Assistant core package — reusable RAG, auth, scraper, and update logic."""

from .rag import ask_kib, KIBAssistant
from .config import settings

__all__ = ["ask_kib", "KIBAssistant", "settings"]
