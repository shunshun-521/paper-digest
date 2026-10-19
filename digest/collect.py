"""Merge multi-source candidates and apply the fallback order."""

from __future__ import annotations

from digest.models import Paper, RunStatus

SOURCE_ORDER = (
    "alphaxiv_for_you",
    "alphaxiv_hot",
    "hf_daily",
    "arxiv",
)


def merge_papers(papers: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    for paper in papers:
        current = merged.get(paper.arxiv_id)
        if current is None:
            merged[paper.arxiv_id] = paper.model_copy(deep=True)
            continue
        for source in paper.sources:
            if source not in current.sources:
                current.sources.append(source)
        if paper.title and not current.title:
            current.title = paper.title
        if paper.abstract and len(paper.abstract) > len(current.abstract):
            current.abstract = paper.abstract
        if paper.authors and not current.authors:
            current.authors = list(paper.authors)
        if paper.categories and not current.categories:
            current.categories = list(paper.categories)
        if paper.published and (current.published is None or paper.published < current.published):
            current.published = paper.published
        if paper.for_you_rank is not None:
            current.for_you_rank = (
                paper.for_you_rank
                if current.for_you_rank is None
                else min(current.for_you_rank, paper.for_you_rank)
            )
        if paper.hot_rank is not None:
            current.hot_rank = (
                paper.hot_rank if current.hot_rank is None else min(current.hot_rank, paper.hot_rank)
            )
        if paper.hf_upvotes is not None:
            current.hf_upvotes = max(current.hf_upvotes or 0, paper.hf_upvotes)
    return list(merged.values())


def _unseen(papers: list[Paper], seen: set[str]) -> list[Paper]:
    return [paper for paper in papers if paper.arxiv_id not in seen]


def choose_candidate_pool(
    by_source: dict[str, list[Paper]],
    seen: set[str],
    *,
    source_errors: dict[str, str] | None = None,
    source_health: dict[str, str] | None = None,
) -> tuple[list[Paper], RunStatus]:
    """Select candidates.

    For You, Hot and Hugging Face are fetched together so the same paper can
    carry heat from more than one source. The reported path is the highest
    source that still has papers not present in ``seen``. The arXiv category
    list is used only when those three sources contribute nothing new.
    """
    errors = source_errors or {}
    health = dict(source_health or {})
    fresh = {name: _unseen(by_source.get(name) or [], seen) for name in SOURCE_ORDER}

    primary = "none"
    reason = "all candidate sources returned 0 new papers"
    if fresh["alphaxiv_for_you"]:
        primary = "alphaxiv_for_you"
        reason = ""
    elif fresh["alphaxiv_hot"]:
        primary = "alphaxiv_hot"
        reason = "for_you returned 0 new papers"
    elif fresh["hf_daily"]:
        primary = "hf_daily"
        reason = "for_you and hot returned 0 new papers"
    elif fresh["arxiv"]:
        primary = "arxiv"
        reason = "alphaxiv and huggingface returned 0 new papers"

    include = ["alphaxiv_for_you", "alphaxiv_hot", "hf_daily"]
    if primary == "arxiv":
        include.append("arxiv")
    if primary == "none":
        include = []

    combined = [paper for name in include for paper in (by_source.get(name) or [])]
    pool = _unseen(merge_papers(combined), seen)

    status = RunStatus(
        candidates=primary,
        fallback_reason=reason,
        source_health=health,
        warnings=[f"{name}: {message}" for name, message in errors.items()],
        paths={"candidates": primary},
    )
    if reason:
        status.paths["fallback_reason"] = reason
    return pool, status
