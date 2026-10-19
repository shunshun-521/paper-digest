import json
from pathlib import Path

from digest.pipeline import run


def test_dry_run_writes_preview_without_touching_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    seen_before = (root / "data" / "seen.json").read_text(encoding="utf-8")
    out = tmp_path / "out"
    code = run(dry_run=True, on_date="2026-10-19", root=root, out_dir=out)
    assert code == 0
    html = (out / "email.html").read_text(encoding="utf-8")
    assert "激活向量能改模型人设" in html
    assert "cid:fig-2510.10001" in html
    assert "<script" not in html.lower()
    page = (out / "2026-10-19" / "index.html").read_text(encoding="utf-8")
    assert "data-topic" in page
    assert "localStorage" in page
    assert (out / "2026-10-19" / "img" / "2510.10001.jpg").exists()
    assert (root / "data" / "seen.json").read_text(encoding="utf-8") == seen_before
    archive = list((root / "data" / "archive").glob("*.json"))
    assert archive == [] or all(json.loads(path.read_text(encoding="utf-8")) for path in archive)
