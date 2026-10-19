"""Topic scoring, source signal, and selection."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone

from digest.config import Topic
from digest.models import JournalNote, Paper

logger = logging.getLogger(__name__)

BATCH_SIZE = 15


def _clamp_score(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(10.0, number))


def source_signal(paper: Paper, upvote_max: int) -> float:
    parts: list[float] = []
    if paper.for_you_rank is not None and paper.for_you_rank > 0:
        parts.append(max(0.0, 1.0 - (paper.for_you_rank - 1) * 0.08))
    if paper.hot_rank is not None and paper.hot_rank > 0:
        parts.append(max(0.0, 1.0 - (paper.hot_rank - 1) * 0.04))
    if paper.hf_upvotes is not None:
        denom = max(upvote_max, 1)
        parts.append(max(0.0, min(1.0, paper.hf_upvotes / denom)))
    base = max(parts) if parts else 0.15
    if len(paper.sources) >= 2:
        base = min(1.0, base + 0.15)
    return base


def recency_score(paper: Paper, today: date) -> float:
    if paper.published is None:
        return 0.45
    published = paper.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days = (today - published.date()).days
    if days <= 1:
        return 1.0
    if days <= 2:
        return 0.8
    if days <= 7:
        return 0.55
    if days <= 30:
        return 0.3
    return 0.1


def apply_scores(
    papers: list[Paper],
    topics: list[Topic],
    today: date,
) -> None:
    default_ids = [topic.id for topic in topics if topic.default]
    all_ids = [topic.id for topic in topics]
    upvote_max = max([paper.hf_upvotes or 0 for paper in papers], default=0)
    for paper in papers:
        for topic_id in all_ids:
            paper.topic_scores.setdefault(topic_id, 0.0)
            paper.topic_scores[topic_id] = _clamp_score(paper.topic_scores.get(topic_id, 0.0))
        paper.matched_topics = [
            topic_id for topic_id, score in paper.topic_scores.items() if score >= 6
        ]
        email_rel = max((paper.topic_scores.get(topic_id, 0.0) for topic_id in default_ids), default=0.0) / 10.0
        web_rel = max((paper.topic_scores.get(topic_id, 0.0) for topic_id in all_ids), default=0.0) / 10.0
        signal = source_signal(paper, upvote_max)
        recency = recency_score(paper, today)
        paper.source_signal = signal
        paper.recency = recency
        paper.email_score = 0.65 * email_rel + 0.25 * signal + 0.10 * recency
        paper.web_score = 0.65 * web_rel + 0.25 * signal + 0.10 * recency


def select_email_papers(papers: list[Paper], limit: int, default_ids: list[str]) -> list[Paper]:
    def matched(paper: Paper) -> bool:
        return any(topic_id in paper.matched_topics for topic_id in default_ids)

    ranked = sorted(papers, key=lambda paper: paper.email_score, reverse=True)
    preferred = [paper for paper in ranked if matched(paper)]
    others = [paper for paper in ranked if paper not in preferred]
    return (preferred + others)[:limit]


def select_page_papers(papers: list[Paper], email_papers: list[Paper], limit: int) -> list[Paper]:
    ranked = sorted(papers, key=lambda paper: paper.web_score, reverse=True)
    chosen: list[Paper] = []
    seen: set[str] = set()
    for paper in email_papers + ranked:
        if paper.arxiv_id in seen:
            continue
        chosen.append(paper)
        seen.add(paper.arxiv_id)
        if len(chosen) >= limit:
            break
    return chosen


def score_journals(notes: list[JournalNote], topics: list[Topic], limit: int) -> list[JournalNote]:
    default_ids = [topic.id for topic in topics if topic.default] or [topic.id for topic in topics]

    def relevance(note: JournalNote) -> float:
        return max((note.topic_scores.get(topic_id, 0.0) for topic_id in default_ids), default=0.0)

    ranked = sorted(notes, key=relevance, reverse=True)
    kept = [note for note in ranked if relevance(note) >= 6]
    if len(kept) < limit:
        for note in ranked:
            if note not in kept:
                kept.append(note)
            if len(kept) >= limit:
                break
    return kept[:limit]


def parse_score_payload(text: str) -> dict[str, dict[str, float]]:
    cleaned = _strip_fence(text)
    data = json.loads(cleaned)
    rows = data.get("scores", data if isinstance(data, list) else [])
    parsed: dict[str, dict[str, float]] = {}
    if isinstance(data, dict) and "scores" not in data and _looks_like_score_map(data):
        rows = [{"arxiv_id": key, "topics": value} for key, value in data.items()]
    for row in rows:
        if not isinstance(row, dict):
            continue
        arxiv_id = str(row.get("arxiv_id") or row.get("id") or "")
        topics = row.get("topics") or row.get("scores") or {}
        if not arxiv_id or not isinstance(topics, dict):
            continue
        parsed[arxiv_id] = {str(key): _clamp_score(value) for key, value in topics.items()}
    return parsed


def _looks_like_score_map(data: dict) -> bool:
    return all(isinstance(value, dict) for value in data.values())


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def scoring_messages(papers: list[Paper], topics: list[Topic]) -> list[dict[str, str]]:
    topic_lines = "\n".join(
        f"- {topic.id}: {topic.name}. {topic.description.strip()}" for topic in topics
    )
    paper_lines = []
    for paper in papers:
        paper_lines.append(
            json.dumps(
                {
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "abstract": paper.abstract[:1500],
                },
                ensure_ascii=False,
            )
        )
    system = (
        "你是论文编辑。根据标题和摘要，为每篇论文对每个主题打 0 到 10 分，"
        "10 表示高度相关。只输出一个 JSON 对象，不要 Markdown。"
        '格式：{"scores":[{"arxiv_id":"...","topics":{"topic_id":8}}]}'
    )
    user = f"主题：\n{topic_lines}\n\n论文：\n" + "\n".join(paper_lines)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def assign_topic_scores(
    papers: list[Paper],
    topics: list[Topic],
    complete,
) -> list[str]:
    """Call ``complete(messages) -> str`` in batches. Returns warnings."""
    warnings: list[str] = []
    if not papers or not topics:
        return warnings
    for start in range(0, len(papers), BATCH_SIZE):
        batch = papers[start : start + BATCH_SIZE]
        messages = scoring_messages(batch, topics)
        try:
            raw = complete(messages)
            parsed = parse_score_payload(raw)
        except Exception as exc:  # noqa: BLE001 - one batch must not stop the run
            logger.warning("topic scoring failed: %s", exc)
            warnings.append(f"topic scoring batch {start}: {exc}")
            continue
        by_id = {paper.arxiv_id: paper for paper in batch}
        for arxiv_id, scores in parsed.items():
            paper = by_id.get(arxiv_id)
            if paper is None:
                continue
            paper.topic_scores.update(scores)
    return warnings


def journal_scoring_messages(notes: list[JournalNote], topics: list[Topic]) -> list[dict[str, str]]:
    fake_papers = [
        Paper(arxiv_id=note.url or note.title, title=note.title, abstract=note.summary)
        for note in notes
    ]
    return scoring_messages(fake_papers, topics)


def published_date(value: datetime | None, today: date) -> date:
    if value is None:
        return today
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date()
