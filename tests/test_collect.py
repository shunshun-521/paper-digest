from digest.collect import choose_candidate_pool
from digest.models import Paper


def _paper(arxiv_id: str, source: str, **kwargs) -> Paper:
    title = kwargs.pop("title", arxiv_id)
    return Paper(arxiv_id=arxiv_id, title=title, sources=[source], **kwargs)


def test_for_you_empty_falls_back_to_hot():
    pool, status = choose_candidate_pool(
        {
            "alphaxiv_for_you": [],
            "alphaxiv_hot": [_paper("2510.20001", "alphaxiv_hot", hot_rank=1)],
            "hf_daily": [_paper("2510.20002", "hf_daily", hf_upvotes=3)],
        },
        set(),
    )
    assert status.candidates == "alphaxiv_hot"
    assert "for_you returned 0 new papers" in status.fallback_reason
    assert {paper.arxiv_id for paper in pool} == {"2510.20001", "2510.20002"}


def test_all_empty_falls_back_to_hf_then_arxiv():
    pool, status = choose_candidate_pool(
        {
            "alphaxiv_for_you": [],
            "alphaxiv_hot": [],
            "hf_daily": [_paper("2510.30001", "hf_daily")],
            "arxiv": [_paper("2510.30002", "arxiv")],
        },
        set(),
    )
    assert status.candidates == "hf_daily"
    assert {paper.arxiv_id for paper in pool} == {"2510.30001"}

    pool, status = choose_candidate_pool(
        {
            "alphaxiv_for_you": [],
            "alphaxiv_hot": [],
            "hf_daily": [],
            "arxiv": [_paper("2510.30002", "arxiv")],
        },
        set(),
    )
    assert status.candidates == "arxiv"
    assert [paper.arxiv_id for paper in pool] == ["2510.30002"]


def test_seen_ids_are_removed_and_can_force_fallback():
    seen = {"2510.40001"}
    pool, status = choose_candidate_pool(
        {
            "alphaxiv_for_you": [_paper("2510.40001", "alphaxiv_for_you", for_you_rank=1)],
            "alphaxiv_hot": [_paper("2510.40002", "alphaxiv_hot", hot_rank=1)],
        },
        seen,
    )
    assert status.candidates == "alphaxiv_hot"
    assert [paper.arxiv_id for paper in pool] == ["2510.40002"]


def test_multi_source_merge_keeps_heat():
    pool, _status = choose_candidate_pool(
        {
            "alphaxiv_for_you": [_paper("2510.50001", "alphaxiv_for_you", for_you_rank=1, title="A")],
            "alphaxiv_hot": [_paper("2510.50001", "alphaxiv_hot", hot_rank=4)],
            "hf_daily": [_paper("2510.50001", "hf_daily", hf_upvotes=12, abstract="longer abstract")],
        },
        set(),
    )
    assert len(pool) == 1
    paper = pool[0]
    assert set(paper.sources) == {"alphaxiv_for_you", "alphaxiv_hot", "hf_daily"}
    assert paper.for_you_rank == 1
    assert paper.hot_rank == 4
    assert paper.hf_upvotes == 12
    assert paper.abstract == "longer abstract"
