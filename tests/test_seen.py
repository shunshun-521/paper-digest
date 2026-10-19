from digest.models import Paper
from digest.state import load_seen, save_seen


def test_seen_roundtrip(tmp_path):
    path = tmp_path / "seen.json"
    save_seen(path, {"2510.10001", "2510.10002"})
    assert load_seen(path) == {"2510.10001", "2510.10002"}


def test_missing_seen_is_empty(tmp_path):
    assert load_seen(tmp_path / "seen.json") == set()


def test_filter_matches_pipeline_ids():
    seen = load_seen_ids = {"2510.10001"}
    papers = [Paper(arxiv_id="2510.10001"), Paper(arxiv_id="2510.10002")]
    fresh = [paper for paper in papers if paper.arxiv_id not in seen]
    assert [paper.arxiv_id for paper in fresh] == ["2510.10002"]
    assert load_seen_ids
