"""
Phase 6 — change detection + MongoDB update.

Strategy:
  1. Scrape each URL with core.scraper.
  2. For each chunk, compute a SHA-256 hash of the *English* text. We use the
     hash as a stable identity (replaces relying on chunk_index, which shifts
     when KIB adds/removes content).
  3. Look up MongoDB to see which hashes are already there.
  4. For NEW hashes: translate to Arabic with GPT-4.1-mini, generate both
     embeddings, insert with `chunk_hash`.
  5. For chunks whose hash no longer appears in the freshly-scraped output of
     a URL we visited: mark them stale (we don't delete to keep history). The
     vector index still includes them, but we set `active: false` and the RAG
     pipeline filters those out.

Every run returns an UpdateReport with counts so the AI Trainer panel and the
Azure Function can both surface what happened.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import certifi
from openai import AzureOpenAI
from pymongo import MongoClient, UpdateOne

from .config import settings
from .scraper import ScrapedPage, scrape_pages


@dataclass
class UpdateReport:
    started_at: str
    finished_at: str
    pages_scraped: int = 0
    pages_failed: int = 0
    chunks_added: int = 0
    chunks_unchanged: int = 0
    chunks_marked_stale: int = 0
    new_offer_chunks: int = 0
    new_offer_samples: list[str] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return f"❌ Update failed: {self.error}"
        return (
            f"✅ Update complete: {self.pages_scraped} pages, "
            f"{self.chunks_added} new chunks, {self.chunks_unchanged} unchanged, "
            f"{self.chunks_marked_stale} marked stale, "
            f"{self.new_offer_chunks} new offer/promotion chunks."
        )


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _translate_to_arabic(ai: AzureOpenAI, text: str) -> str:
    """GPT-based translation, identical approach to load_real_kib_data_gpt.py."""
    response = ai.chat.completions.create(
        model=settings.chat_deployment,
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate the following English text to Arabic accurately. "
                    "Output ONLY the translation, nothing else."
                ),
            },
            {"role": "user", "content": text[:3000]},
        ],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


def _embed(ai: AzureOpenAI, text: str) -> list[float]:
    return ai.embeddings.create(
        model=settings.embedding_deployment,
        input=text,
    ).data[0].embedding


_OFFER_KEYWORDS = ("offer", "promotion", "promo", "campaign", "discount", "limited")


def _looks_like_offer(url: str, text: str) -> bool:
    lower_url = url.lower()
    if "offer" in lower_url or "promotion" in lower_url:
        return True
    lower_text = text.lower()
    return any(k in lower_text for k in _OFFER_KEYWORDS)


def run_update(
    urls: Iterable[str] | None = None,
    *,
    triggered_by: str = "scheduled",
) -> UpdateReport:
    """Scrape, diff, and apply changes. Safe to call from any context."""
    started = datetime.now(timezone.utc)
    report = UpdateReport(started_at=started.isoformat(), finished_at="")

    target_urls = list(urls) if urls is not None else list(settings.scrape_urls)

    try:
        # 1) Scrape
        pages: list[ScrapedPage] = scrape_pages(target_urls)
        report.pages_scraped = len(pages)
        report.pages_failed = len(target_urls) - len(pages)

        if not pages:
            report.finished_at = datetime.now(timezone.utc).isoformat()
            report.error = "No pages could be scraped (Cloudflare may be blocking)."
            return report

        # 2) Connect once. tlsCAFile fixes Py3.13/Windows + Atlas TLS issue.
        mongo = MongoClient(settings.mongodb_url, tlsCAFile=certifi.where())
        collection = mongo[settings.mongodb_db][settings.mongodb_collection]
        ai = AzureOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_key,
            api_version=settings.azure_api_version,
        )

        # 3) Build hash sets — what we just scraped vs. what's already in DB
        fresh_by_url: dict[str, dict[str, str]] = {}  # url -> {hash: chunk_text}
        for page in pages:
            fresh_by_url[page.url] = {_hash(c): c for c in page.chunks}

        scraped_urls = list(fresh_by_url.keys())
        existing = collection.find(
            {"url": {"$in": scraped_urls}, "active": {"$ne": False}},
            {"chunk_hash": 1, "url": 1},
        )
        existing_by_url: dict[str, set[str]] = {}
        for doc in existing:
            existing_by_url.setdefault(doc.get("url", ""), set()).add(doc.get("chunk_hash", ""))

        # 4) Insert new chunks
        new_docs = []
        new_offer_samples: list[str] = []
        for url, hashes in fresh_by_url.items():
            already = existing_by_url.get(url, set())
            for h, en_text in hashes.items():
                if h in already:
                    report.chunks_unchanged += 1
                    continue

                # New chunk — translate, embed, queue insert
                ar_text = _translate_to_arabic(ai, en_text)
                en_emb = _embed(ai, en_text)
                ar_emb = _embed(ai, ar_text)

                doc = {
                    "text_en": en_text,
                    "text_ar": ar_text,
                    "embedding_en": en_emb,
                    "embedding_ar": ar_emb,
                    "url": url,
                    "chunk_hash": h,
                    "active": True,
                    "source": "phase6_scheduled_update",
                    "added_at": datetime.now(timezone.utc),
                    "triggered_by": triggered_by,
                }
                new_docs.append(doc)
                report.chunks_added += 1

                if _looks_like_offer(url, en_text):
                    report.new_offer_chunks += 1
                    if len(new_offer_samples) < 5:
                        new_offer_samples.append(f"{url}: {en_text[:140]}...")

        if new_docs:
            collection.insert_many(new_docs)

        report.new_offer_samples = new_offer_samples

        # 5) Mark stale: chunks in DB for a scraped URL whose hash is no longer present
        stale_ops: list[UpdateOne] = []
        for url, fresh_hashes in fresh_by_url.items():
            current_in_db = existing_by_url.get(url, set())
            stale_hashes = current_in_db - set(fresh_hashes.keys())
            for sh in stale_hashes:
                if not sh:
                    continue
                stale_ops.append(
                    UpdateOne(
                        {"url": url, "chunk_hash": sh},
                        {"$set": {"active": False, "marked_stale_at": datetime.now(timezone.utc)}},
                    )
                )

        if stale_ops:
            result = collection.bulk_write(stale_ops, ordered=False)
            report.chunks_marked_stale = result.modified_count

        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report

    except Exception as exc:  # noqa: BLE001 — top-level handler reports any failure
        report.finished_at = datetime.now(timezone.utc).isoformat()
        report.error = f"{type(exc).__name__}: {exc}"
        return report


if __name__ == "__main__":
    rep = run_update(triggered_by="cli")
    print(rep.summary())
    if rep.new_offer_samples:
        print("\nNew offers/promotions detected:")
        for s in rep.new_offer_samples:
            print(f"  - {s}")
