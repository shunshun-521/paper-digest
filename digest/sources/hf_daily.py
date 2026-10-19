"""Hugging Face Daily Papers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from digest.ids import normalize_arxiv_id
from digest.models import Paper

logger = logging.getLogger(__name__)

HF_DAILY_URL = "https://huggingface.co/api/daily_papers"
USER_AGENT = "paper-digest/1.0 (GitHub Actions; research digest)"


def parse_daily_papers(payload: bytes | str) -> list[Paper]:
    data = json.loads(payload)
    rows = data if isinstance(data, list) else data.get("papers") or data.get("items") or []
    papers: list[Paper] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        paper = row.get("paper") if isinstance(row.get("paper"), dict) else row
        raw_id = str(paper.get("id") or paper.get("arxiv_id") or "")
        arxiv_id = normalize_arxiv_id(raw_id)
        if not arxiv_id:
            continue
        authors = []
        for author in paper.get("authors") or []:
            if isinstance(author, dict) and author.get("name"):
                authors.append(str(author["name"]))
            elif isinstance(author, str):
                authors.append(author)
        upvotes = paper.get("upvotes", row.get("upvotes"))
        try:
            upvotes_n = int(upvotes) if upvotes is not None else None
        except (TypeError, ValueError):
            upvotes_n = None
        published = _parse_time(paper.get("publishedAt") or row.get("publishedAt"))
        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=str(paper.get("title") or row.get("title") or ""),
                abstract=str(paper.get("summary") or paper.get("abstract") or row.get("summary") or ""),
                authors=authors,
                published=published,
                sources=["hf_daily"],
                hf_upvotes=upvotes_n,
            )
        )
    return papers


def _parse_time(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def fetch_daily_papers(
    *,
    day: str | None = None,
    getter: Callable[[str], bytes] | None = None,
) -> list[Paper]:
    url = HF_DAILY_URL if not day else f"{HF_DAILY_URL}?date={day}"
    if getter is None:
        import httpx

        def getter(target: str) -> bytes:  # type: ignore[misc]
            with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(target)
                response.raise_for_status()
                return response.content

    return parse_daily_papers(getter(url))
