"""Pick one method-overview figure per paper, with three fallbacks."""

from __future__ import annotations

import io
import logging
import re
import tarfile
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "paper-digest/1.0 (GitHub Actions; research digest)"
OVERVIEW_HINTS = (
    "overview",
    "framework",
    "pipeline",
    "architecture",
    "method",
    "模型",
    "框架",
    "总览",
    "流程",
)
FIGURE_CAPTION_RE = re.compile(r"(figure|fig\.)\s*1\b", re.IGNORECASE)


@dataclass
class FigureCandidate:
    caption: str
    data: bytes
    origin: str


def figures_from_html(html: str, page_url: str, fetch_image: Callable[[str], bytes]) -> list[FigureCandidate]:
    soup = BeautifulSoup(html, "lxml")
    found: list[FigureCandidate] = []
    for figure in soup.find_all("figure"):
        image = figure.find("img")
        if image is None or not image.get("src"):
            continue
        caption_tag = figure.find("figcaption")
        caption = caption_tag.get_text(" ", strip=True) if caption_tag else (image.get("alt") or "")
        src = urljoin(page_url, image["src"])
        try:
            data = fetch_image(src)
        except Exception as exc:  # noqa: BLE001
            logger.warning("figure download failed %s: %s", src, exc)
            continue
        if data:
            found.append(FigureCandidate(caption=caption, data=data, origin="arxiv_html"))
    return found


def _balanced_brace(text: str, open_at: int) -> str | None:
    if open_at >= len(text) or text[open_at] != "{":
        return None
    depth = 0
    for index in range(open_at, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : index]
    return None


def figures_from_latex(files: dict[str, str], images: dict[str, bytes]) -> list[FigureCandidate]:
    found: list[FigureCandidate] = []
    include_re = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{")
    caption_re = re.compile(r"\\caption\{")
    figure_re = re.compile(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.S)
    image_index = {_basename(name).lower(): blob for name, blob in images.items()}
    for tex in files.values():
        blocks = figure_re.findall(tex) or [tex]
        for block in blocks:
            include = include_re.search(block)
            if not include:
                continue
            path = _balanced_brace(block, include.end() - 1)
            if not path:
                continue
            caption = ""
            cap = caption_re.search(block)
            if cap:
                caption = _balanced_brace(block, cap.end() - 1) or ""
            blob = image_index.get(_basename(path).lower())
            if blob is None:
                continue
            if path.lower().endswith(".pdf") or blob[:4] == b"%PDF":
                rendered = render_pdf_page(blob)
                if not rendered:
                    continue
                blob = rendered
            found.append(FigureCandidate(caption=_clean_tex(caption), data=blob, origin="latex"))
    return found


def _basename(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1]


def _clean_tex(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def render_pdf_page(pdf_bytes: bytes) -> bytes | None:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return None
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001
        return None
    if document.page_count == 0:
        return None
    page = document[0]
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    return pixmap.tobytes("png")


def figures_from_pdf(pdf_bytes: bytes) -> list[FigureCandidate]:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return []
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001
        return []
    for page in document:
        hits = page.search_for("Figure 1") or page.search_for("Fig. 1")
        if not hits:
            continue
        rect = hits[0]
        top = max(page.rect.y0, rect.y0 - 340)
        clip = pymupdf.Rect(page.rect.x0 + 24, top, page.rect.x1 - 24, max(rect.y0 - 2, top + 40))
        if clip.height < 30:
            continue
        pixmap = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(2, 2), alpha=False)
        return [FigureCandidate(caption="Figure 1", data=pixmap.tobytes("png"), origin="pdf")]
    return []


def unpack_eprint(blob: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    if blob.startswith(b"%PDF"):
        return {}, {}
    tex_files: dict[str, str] = {}
    images: dict[str, bytes] = {}
    try:
        archive = tarfile.open(fileobj=io.BytesIO(blob), mode="r:*")
    except tarfile.TarError:
        return {}, {}
    for member in archive.getmembers():
        if not member.isfile():
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        data = extracted.read()
        name = member.name
        lower = name.lower()
        if lower.endswith(".tex"):
            tex_files[name] = data.decode("utf-8", errors="ignore")
        elif lower.endswith((".png", ".jpg", ".jpeg", ".pdf")):
            images[name] = data
    return tex_files, images


def first_available(
    levels: list[tuple[str, list[FigureCandidate]]],
) -> tuple[list[FigureCandidate], str]:
    for name, candidates in levels:
        if candidates:
            return candidates, name
    return [], "none"


def select_by_caption(candidates: list[FigureCandidate]) -> int:
    for index, candidate in enumerate(candidates):
        caption = candidate.caption.lower()
        if any(hint in caption for hint in OVERVIEW_HINTS):
            return index
    return 0


def parse_choice(text: str, count: int) -> int | None:
    match = re.search(r"\d+", text or "")
    if not match:
        return None
    number = int(match.group(0))
    if 1 <= number <= count:
        return number - 1
    if 0 <= number < count:
        return number
    return None


def normalize_image(data: bytes, *, max_edge: int = 1000, max_bytes: int = 300_000) -> tuple[bytes, str]:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image = image.convert("RGB")
    image.thumbnail((max_edge, max_edge))
    quality = 85
    edge = max(image.size)
    best = b""
    while True:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        best = buffer.getvalue()
        if len(best) <= max_bytes or (quality <= 40 and edge <= 480):
            return best, "image/jpeg"
        if quality > 40:
            quality -= 10
            continue
        edge = int(edge * 0.8)
        image.thumbnail((edge, edge))


def shrink_for_email(data: bytes) -> tuple[bytes, str]:
    return normalize_image(data, max_edge=800, max_bytes=120_000)


def preview_png(title: str) -> bytes:
    """Offline illustration used by dry-run fixtures."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (960, 540), (244, 247, 251))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 36, 924, 504), radius=18, outline=(22, 96, 160), width=4)
    draw.rounded_rectangle((70, 150, 300, 300), radius=12, fill=(222, 236, 248))
    draw.rounded_rectangle((380, 150, 610, 300), radius=12, fill=(232, 242, 226))
    draw.rounded_rectangle((690, 150, 890, 300), radius=12, fill=(250, 236, 214))
    draw.line((300, 225, 380, 225), fill=(22, 96, 160), width=4)
    draw.line((610, 225, 690, 225), fill=(22, 96, 160), width=4)
    draw.text((70, 70), "Method overview", fill=(18, 42, 74))
    draw.text((70, 360), title[:48], fill=(40, 48, 58))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
