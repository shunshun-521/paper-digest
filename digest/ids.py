"""Extract normalized arXiv IDs from messy tool output."""

from __future__ import annotations

import json
import re
from typing import Any

# New-style ids: 2510.12345 or 2510.12345v2. Version suffix is stripped.
ARXIV_ID_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)


def normalize_arxiv_id(value: str) -> str | None:
    match = ARXIV_ID_RE.search(value.strip())
    if not match:
        return None
    return match.group(1)


def extract_arxiv_ids(payload: str | None) -> list[str]:
    """Pull arXiv IDs from JSON text or plain text. Order is preserved."""
    if not payload or not str(payload).strip():
        return []
    text = str(payload).strip()
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        if raw is None:
            return
        normalized = normalize_arxiv_id(str(raw))
        if normalized and normalized not in seen:
            seen.add(normalized)
            found.append(normalized)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in {
                    "id",
                    "arxiv_id",
                    "arxivid",
                    "paper_id",
                    "paperid",
                    "arxiv",
                } and not isinstance(value, (dict, list)):
                    add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in ARXIV_ID_RE.finditer(node):
                add(match.group(0))

    try:
        walk(json.loads(text))
    except json.JSONDecodeError:
        for match in ARXIV_ID_RE.finditer(text):
            add(match.group(0))
    if not found:
        for match in ARXIV_ID_RE.finditer(text):
            add(match.group(0))
    return found
