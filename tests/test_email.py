import re

from digest.models import Article, FigureAsset, Paper
from digest.notify.email import build_message


def test_cid_matches_img_src():
    paper = Paper(
        arxiv_id="2510.12345",
        title="t",
        article=Article(
            arxiv_id="2510.12345",
            headline="标题",
            lede="导语",
            problem="问题",
            method="方法",
            results="结果 84%",
            why_it_matters="原因",
            limitations="局限",
            figure_caption_zh="图注",
            matched_topics=["interpretability"],
        ),
        figure=FigureAsset(
            caption="overview",
            source="arxiv_html",
            media_type="image/jpeg",
            data=b"\xff\xd8\xff\xd9",
            cid="fig-2510.12345",
            filename="2510.12345.jpg",
        ),
    )
    html = '<html><body><img src="cid:fig-2510.12345"></body></html>'
    message = build_message(
        sender="a@example.com",
        recipients=["b@example.com"],
        subject="test",
        html=html,
        plain="plain",
        papers=[paper],
    )
    html_body = ""
    part_cids = set()
    for part in message.walk():
        if part.get_content_type() == "text/html":
            html_body = part.get_payload(decode=True).decode("utf-8")
        cid = part.get("Content-ID")
        if cid:
            part_cids.add(cid.strip().strip("<>"))
    html_cids = set(re.findall(r"cid:([^\"']+)", html_body))
    assert html_cids == part_cids == {"fig-2510.12345"}
    assert 'multipart/alternative' in message.as_string()
    assert 'multipart/related' in message.as_string()
