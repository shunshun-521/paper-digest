"""Turn paper text into a structured Chinese brief."""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from pydantic import ValidationError

from digest.config import Settings
from digest.models import Article, JournalNote, Paper

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是科技新闻编辑，面向懂机器学习的研究生读者。用中文写作，风格像科技新闻，但必须准确。
要求：
- 结果中的数字必须来自原文；原文没有给出就写「论文未给出具体数字」，禁止编造
- 必须写出局限或存疑点，不能只有正面评价
- 只输出一个 JSON 对象，不要 Markdown 代码块、不要多余文字
JSON 字段：arxiv_id, headline, lede, problem, method, results, why_it_matters, limitations, figure_caption_zh, matched_topics
headline 不超过 25 个字，不夸张；lede 不超过 60 个字；problem 和 method 各 2 到 3 句；results 必须包含原文中的具体数字；why_it_matters 和 limitations 各 1 到 2 句；figure_caption_zh 一句话。
"""


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped.strip()


def parse_article(text: str) -> Article:
    payload = json.loads(strip_json_fence(text))
    if not isinstance(payload, dict):
        raise ValueError("article JSON must be an object")
    article = Article.model_validate(payload)
    article.headline = _clip(article.headline, 25)
    article.lede = _clip(article.lede, 60)
    return article


def _clip(text: str, limit: int) -> str:
    chars = list(text.strip())
    if len(chars) <= limit:
        return text.strip()
    return "".join(chars[:limit])


def fallback_article(paper: Paper, *, translated_abstract: str | None = None) -> Article:
    abstract = (translated_abstract or paper.abstract or "论文未提供摘要。").strip()
    title = paper.title.strip() or "论文速览"
    return Article(
        arxiv_id=paper.arxiv_id,
        headline=_clip(title, 25),
        lede=_clip(abstract.replace("\n", " "), 60) or "以下为摘要简版。",
        problem=abstract,
        method="完整方法解读生成失败，请直接阅读原文。",
        results="论文未给出具体数字",
        why_it_matters="自动写稿未完成，请以原文为准。",
        limitations="本条为降级简版，只有标题和摘要，缺少结构化解读。",
        figure_caption_zh="关键图说明生成失败。",
        matched_topics=list(paper.matched_topics),
        degraded=True,
    )


def article_messages(paper: Paper) -> list[dict[str, str]]:
    payload = {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "matched_topics": paper.matched_topics,
        "figure_caption": paper.figure.caption if paper.figure else "",
        "body": paper.content,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请根据下面材料写稿。只输出 JSON。\n" + json.dumps(payload, ensure_ascii=False),
        },
    ]


def write_article(paper: Paper, complete: Callable[[list[dict[str, str]]], str]) -> tuple[Article, str]:
    """Returns the article and the path actually used: full, retry, or fallback."""
    messages = article_messages(paper)
    last_error = "unknown"
    for attempt in range(2):
        try:
            raw = complete(messages)
            article = parse_article(raw)
            article.arxiv_id = paper.arxiv_id
            if not article.matched_topics:
                article.matched_topics = list(paper.matched_topics)
            if not article.results.strip():
                article.results = "论文未给出具体数字"
            return article, "full" if attempt == 0 else "retry"
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("article parse failed for %s: %s", paper.arxiv_id, exc)
            messages = article_messages(paper) + [
                {"role": "assistant", "content": "（上一次输出无法通过校验）"},
                {
                    "role": "user",
                    "content": f"校验失败：{last_error}\n请只输出一个合法 JSON 对象，不要代码块。",
                },
            ]
    translated = _translate_abstract(paper, complete)
    return fallback_article(paper, translated_abstract=translated), "fallback"


def _translate_abstract(paper: Paper, complete: Callable[[list[dict[str, str]]], str]) -> str | None:
    if not paper.abstract.strip():
        return None
    messages = [
        {
            "role": "system",
            "content": "把摘要译成准确的中文，保留数字。只输出译文，不要解释。",
        },
        {"role": "user", "content": paper.abstract[:4000]},
    ]
    try:
        text = complete(messages).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("abstract translation failed: %s", exc)
        return None
    return text or None


def journal_messages(note: JournalNote) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "用中文写 2 到 3 句期刊简讯，面向机器学习研究生。"
                "数字必须来自摘要；没有数字就不要编。只输出 JSON："
                '{"blurb":"..."}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"source": note.source, "title": note.title, "summary": note.summary[:2000]},
                ensure_ascii=False,
            ),
        },
    ]


def write_journal(note: JournalNote, complete: Callable[[list[dict[str, str]]], str]) -> str:
    try:
        raw = strip_json_fence(complete(journal_messages(note)))
        data = json.loads(raw)
        blurb = str(data.get("blurb") or "").strip()
        if blurb:
            return blurb
    except Exception as exc:  # noqa: BLE001
        logger.warning("journal blurb failed: %s", exc)
    return note.summary[:280] or note.title


def openai_complete(settings: Settings, messages: list[dict]) -> str:
    key = settings.llm.api_key()
    if not key:
        raise RuntimeError(f"missing {settings.llm.api_key_env}")
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=settings.llm.base_url)
    response = client.chat.completions.create(
        model=settings.llm.model,
        temperature=settings.llm.temperature,
        messages=messages,
    )
    return response.choices[0].message.content or ""


def openai_pick_figure(settings: Settings, captions: list[str], images: list[bytes] | None) -> str:
    key = settings.llm.api_key()
    if not key:
        raise RuntimeError(f"missing {settings.llm.api_key_env}")
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=settings.llm.base_url)
    prompt = (
        "这些图来自同一篇论文。选出最能说明方法（framework / pipeline / overview / architecture）的一张。"
        "只输出序号，从 1 开始。\n"
        + "\n".join(f"{index}. {caption}" for index, caption in enumerate(captions, start=1))
    )
    if images:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for blob in images:
            import base64

            encoded = base64.b64encode(blob).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]
    response = client.chat.completions.create(
        model=settings.llm.model,
        temperature=0,
        messages=messages,
    )
    return response.choices[0].message.content or ""
