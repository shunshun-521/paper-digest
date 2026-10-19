"""arXiv API metadata and category fallback. Respect the 3 second gap."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import feedparser

from digest.ids import normalize_arxiv_id
from digest.models import Paper

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
USER_AGENT = "paper-digest/1.0 (GitHub Actions; mailto:digest@localhost)"
MAX_IDS = 50


def parse_atom(payload: bytes | str) -> list[Paper]:
    parsed = feedparser.parse(payload)
    papers: list[Paper] = []
    for entry in parsed.entries:
        raw_id = str(getattr(entry, "id", "") or "")
        arxiv_id = normalize_arxiv_id(raw_id)
        if not arxiv_id:
            continue
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        authors = [author.get("name", "") for author in getattr(entry, "authors", []) if author.get("name")]
        categories = []
        for tag in getattr(entry, "tags", []) or []:
            term = tag.get("term") if isinstance(tag, dict) else getattr(tag, "term", None)
            if term:
                categories.append(str(term))
        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=" ".join(str(getattr(entry, "title", "")).split()),
                abstract=" ".join(str(getattr(entry, "summary", "")).split()),
                authors=authors,
                categories=categories,
                published=published,
                sources=["arxiv"],
            )
        )
    return papers


class ArxivClient:
    def __init__(
        self,
        *,
        sleep_seconds: float = 3.0,
        getter: Callable[[str], bytes] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.sleep_seconds = sleep_seconds
        self._getter = getter
        self._sleeper = sleeper or time.sleep
        self._last = 0.0

    def _get(self, url: str) -> bytes:
        now = time.monotonic()
        wait = self.sleep_seconds - (now - self._last)
        if self._last and wait > 0:
            self._sleeper(wait)
        if self._getter is not None:
            payload = self._getter(url)
        else:
            import httpx

            with httpx.Client(timeout=45.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
        self._last = time.monotonic()
        return payload

    def metadata(self, arxiv_ids: list[str]) -> list[Paper]:
        papers: list[Paper] = []
        unique = list(dict.fromkeys(arxiv_ids))
        for start in range(0, len(unique), MAX_IDS):
            chunk = unique[start : start + MAX_IDS]
            url = f"{ARXIV_API}?id_list={','.join(chunk)}"
            try:
                papers.extend(parse_atom(self._get(url)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("arXiv metadata batch failed: %s", exc)
        return papers

    def recent_by_categories(self, categories: list[str], *, now: datetime | None = None) -> list[Paper]:
        if not categories:
            return []
        now = now or datetime.now(timezone.utc)
        query = "+OR+".join(f"cat:{cat}" for cat in categories)
        url = (
            f"{ARXIV_API}?search_query={query}"
            "&sortBy=submittedDate&sortOrder=descending&max_results=40"
        )
        papers = parse_atom(self._get(url))
        cutoff = now - timedelta(days=2)
        fresh: list[Paper] = []
        for paper in papers:
            if paper.published is None or paper.published >= cutoff:
                fresh.append(paper)
        return fresh
