"""Shared data models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Article(BaseModel):
    arxiv_id: str
    headline: str
    lede: str
    problem: str
    method: str
    results: str
    why_it_matters: str
    limitations: str
    figure_caption_zh: str
    matched_topics: list[str] = Field(default_factory=list)
    degraded: bool = False


class FigureAsset(BaseModel):
    caption: str = ""
    source: str = ""
    media_type: str = "image/jpeg"
    data: bytes = Field(default=b"", exclude=True)
    cid: str = ""
    filename: str = ""

    model_config = {"arbitrary_types_allowed": True}


class Paper(BaseModel):
    arxiv_id: str
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    published: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    for_you_rank: int | None = None
    hot_rank: int | None = None
    hf_upvotes: int | None = None
    topic_scores: dict[str, float] = Field(default_factory=dict)
    matched_topics: list[str] = Field(default_factory=list)
    email_score: float = 0.0
    web_score: float = 0.0
    source_signal: float = 0.0
    recency: float = 0.0
    content: str = ""
    content_source: str = ""
    article: Article | None = None
    figure: FigureAsset | None = None

    model_config = {"arbitrary_types_allowed": True}


class JournalNote(BaseModel):
    source: str
    title: str
    url: str
    summary: str = ""
    published: datetime | None = None
    blurb: str = ""
    topic_scores: dict[str, float] = Field(default_factory=dict)


class RunStatus(BaseModel):
    candidates: str = "none"
    fallback_reason: str = ""
    paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    source_health: dict[str, str] = Field(default_factory=dict)
    content_alphaxiv: int = 0
    content_total: int = 0
    figures_ok: int = 0
    figures_total: int = 0
    paper_count: int = 0
    status_line: str = ""
    per_paper: dict[str, dict[str, str]] = Field(default_factory=dict)
