import json
from datetime import date, datetime, timezone

from digest.config import Topic
from digest.models import Paper
from digest.rank import apply_scores, parse_score_payload, source_signal


def test_fenced_score_json():
    raw = """```json
{"scores":[{"arxiv_id":"2510.10001","topics":{"interpretability":8}}]}
```"""
    assert parse_score_payload(raw)["2510.10001"]["interpretability"] == 8


def test_score_weights():
    paper = Paper(
        arxiv_id="2510.10001",
        sources=["alphaxiv_for_you"],
        for_you_rank=1,
        published=datetime(2026, 10, 18, tzinfo=timezone.utc),
        topic_scores={"interpretability": 8, "agents": 1},
    )
    topics = [
        Topic(id="interpretability", name="可解释性", default=True, description="interpretability"),
        Topic(id="agents", name="智能体", default=False, description="agents"),
    ]
    apply_scores([paper], topics, date(2026, 10, 19))
    signal = source_signal(paper, 0)
    assert paper.email_score == 0.65 * 0.8 + 0.25 * signal + 0.10 * 1.0
    assert "interpretability" in paper.matched_topics
    assert "agents" not in paper.matched_topics
    assert paper.web_score == paper.email_score


def test_bad_score_json_raises():
    try:
        parse_score_payload("not json")
    except json.JSONDecodeError:
        return
    raise AssertionError("expected JSON error")
