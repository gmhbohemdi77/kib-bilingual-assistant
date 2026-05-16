"""
FastAPI wrapper around core.rag.KIBAssistant — Phase 5.1 (Teams via Copilot
Studio).

Why a FastAPI wrapper instead of pointing Copilot Studio directly at MongoDB?
  * Copilot Studio's "topics" can call HTTP endpoints (via custom connectors)
    but cannot run Python or open vector-search pipelines directly.
  * Wrapping the same KIBAssistant used by Streamlit means there's exactly
    one code path producing answers — fix it once, both surfaces benefit.

The endpoint takes an API key in the `x-api-key` header. In Copilot Studio
the custom connector stores this as a "API Key" security definition, so KIB
employees never see it.

Run locally:
    uvicorn teams_api.main:app --reload --port 8080

Deploy:
    Same Azure Web App as Streamlit (different App Service plan or sibling
    app), or to Azure Functions with `func init`. See docs/DEPLOY_TEAMS.md.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from core.rag import KIBAssistant  # noqa: E402


app = FastAPI(
    title="KIB Assistant API",
    description=(
        "Bilingual (English/Arabic) RAG API for Kuwait International Bank. "
        "Used by the Microsoft Teams Copilot Studio connector and any other "
        "non-Streamlit client."
    ),
    version="1.0.0",
)
app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
)

# ---- Auth -------------------------------------------------------------------


def _api_key_dep(x_api_key: str = Header(..., alias="x-api-key")) -> None:
    expected = os.getenv("KIB_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="Server is missing KIB_API_KEY")
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---- Models -----------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(..., description="The user's question, in English or Arabic.")
    top_k: int = Field(3, ge=1, le=10, description="How many source chunks to retrieve.")


class SourceModel(BaseModel):
    url: str
    score: float


class AskResponse(BaseModel):
    answer: str
    language: str = Field(..., description="'ar' or 'en' — detected from the question.")
    sources: list[SourceModel]


# ---- Singleton --------------------------------------------------------------


_assistant: KIBAssistant | None = None


def _get_assistant() -> KIBAssistant:
    global _assistant
    if _assistant is None:
        _assistant = KIBAssistant()
    return _assistant


# ---- Routes -----------------------------------------------------------------


@app.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask KIB Assistant a question",
    dependencies=[Depends(_api_key_dep)],
)
def ask(payload: AskRequest) -> AskResponse:
    result = _get_assistant().ask(payload.question, top_k=payload.top_k)
    return AskResponse(
        answer=result.answer,
        language=result.language,
        sources=[SourceModel(url=s.url, score=s.score) for s in result.sources],
    )
