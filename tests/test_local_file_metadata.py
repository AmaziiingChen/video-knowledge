from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.local_file_imports import extract_document_text, local_file_metadata


def test_reads_retained_image_metadata(tmp_path):
    original = tmp_path / "original--scan.webp"
    Image.new("RGB", (640, 480), "white").save(original)

    metadata = local_file_metadata(original)

    assert metadata["file_name"] == "scan.webp"
    assert metadata["file_format"] == "WEBP"
    assert metadata["file_size_bytes"] == original.stat().st_size
    assert metadata["width"] == 640
    assert metadata["height"] == 480


def test_reads_pdf_page_count_when_the_page_objects_are_present(tmp_path):
    original = tmp_path / "original--notes.pdf"
    original.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Page >>\n2 0 obj << /Type /Page >>\n")

    metadata = local_file_metadata(original)

    assert metadata["file_format"] == "PDF"
    assert metadata["page_count"] == 2


def test_html_metadata_reads_saved_original_url(tmp_path):
    original = tmp_path / "original--page.html"
    original.write_text(
        '<!-- saved from url=(0042)https://example.edu/news?id=42 -->\n<html><head></head><body></body></html>',
        encoding="utf-8",
    )

    metadata = local_file_metadata(original)

    assert metadata["original_source_url"] == "https://example.edu/news?id=42"


def test_html_extraction_prefers_campus_content_container_over_page_chrome():
    raw = b'''<!doctype html><html><head><title>\xe6\x96\xb0\xe6\x9d\x90\xe6\x96\x99\xe4\xb8\x8e\xe6\x96\xb0\xe8\x83\xbd\xe6\xba\x90\xe5\xad\xa6\xe9\x99\xa2</title></head>
    <body><nav>\xe7\xbd\x91\xe7\xab\x99\xe5\xaf\xbc\xe8\x88\xaa</nav><div id="vsb_content"><div class="news_conent_two_text"><style>.x{}</style><p>\xe5\xad\xa6\xe9\x99\xa2\xe6\xad\xa3\xe6\x96\x87\xe7\xac\xac\xe4\xb8\x80\xe6\xae\xb5</p><p>\xe5\xad\xa6\xe9\x99\xa2\xe6\xad\xa3\xe6\x96\x87\xe7\xac\xac\xe4\xba\x8c\xe6\xae\xb5</p></div></div><footer>\xe9\xa1\xb5\xe8\x84\x9a</footer></body></html>'''

    text, title = extract_document_text(raw, filename="academy.html", kind="html")

    assert title == "新材料与新能源学院"
    assert "学院正文第一段" in text
    assert "学院正文第二段" in text
    assert "网站导航" not in text
