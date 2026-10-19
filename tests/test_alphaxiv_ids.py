from pathlib import Path

from digest.ids import extract_arxiv_ids
from digest.sources.alphaxiv import build_tool_arguments

FIXTURES = Path(__file__).parent / "fixtures"


def test_json_ids_strip_version():
    payload = (FIXTURES / "alphaxiv_json.txt").read_text(encoding="utf-8")
    assert extract_arxiv_ids(payload) == ["2510.12345", "2510.99999"]


def test_plain_text_ids():
    text = (FIXTURES / "alphaxiv_text.txt").read_text(encoding="utf-8")
    assert extract_arxiv_ids(text) == ["2510.11111", "2510.22222"]


def test_empty_payload():
    assert extract_arxiv_ids((FIXTURES / "alphaxiv_empty.txt").read_text(encoding="utf-8")) == []
    assert extract_arxiv_ids("") == []
    assert extract_arxiv_ids("nothing here") == []


def test_feed_args_follow_schema():
    schema = {"type": "object", "properties": {"max_results": {"type": "integer", "maximum": 20}}}
    args = build_tool_arguments(schema, kind="feed")
    assert args == {"max_results": 20}
    assert "limit" not in args


def test_content_args_use_schema_key():
    schema = {"type": "object", "properties": {"paper_id": {"type": "string"}}, "required": ["paper_id"]}
    args = build_tool_arguments(schema, kind="content", arxiv_id="2510.12345")
    assert args == {"paper_id": "2510.12345"}
