import io

import pymupdf
from PIL import Image

from digest.figures import (
    FigureCandidate,
    figures_from_html,
    figures_from_latex,
    figures_from_pdf,
    first_available,
    normalize_image,
)


def _png() -> bytes:
    image = Image.new("RGB", (80, 40), (20, 80, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_html_figures_and_absolute_src():
    html = """
    <html><body>
      <figure><img src="overview.png"><figcaption>The overall framework.</figcaption></figure>
      <figure><img src="/html/2510.10001/result.jpg"><figcaption>Qualitative results.</figcaption></figure>
    </body></html>
    """
    fetched = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _png()

    found = figures_from_html(html, "https://arxiv.org/html/2510.10001/", fetch)
    assert len(found) == 2
    assert fetched[0] == "https://arxiv.org/html/2510.10001/overview.png"
    assert fetched[1] == "https://arxiv.org/html/2510.10001/result.jpg"


def test_three_level_fallback():
    html = [FigureCandidate("framework", b"h", "arxiv_html")]
    latex = [FigureCandidate("pipeline", b"l", "latex")]
    pdf = [FigureCandidate("Figure 1", b"p", "pdf")]
    assert first_available([("arxiv_html", html), ("latex", latex), ("pdf", pdf)])[1] == "arxiv_html"
    assert first_available([("arxiv_html", []), ("latex", latex), ("pdf", pdf)])[1] == "latex"
    assert first_available([("arxiv_html", []), ("latex", []), ("pdf", pdf)])[1] == "pdf"
    assert first_available([("arxiv_html", []), ("latex", []), ("pdf", [])])[1] == "none"


def test_latex_caption_and_image():
    tex = r"""
    \begin{figure}
    \includegraphics[width=0.8\linewidth]{figures/overview.png}
    \caption{The pipeline of the proposed model.}
    \end{figure}
    """
    found = figures_from_latex({"main.tex": tex}, {"figures/overview.png": _png()})
    assert len(found) == 1
    assert "pipeline" in found[0].caption
    assert found[0].origin == "latex"


def test_pdf_crop_finds_figure_1():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 180), "method overview diagram")
    page.insert_text((72, 420), "Figure 1: the pipeline")
    blob = document.tobytes()
    found = figures_from_pdf(blob)
    assert len(found) == 1
    assert found[0].data[:8] == b"\x89PNG\r\n\x1a\n"
    normalized, media = normalize_image(found[0].data, max_edge=200, max_bytes=80_000)
    assert media == "image/jpeg"
    assert len(normalized) < 80_000
