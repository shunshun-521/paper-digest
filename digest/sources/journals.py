"""Journal RSS items from the last 48 hours."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import feedparser

from digest.config import JournalFeed
from digest.models import JournalNote

logger = logging.getLogger(__name__)
USER_AGENT = "paper-digest/1.0 (GitHub Actions; research digest)"


def parse_feed(name: str, payload: bytes | str, *, now: datetime, max_age: timedelta) -> list[JournalNote]:
    parsed = feedparser.parse(payload)
    notes: list[JournalNote] = []
    for entry in parsed.entries:
        published = None
        stamp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if stamp:
            published = datetime(*stamp[:6], tzinfo=timezone.utc)
        if published is not None and now - published > max_age:
            continue
        if published is None:
            # Undated items are kept only when the feed itself is fresh enough to be useful;
            # skip them so an old undated feed cannot flood the column.
            continue
        title = " ".join(str(getattr(entry, "title", "")).split())
        summary = " ".join(str(getattr(entry, "summary", "")).split())
        url = str(getattr(entry, "link", "") or "")
        if not title:
            continue
        notes.append(
            JournalNote(source=name, title=title, url=url, summary=summary, published=published)
        )
    return notes


def fetch_journals(
    feeds: list[JournalFeed],
    *,
    now: datetime | None = None,
    getter: Callable[[str], bytes] | None = None,
    max_age_hours: int = 48,
) -> tuple[list[JournalNote], list[str]]:
    now = now or datetime.now(timezone.utc)
    max_age = timedelta(hours=max_age_hours)
    warnings: list[str] = []
    notes: list[JournalNote] = []
    for feed in feeds:
        try:
            if getter is None:
                import httpx

                with httpx.Client(
                    timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
                ) as client:
                    response = client.get(feed.url)
                    response.raise_for_status()
                    payload: bytes | str = response.content
            else:
                payload = getter(feed.url)
            parsed = feedparser.parse(payload)
            if getattr(parsed, "bozo", False) and not parsed.entries:
                warnings.append(f"journal {feed.name}: unreadable feed")
                continue
            notes.extend(parse_feed(feed.name, payload, now=now, max_age=max_age))
        except Exception as exc:  # noqa: BLE001
            logger.warning("journal %s failed: %s", feed.name, exc)
            warnings.append(f"journal {feed.name}: {exc}")
    return notes, warnings
