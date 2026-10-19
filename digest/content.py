"""Fetch paper text with a fixed fallback order."""

from __future__ import annotations

import logging
import re
from typing import Callable

from bs4 import BeautifulSoup

from digest.models import Paper

logger = logging.getLogger(__name__)

USER_AGENT = "paper-digest/1.0 (GitHub Actions; research digest)"
HEADING_HINTS = (
    "abstract",
    "摘要",
    "introduction",
    "引言",
    "method",
    "方法",
    "approach",
    "experiment",
    "实验",
    "result",
    "结果",
    "conclusion",
    "结论",
    "discussion",
)


def trim_for_llm(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    parts = re.split(r"\n(?=#{1,3}\s|\d+\.\s|[A-Z][A-Za-z /]{3,40}\n)", text)
    picked = []
    for part in parts:
        head = part[:120].lower()
        if any(hint in head for hint in HEADING_HINTS):
            picked.append(part.strip())
    body = "\n\n".join(picked) if picked else text
    if len(body) > limit:
        body = body[:limit]
    return body


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    article = soup.find("article") or soup.body or soup
    return re.sub(r"\n{3,}", "\n\n", article.get_text("\n", strip=True))


def arxiv_html_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/html/{arxiv_id}"


def fetch_content_for_paper(
    paper: Paper,
    *,
    alphaxiv_text: str | None,
    html_getter: Callable[[str], str] | None,
    max_chars: int,
) -> tuple[str, str]:
    """Return (text, source_name). source_name is alphaxiv, arxiv_html, or abstract."""
    if alphaxiv_text and len(alphaxiv_text.strip()) > 80:
        return trim_for_llm(alphaxiv_text.strip(), max_chars), "alphaxiv"
    if html_getter is not None:
        try:
            html = html_getter(arxiv_html_url(paper.arxiv_id))
            text = html_to_text(html)
            if len(text) > 200:
                return trim_for_llm(text, max_chars), "arxiv_html"
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv HTML failed for %s: %s", paper.arxiv_id, exc)
    abstract = paper.abstract.strip() or paper.title
    return trim_for_llm(abstract, max_chars), "abstract"


def default_html_getter(url: str) -> str:
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text
