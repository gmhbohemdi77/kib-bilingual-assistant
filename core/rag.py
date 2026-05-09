"""
Reusable RAG query module — the core of the KIB Assistant.

Wraps the same logic as your friend's query_bilingual.py, but as a class so
clients (Streamlit, FastAPI, Azure Function) can hold a single instance and
re-use the MongoDB / Azure OpenAI connections.

Public API:
    KIBAssistant().ask("How do I open a savings account?") -> AskResult
    ask_kib(question)  # convenience wrapper around a module-level singleton
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import certifi
from openai import AzureOpenAI
from pymongo import MongoClient

from .config import settings


# Characters that signal an Arabic question. Matches the heuristic in
# query_bilingual.py exactly so behavior is identical to Phase 4 tests.
_ARABIC_CHARS = set("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")


@dataclass
class Source:
    text_en: str
    text_ar: str
    url: str
    score: float


@dataclass
class AskResult:
    question: str
    answer: str
    language: str  # "ar" or "en"
    sources: list[Source]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "language": self.language,
            "sources": [asdict(s) for s in self.sources],
        }


class KIBAssistant:
    """Long-lived RAG client. Construct once, call .ask() many times."""

    def __init__(self) -> None:
        # tlsCAFile=certifi.where() works around a Python 3.13 + Windows +
        # MongoDB Atlas TLS handshake issue. Harmless on other platforms.
        self._mongo = MongoClient(settings.mongodb_url, tlsCAFile=certifi.where())
        self._collection = self._mongo[settings.mongodb_db][settings.mongodb_collection]
        self._ai = AzureOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_key,
            api_version=settings.azure_api_version,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def detect_language(text: str) -> str:
        """Return 'ar' if the text contains any Arabic letter, else 'en'."""
        return "ar" if any(c in _ARABIC_CHARS for c in text) else "en"

    def embed(self, text: str) -> list[float]:
        response = self._ai.embeddings.create(
            model=settings.embedding_deployment,
            input=text,
        )
        return response.data[0].embedding

    # -- main entrypoint ---------------------------------------------------

    def ask(self, question: str, *, top_k: int = 3, num_candidates: int = 10) -> AskResult:
        if not question or not question.strip():
            return AskResult(
                question=question,
                answer="Please enter a question.",
                language="en",
                sources=[],
            )

        language = self.detect_language(question)
        search_field = "embedding_ar" if language == "ar" else "embedding_en"

        # 1) Embed question
        query_vec = self.embed(question)

        # 2) Vector search MongoDB Atlas. We over-fetch, then filter out chunks
        # marked stale by Phase 6 (active: false). Docs without `active` are
        # treated as active (covers everything your friend loaded in Phase 3-4).
        pipeline = [
            {
                "$vectorSearch": {
                    "index": settings.vector_index_name,
                    "path": search_field,
                    "queryVector": query_vec,
                    "numCandidates": num_candidates,
                    "limit": top_k * 3,  # over-fetch to survive the active filter
                }
            },
            {"$match": {"active": {"$ne": False}}},
            {"$limit": top_k},
            {
                "$project": {
                    "text_en": 1,
                    "text_ar": 1,
                    "url": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        hits = list(self._collection.aggregate(pipeline))

        if not hits:
            no_data = (
                "لم أتمكن من العثور على معلومات ذات صلة. يرجى إعادة الصياغة."
                if language == "ar"
                else "I couldn't find relevant information. Please try rephrasing."
            )
            return AskResult(question=question, answer=no_data, language=language, sources=[])

        # 3) Build context in the user's language
        context_field = "text_ar" if language == "ar" else "text_en"
        context = "\n\n".join(h.get(context_field, "") for h in hits)

        # 4) Generate the answer
        system_prompt = (
            "You are KIB Assistant, the official AI assistant for Kuwait International Bank (KIB). "
            f"Answer in {'Arabic' if language == 'ar' else 'English'}. "
            "Use ONLY the context provided. If the context does not contain the answer, "
            "say you don't have that information and suggest the user contact KIB directly. "
            "Do not invent products, rates, or fees."
        )
        user_prompt = f"Context:\n{context}\n\nQuestion: {question}"

        chat = self._ai.chat.completions.create(
            model=settings.chat_deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        answer = chat.choices[0].message.content or ""

        sources = [
            Source(
                text_en=h.get("text_en", ""),
                text_ar=h.get("text_ar", ""),
                url=h.get("url", ""),
                score=float(h.get("score", 0.0)),
            )
            for h in hits
        ]

        return AskResult(question=question, answer=answer, language=language, sources=sources)


# Module-level singleton — built lazily on first call so importing this
# module never blocks on a network connection.
_assistant: KIBAssistant | None = None


def ask_kib(question: str, *, top_k: int = 3) -> AskResult:
    """Convenience wrapper around a module-level KIBAssistant singleton."""
    global _assistant
    if _assistant is None:
        _assistant = KIBAssistant()
    return _assistant.ask(question, top_k=top_k)


if __name__ == "__main__":
    # Same interactive loop as query_bilingual.py, but using the new module.
    print("=" * 50)
    print("KIB Bilingual Assistant (core.rag)")
    print("Ask questions in English or Arabic. Type 'exit' to quit.")
    print("=" * 50)
    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        if not q:
            continue
        result = ask_kib(q)
        print(f"\n[lang={result.language}]")
        print(f"Assistant: {result.answer}")
        print("\nSources:")
        for s in result.sources:
            print(f"  - {s.url}  (score={s.score:.3f})")
