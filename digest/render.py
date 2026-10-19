"""Render the email, the daily page, and the archive index."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from digest.config import Topic
from digest.models import JournalNote, Paper, RunStatus


def build_status_line(status: RunStatus) -> str:
    def mark(label: str, key: str) -> str:
        health = status.source_health.get(key, "skipped")
        if health == "ok":
            return f"{label} ✓"
        return f"{label} ⚠"

    content = f"正文 {status.content_alphaxiv}/{status.content_total} 来自 alphaXiv"
    if status.content_total and status.content_alphaxiv < status.content_total:
        content += " ⚠"
    figures = f"图片 {status.figures_ok}/{status.figures_total}"
    if status.figures_total and status.figures_ok < status.figures_total:
        figures += " ⚠"
    return " · ".join(
        [
            mark("For You", "alphaxiv_for_you"),
            mark("Hot", "alphaxiv_hot"),
            content,
            figures,
        ]
    )


def _env(root: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(root / "templates")),
        autoescape=select_autoescape(["html", "j2"]),
    )


def render_email(
    *,
    root: Path,
    day: date,
    papers: list[Paper],
    journals: list[JournalNote],
    status: RunStatus,
    topics: list[Topic],
    site_url: str,
) -> tuple[str, str]:
    names = {topic.id: topic.name for topic in topics}
    html = _env(root).get_template("email.html.j2").render(
        day=day,
        papers=papers,
        journals=journals,
        status_line=status.status_line,
        topic_names=names,
        site_url=site_url.rstrip("/"),
    )
    plain_lines = [f"论文日报 {day.isoformat()}", ""]
    for index, paper in enumerate(papers, start=1):
        article = paper.article
        headline = article.headline if article else paper.title
        plain_lines.append(f"{index}. {headline}")
        if article:
            plain_lines.extend(
                [
                    article.lede,
                    f"问题：{article.problem}",
                    f"方法：{article.method}",
                    f"结果：{article.results}",
                    f"为什么重要：{article.why_it_matters}",
                    f"局限：{article.limitations}",
                    f"https://arxiv.org/abs/{paper.arxiv_id}",
                    "",
                ]
            )
    if journals:
        plain_lines.append("期刊")
        for note in journals:
            plain_lines.append(f"- {note.source}: {note.title}")
    plain_lines.append(status.status_line)
    return html, "\n".join(plain_lines)


def render_page(
    *,
    root: Path,
    day: date,
    papers: list[Paper],
    journals: list[JournalNote],
    status: RunStatus,
    topics: list[Topic],
    papers_per_day: int,
    site_url: str,
) -> str:
    names = {topic.id: topic.name for topic in topics}
    return _env(root).get_template("page.html.j2").render(
        day=day,
        papers=papers,
        journals=journals,
        status_line=status.status_line,
        topics=topics,
        topic_names=names,
        papers_per_day=papers_per_day,
        site_url=site_url.rstrip("/"),
    )


def render_index(*, root: Path, days: list[str]) -> str:
    return _env(root).get_template("index.html.j2").render(days=days)


def list_archive_days(site_dir: Path, extra: str | None = None) -> list[str]:
    days = set()
    if site_dir.exists():
        for child in site_dir.iterdir():
            if child.is_dir() and len(child.name) == 10 and child.name[4] == "-":
                days.add(child.name)
    if extra:
        days.add(extra)
    return sorted(days, reverse=True)


def write_site(
    *,
    root: Path,
    site_dir: Path,
    day: date,
    page_html: str,
    papers: list[Paper],
) -> None:
    day_dir = site_dir / day.isoformat()
    image_dir = day_dir / "img"
    image_dir.mkdir(parents=True, exist_ok=True)
    for paper in papers:
        if paper.figure and paper.figure.data:
            (image_dir / paper.figure.filename).write_bytes(paper.figure.data)
    (day_dir / "index.html").write_text(page_html, encoding="utf-8")
    index = render_index(root=root, days=list_archive_days(site_dir, day.isoformat()))
    (site_dir / "index.html").write_text(index, encoding="utf-8")
