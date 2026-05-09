"""
KIB website scraper — refactored from scrape_kib_discover.py into a callable
function so it can run from an Azure Function, a Streamlit "AI Trainer" button,
or the command line.

Uses the same approach your friend confirmed works:
  * curl_cffi with impersonate="chrome120" to bypass Cloudflare
  * BeautifulSoup to strip script/style tags
  * 400-word chunking
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from curl_cffi import requests


@dataclass
class ScrapedPage:
    url: str
    text: str
    chunks: list[str] = field(default_factory=list)


def _fetch(url: str, *, timeout: int = 30) -> str | None:
    """Fetch a single URL. Returns the HTML body or None on failure."""
    try:
        response = requests.get(url, impersonate="chrome120", timeout=timeout)
    except Exception:
        return None
    if response.status_code != 200 or len(response.text) < 5000:
        return None
    return response.text


def _clean(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def _chunk(text: str, chunk_size: int = 400) -> list[str]:
    """Split text into ~chunk_size-word chunks (matches your friend's loader)."""
    words = text.split()
    return [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]


def scrape_pages(urls: list[str] | tuple[str, ...], *, min_chunk_chars: int = 100) -> list[ScrapedPage]:
    """Scrape a list of URLs and return a ScrapedPage per successful fetch.

    Args:
        urls: Absolute URLs to fetch.
        min_chunk_chars: Drop chunks shorter than this (matches the loader).
    """
    pages: list[ScrapedPage] = []
    for url in urls:
        html = _fetch(url)
        if html is None:
            continue
        text = _clean(html)
        chunks = [c for c in _chunk(text) if len(c.strip()) >= min_chunk_chars]
        if not chunks:
            continue
        pages.append(ScrapedPage(url=url, text=text, chunks=chunks))
    return pages


if __name__ == "__main__":
    from .config import settings

    print(f"Scraping {len(settings.scrape_urls)} URLs...")
    results = scrape_pages(list(settings.scrape_urls))
    for p in results:
        print(f"  ✅ {p.url} — {len(p.chunks)} chunks ({len(p.text)} chars)")
    print(f"\nTotal: {len(results)} pages")
