from digest.models import Paper
from digest.writer import parse_article, write_article

GOOD = {
    "arxiv_id": "2510.10001",
    "headline": "激活向量能改模型人设",
    "lede": "推理时加上引导向量，人设准确率从 61% 升到 84%。",
    "problem": "微调人设太贵。作者改用推理时干预。",
    "method": "取两种人设的激活差，生成时加回去。",
    "results": "准确率从 61% 升到 84%，MMLU 下降 1.2 分。",
    "why_it_matters": "人设可以变成一条可加减的方向。",
    "limitations": "标签很吵，涨幅未必稳定。",
    "figure_caption_zh": "引导向量加到残差流上。",
    "matched_topics": ["interpretability"],
}


def test_fenced_article_json():
    text = "```json\n" + __import__("json").dumps(GOOD, ensure_ascii=False) + "\n```"
    article = parse_article(text)
    assert article.headline == GOOD["headline"]
    assert article.results.startswith("准确率")


def test_retry_then_success():
    calls = {"n": 0}

    def complete(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "sure, here is the story"
        return __import__("json").dumps(GOOD, ensure_ascii=False)

    paper = Paper(arxiv_id="2510.10001", title="t", abstract="a", matched_topics=["interpretability"])
    article, path = write_article(paper, complete)
    assert path == "retry"
    assert article.degraded is False
    assert calls["n"] == 2


def test_missing_fields_fall_back():
    def complete(_messages):
        return '{"arxiv_id":"2510.10001"}'

    paper = Paper(
        arxiv_id="2510.10001",
        title="A very long English title about steering vectors",
        abstract="Accuracy rose from 61% to 84%.",
        matched_topics=["interpretability"],
    )
    article, path = write_article(paper, complete)
    assert path == "fallback"
    assert article.degraded is True
    assert article.results == "论文未给出具体数字"
    assert article.arxiv_id == "2510.10001"
