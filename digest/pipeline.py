"""End-to-end daily digest."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from digest.collect import choose_candidate_pool
from digest.config import Settings, Topic, env, load_feeds, load_settings, load_topics, repo_root
from digest.content import arxiv_html_url, default_html_getter, fetch_content_for_paper
from digest.figures import (
    FigureCandidate,
    figures_from_html,
    figures_from_latex,
    figures_from_pdf,
    first_available,
    normalize_image,
    parse_choice,
    preview_png,
    select_by_caption,
    unpack_eprint,
)
from digest.models import FigureAsset, JournalNote, Paper, RunStatus
from digest.notify.email import build_message, send_email, shrink_figures_if_needed, subject_for
from digest.notify.wechat import failure_notice, send_wechat
from digest.rank import apply_scores, assign_topic_scores, score_journals, select_email_papers, select_page_papers
from digest.render import build_status_line, render_email, render_page, write_site
from digest.sources.arxiv_api import ArxivClient
from digest.sources.hf_daily import fetch_daily_papers
from digest.sources.journals import fetch_journals
from digest.state import load_seen, save_seen, write_archive
from digest.writer import openai_complete, openai_pick_figure, write_article, write_journal

logger = logging.getLogger(__name__)


def run(
    *,
    dry_run: bool = False,
    on_date: str | None = None,
    root: Path | None = None,
    out_dir: Path | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = root or repo_root()
    settings = load_settings(root)
    topics = load_topics(root)
    feeds = load_feeds(root)
    day = date.fromisoformat(on_date) if on_date else datetime.now(ZoneInfo(settings.timezone)).date()
    destination = out_dir or (root / "out" if dry_run else root / "site")
    destination.mkdir(parents=True, exist_ok=True)

    if dry_run:
        code, status, email_papers, page_papers, journals = _run_dry(
            root=root,
            settings=settings,
            topics=topics,
            day=day,
            destination=destination,
        )
    else:
        code, status, email_papers, page_papers, journals = asyncio.run(
            _run_live(
                root=root,
                settings=settings,
                topics=topics,
                feeds=feeds,
                day=day,
                now=datetime.now(ZoneInfo(settings.timezone)),
                destination=destination,
            )
        )
    logger.info("今日数据源状态：%s", status.status_line)
    logger.info("exit %s, papers %s", code, len(email_papers))
    return code


def _run_dry(root, settings, topics, day, destination):
    bundle_path = root / "tests" / "fixtures" / "dry_run.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    papers = [Paper.model_validate(item) for item in bundle["papers"]]
    for paper in papers:
        for topic_id, score in bundle["scores"].get(paper.arxiv_id, {}).items():
            paper.topic_scores[topic_id] = score
    seen = load_seen(root / "data" / "seen.json")
    by_source: dict[str, list[Paper]] = {
        "alphaxiv_for_you": [],
        "alphaxiv_hot": [],
        "hf_daily": [],
        "arxiv": [],
    }
    for paper in papers:
        for source in paper.sources:
            clone = paper.model_copy(deep=True)
            clone.sources = [source]
            by_source.setdefault(source, []).append(clone)
    health = {
        "alphaxiv_for_you": "ok",
        "alphaxiv_hot": "ok",
        "hf_daily": "ok",
    }
    pool, status = choose_candidate_pool(by_source, seen, source_health=health)
    apply_scores(pool, topics, day)
    default_ids = [topic.id for topic in topics if topic.default]
    email_papers = select_email_papers(pool, settings.papers_per_day, default_ids)
    page_papers = select_page_papers(
        pool, email_papers, settings.candidates_on_page, [topic.id for topic in topics]
    )

    def html_getter(url: str) -> str:
        arxiv_id = url.rstrip("/").split("/")[-1]
        return (
            "<html><body><article><p>Dry-run full text.</p></article>"
            f"<figure><img src='overview.png'><figcaption>Method overview for {arxiv_id}</figcaption></figure>"
            "</body></html>"
        )

    def fetch_image(url: str) -> bytes:
        return preview_png(url)

    articles = bundle["articles"]
    for paper in page_papers:
        text, source = fetch_content_for_paper(
            paper,
            alphaxiv_text=bundle["contents"].get(paper.arxiv_id),
            html_getter=html_getter,
            max_chars=settings.llm.max_input_chars,
        )
        paper.content = text
        paper.content_source = source
        _attach_figure(
            paper,
            settings,
            html_getter,
            fetch_image,
            use_network_pdf=False,
            allow_llm=False,
        )
        raw = json.dumps(articles[paper.arxiv_id], ensure_ascii=False)
        article, path = write_article(paper, lambda _messages, raw=raw: raw)
        paper.article = article
        status.per_paper[paper.arxiv_id] = {"content": source, "writer": path, "figure": paper.figure.source if paper.figure else "none"}

    journals = [JournalNote.model_validate(item) for item in bundle.get("journals", [])]
    _finalize_status(status, email_papers, page_papers)
    _emit(
        root=root,
        settings=settings,
        topics=topics,
        day=day,
        email_papers=email_papers,
        page_papers=page_papers,
        journals=journals,
        status=status,
        destination=destination,
        dry_run=True,
    )
    return (0 if email_papers else 1), status, email_papers, page_papers, journals


async def _run_live(root, settings, topics, feeds, day, now, destination):
    by_source: dict[str, list[Paper]] = {
        "alphaxiv_for_you": [],
        "alphaxiv_hot": [],
        "hf_daily": [],
        "arxiv": [],
    }
    health: dict[str, str] = {}
    errors: dict[str, str] = {}
    alphaxiv_key = env("ALPHAXIV_API_KEY")
    client = None
    if settings.sources.alphaxiv_for_you or settings.sources.alphaxiv_hot:
        from digest.sources.alphaxiv import AlphaXivClient

        client = AlphaXivClient(alphaxiv_key)

    seen = load_seen(root / "data" / "seen.json")
    arxiv = ArxivClient()

    async def load_alphaxiv() -> None:
        if client is None or not client.available:
            for key, enabled in (
                ("alphaxiv_for_you", settings.sources.alphaxiv_for_you),
                ("alphaxiv_hot", settings.sources.alphaxiv_hot),
            ):
                if enabled:
                    health[key] = "skipped"
            if settings.sources.alphaxiv_for_you or settings.sources.alphaxiv_hot:
                errors["alphaxiv"] = "ALPHAXIV_API_KEY missing"
            return
        try:
            await client.__aenter__()
        except Exception as exc:  # noqa: BLE001
            health["alphaxiv_for_you"] = "error"
            health["alphaxiv_hot"] = "error"
            errors["alphaxiv"] = str(exc)
            logger.warning("alphaXiv connect failed: %s", exc)
            return
        if settings.sources.alphaxiv_for_you:
            try:
                ids = await client.feed_ids("for_you")
                by_source["alphaxiv_for_you"] = [
                    Paper(arxiv_id=arxiv_id, sources=["alphaxiv_for_you"], for_you_rank=rank)
                    for rank, arxiv_id in enumerate(ids, start=1)
                ]
                health["alphaxiv_for_you"] = "ok" if ids else "empty"
            except Exception as exc:  # noqa: BLE001
                health["alphaxiv_for_you"] = "error"
                errors["alphaxiv_for_you"] = str(exc)
        if settings.sources.alphaxiv_hot:
            try:
                ids = await client.feed_ids("hot")
                by_source["alphaxiv_hot"] = [
                    Paper(arxiv_id=arxiv_id, sources=["alphaxiv_hot"], hot_rank=rank)
                    for rank, arxiv_id in enumerate(ids, start=1)
                ]
                health["alphaxiv_hot"] = "ok" if ids else "empty"
            except Exception as exc:  # noqa: BLE001
                health["alphaxiv_hot"] = "error"
                errors["alphaxiv_hot"] = str(exc)

    try:
        await load_alphaxiv()
        if settings.sources.hf_daily:
            try:
                hf_papers = fetch_daily_papers(day=day.isoformat())
                by_source["hf_daily"] = hf_papers
                health["hf_daily"] = "ok" if hf_papers else "empty"
            except Exception as exc:  # noqa: BLE001
                health["hf_daily"] = "error"
                errors["hf_daily"] = str(exc)
                logger.warning("HF daily failed: %s", exc)

        pool, status = choose_candidate_pool(
            {key: value for key, value in by_source.items() if key != "arxiv"},
            seen,
            source_errors=errors,
            source_health=health,
        )
        if not pool:
            try:
                fallback = arxiv.recent_by_categories(settings.sources.arxiv_fallback_categories)
                by_source["arxiv"] = fallback
                health["arxiv"] = "ok" if fallback else "empty"
            except Exception as exc:  # noqa: BLE001
                health["arxiv"] = "error"
                errors["arxiv"] = str(exc)
            pool, status = choose_candidate_pool(by_source, seen, source_errors=errors, source_health=health)
        else:
            health.setdefault("arxiv", "skipped")
            status.source_health = health

        if pool:
            meta = arxiv.metadata([paper.arxiv_id for paper in pool])
            _copy_metadata(pool, meta)

        def complete(messages):
            return openai_complete(settings, messages)

        if pool and settings.llm.api_key():
            status.warnings.extend(assign_topic_scores(pool, topics, complete))
        elif pool:
            status.warnings.append(f"{settings.llm.api_key_env} missing, topic scores left at 0")
            status.skipped.append(settings.llm.api_key_env)

        apply_scores(pool, topics, day)
        default_ids = [topic.id for topic in topics if topic.default]
        email_papers = select_email_papers(pool, settings.papers_per_day, default_ids)
        page_papers = select_page_papers(
            pool, email_papers, settings.candidates_on_page, [topic.id for topic in topics]
        )

        for paper in page_papers:
            alphaxiv_text = None
            alphaxiv_up = client is not None and getattr(client, "_caller", None) is not None
            if alphaxiv_up:
                try:
                    alphaxiv_text = await client.paper_content(paper.arxiv_id)
                except Exception as exc:  # noqa: BLE001
                    status.warnings.append(f"content {paper.arxiv_id}: {exc}")
            text, source = fetch_content_for_paper(
                paper,
                alphaxiv_text=alphaxiv_text,
                html_getter=default_html_getter,
                max_chars=settings.llm.max_input_chars,
            )
            paper.content = text
            paper.content_source = source
            try:
                _attach_figure(paper, settings, default_html_getter, _http_bytes, use_network_pdf=True)
            except Exception as exc:  # noqa: BLE001
                status.warnings.append(f"figure {paper.arxiv_id}: {exc}")
            if settings.llm.api_key():
                article, path = write_article(paper, complete)
            else:
                from digest.writer import fallback_article

                article, path = fallback_article(paper), "fallback"
            paper.article = article
            status.per_paper[paper.arxiv_id] = {
                "content": source,
                "writer": path,
                "figure": paper.figure.source if paper.figure else "none",
            }

        journal_notes, journal_warnings = fetch_journals(feeds, now=now)
        status.warnings.extend(journal_warnings)
        if journal_notes and settings.llm.api_key():
            fake_papers = [
                Paper(arxiv_id=note.url or note.title, title=note.title, abstract=note.summary)
                for note in journal_notes
            ]
            assign_topic_scores(fake_papers, topics, complete)
            for note, fake in zip(journal_notes, fake_papers):
                note.topic_scores = dict(fake.topic_scores)
        journals = score_journals(journal_notes, topics, settings.journal_items_max)
        for note in journals:
            if settings.llm.api_key():
                note.blurb = write_journal(note, complete)
            else:
                note.blurb = note.summary[:280] or note.title

        _finalize_status(status, email_papers, page_papers)
        failed = status.candidates == "none" or not email_papers
        _emit(
            root=root,
            settings=settings,
            topics=topics,
            day=day,
            email_papers=email_papers,
            page_papers=page_papers,
            journals=journals,
            status=status,
            destination=destination,
            dry_run=False,
        )
        _persist(root, day, seen, email_papers, page_papers, journals, status)
        if failed:
            if settings.notify.wechat:
                failure_notice(settings.notify.wechat_provider)
            return 1, status, email_papers, page_papers, journals
        _notify(settings, day, email_papers, status)
        return 0, status, email_papers, page_papers, journals
    finally:
        if client is not None and client.available:
            try:
                await client.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("alphaXiv session close failed: %s", exc)


def _copy_metadata(papers: list[Paper], meta: list[Paper]) -> None:
    by_id = {item.arxiv_id: item for item in meta}
    for paper in papers:
        extra = by_id.get(paper.arxiv_id)
        if extra is None:
            continue
        paper.title = extra.title or paper.title
        paper.abstract = extra.abstract or paper.abstract
        paper.authors = extra.authors or paper.authors
        paper.categories = extra.categories or paper.categories
        paper.published = extra.published or paper.published


def _http_bytes(url: str) -> bytes:
    import httpx

    with httpx.Client(timeout=45.0, follow_redirects=True, headers={"User-Agent": "paper-digest/1.0"}) as http:
        response = http.get(url)
        response.raise_for_status()
        return response.content


def _attach_figure(
    paper,
    settings: Settings,
    html_getter,
    fetch_image,
    *,
    use_network_pdf: bool,
    allow_llm: bool = True,
) -> None:
    html_candidates: list[FigureCandidate] = []
    latex_candidates: list[FigureCandidate] = []
    pdf_candidates: list[FigureCandidate] = []
    page_url = arxiv_html_url(paper.arxiv_id)
    try:
        html = html_getter(page_url)
        html_candidates = figures_from_html(html, page_url + "/", fetch_image)
    except Exception as exc:  # noqa: BLE001
        logger.warning("html figures %s: %s", paper.arxiv_id, exc)
    if not html_candidates and use_network_pdf:
        try:
            blob = _http_bytes(f"https://arxiv.org/e-print/{paper.arxiv_id}")
            tex_files, images = unpack_eprint(blob)
            latex_candidates = figures_from_latex(tex_files, images)
        except Exception as exc:  # noqa: BLE001
            logger.warning("latex figures %s: %s", paper.arxiv_id, exc)
    if not html_candidates and not latex_candidates and use_network_pdf:
        try:
            pdf_candidates = figures_from_pdf(_http_bytes(f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf figures %s: %s", paper.arxiv_id, exc)
    chosen, origin = first_available(
        [
            ("arxiv_html", html_candidates),
            ("latex", latex_candidates),
            ("pdf", pdf_candidates),
        ]
    )
    if not chosen:
        paper.figure = None
        return
    limited = chosen[:6]
    index = _pick_index(limited, settings) if allow_llm else select_by_caption(limited)
    best = limited[index]
    data, media = normalize_image(best.data)
    paper.figure = FigureAsset(
        caption=best.caption,
        source=origin,
        media_type=media,
        data=data,
        cid=f"fig-{paper.arxiv_id}",
        filename=f"{paper.arxiv_id}.jpg",
    )


def _pick_index(candidates: list[FigureCandidate], settings: Settings) -> int:
    captions = [item.caption for item in candidates]
    if settings.llm.use_vision and settings.llm.api_key():
        try:
            images = [normalize_image(item.data, max_edge=768, max_bytes=200_000)[0] for item in candidates]
            choice = parse_choice(openai_pick_figure(settings, captions, images), len(candidates))
            if choice is not None:
                return choice
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision figure pick failed: %s", exc)
    if settings.llm.api_key():
        try:
            choice = parse_choice(openai_pick_figure(settings, captions, None), len(candidates))
            if choice is not None:
                return choice
        except Exception as exc:  # noqa: BLE001
            logger.warning("caption figure pick failed: %s", exc)
    return select_by_caption(candidates)


def _finalize_status(status: RunStatus, email_papers: list[Paper], page_papers: list[Paper]) -> None:
    status.paper_count = len(email_papers)
    status.content_total = len(page_papers)
    status.content_alphaxiv = sum(1 for paper in page_papers if paper.content_source == "alphaxiv")
    status.figures_total = len(page_papers)
    status.figures_ok = sum(1 for paper in page_papers if paper.figure and paper.figure.data)
    for paper in page_papers:
        info = status.per_paper.get(paper.arxiv_id, {})
        if info.get("writer") == "fallback":
            status.warnings.append(f"writer fallback {paper.arxiv_id}")
    status.status_line = build_status_line(status)


def _emit(root, settings, topics, day, email_papers, page_papers, journals, status, destination, dry_run: bool) -> None:
    site_url = settings.deploy.site_base_url
    html, plain = render_email(
        root=root,
        day=day,
        papers=email_papers,
        journals=journals,
        status=status,
        topics=topics,
        site_url=site_url,
    )
    page = render_page(
        root=root,
        day=day,
        papers=page_papers,
        journals=journals,
        status=status,
        topics=topics,
        papers_per_day=settings.papers_per_day,
        site_url=site_url,
    )
    if dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "email.html").write_text(html, encoding="utf-8")
        (destination / "email.txt").write_text(plain, encoding="utf-8")
        write_site(root=root, site_dir=destination, day=day, page_html=page, papers=page_papers)
        return
    write_site(root=root, site_dir=destination, day=day, page_html=page, papers=page_papers)
    mail_dir = root / "out"
    mail_dir.mkdir(parents=True, exist_ok=True)
    (mail_dir / "email.html").write_text(html, encoding="utf-8")
    (mail_dir / "email.txt").write_text(plain, encoding="utf-8")
    _maybe_send_email(settings, day, email_papers, html, plain, status)


def _maybe_send_email(settings, day, email_papers, html, plain, status: RunStatus) -> None:
    if not settings.notify.email:
        status.skipped.append("email")
        return
    host = env("SMTP_HOST")
    user = env("SMTP_USER")
    password = env("SMTP_PASSWORD")
    mail_to = env("MAIL_TO")
    if not email_papers:
        return
    if not all([host, user, password, mail_to]):
        status.skipped.append("email")
        status.warnings.append("email skipped: SMTP_HOST/SMTP_USER/SMTP_PASSWORD/MAIL_TO incomplete")
        return
    port = int(env("SMTP_PORT") or "465")
    recipients = [item.strip() for item in mail_to.split(",") if item.strip()]
    headline = email_papers[0].article.headline if email_papers and email_papers[0].article else "论文日报"
    subject = subject_for(f"{day.month}/{day.day}", headline)
    message = build_message(
        sender=user,
        recipients=recipients,
        subject=subject,
        html=html,
        plain=plain,
        papers=email_papers,
    )
    message = shrink_figures_if_needed(message, email_papers, html, plain, user, recipients, subject)
    try:
        send_email(host=host, port=port, user=user, password=password, recipients=recipients, message=message)
    except Exception as exc:  # noqa: BLE001
        status.warnings.append(f"email send failed: {exc}")
        logger.warning("email send failed: %s", exc)


def _notify(settings: Settings, day: date, email_papers: list[Paper], status: RunStatus) -> None:
    if not settings.notify.wechat:
        status.skipped.append("wechat")
        return
    lines: list[str] = []
    for index, paper in enumerate(email_papers, start=1):
        headline = paper.article.headline if paper.article else paper.title
        lines.append(f"{index}. **{headline}**")
        if paper.article and paper.article.lede:
            lines.append(f"   {paper.article.lede}")
        lines.append(
            f"   [arXiv](https://arxiv.org/abs/{paper.arxiv_id}) · "
            f"[alphaXiv](https://www.alphaxiv.org/abs/{paper.arxiv_id})"
        )
        lines.append("")
    site_base = (settings.deploy.site_base_url or "").rstrip("/")
    if site_base:
        page_url = f"{site_base}/{day.isoformat()}/"
        lines.append(f"网页版（含图文）：{page_url}")
        lines.append("")
    else:
        lines.append("网页版链接未配置：请在 Cloudflare Pages 复制网址后填入 config/settings.yaml 的 deploy.site_base_url")
        lines.append("")
    lines.append(f"今日数据源状态：{status.status_line}")
    title = f"论文日报 {day.month}/{day.day}"
    if email_papers and email_papers[0].article:
        title = f"{title} · {email_papers[0].article.headline}"
    try:
        result = send_wechat(settings.notify.wechat_provider, title, "\n".join(lines))
        if result == "skipped":
            status.skipped.append("wechat")
    except Exception as exc:  # noqa: BLE001
        status.warnings.append(f"wechat failed: {exc}")
        logger.warning("wechat failed: %s", exc)


def _persist(root, day, seen, email_papers, page_papers, journals, status: RunStatus) -> None:
    seen.update(paper.arxiv_id for paper in email_papers)
    save_seen(root / "data" / "seen.json", seen)

    def dump_paper(paper: Paper) -> dict:
        data = paper.model_dump(mode="json")
        if paper.figure:
            data["figure"] = paper.figure.model_dump(mode="json")
        return data

    write_archive(
        root / "data" / "archive",
        day.isoformat(),
        {
            "date": day.isoformat(),
            "email_papers": [dump_paper(paper) for paper in email_papers],
            "page_papers": [dump_paper(paper) for paper in page_papers],
            "journals": [note.model_dump(mode="json") for note in journals],
            "run_status": status.model_dump(mode="json"),
        },
    )

