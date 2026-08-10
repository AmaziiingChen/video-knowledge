from types import SimpleNamespace

from services import campus_procurement_payloads, campus_sources
from services.campus_source_catalog import get_campus_source


def test_campus_sources_keeps_procurement_compatibility_aliases():
    assert (
        campus_sources._procurement_publish_id_from_fragment
        is campus_procurement_payloads.procurement_publish_id_from_fragment
    )
    assert (
        campus_sources._procurement_provider_document_url
        is campus_procurement_payloads.procurement_provider_document_url
    )


def test_procurement_record_normalization_preserves_public_url_and_rejects_invalid_ids():
    article = campus_procurement_payloads.procurement_record_to_article(
        {
            "id": "record-1",
            "syncId": "PUBLICSYNC1",
            "subject": "  2026-08-10 实验设备采购公告  ",
            "beginTime": "2026-08-10 09:30:00",
            "tenderNo": "SZTU20260001",
        },
        source=get_campus_source("sztu-procurement"),
        section="采购公告",
    )

    assert article is not None
    assert article.title == "实验设备采购公告"
    assert article.published_at == "2026-08-10 09:30:00"
    assert article.url == (
        "https://ztb.sztu.edu.cn/provider/?record_id=record-1&keyword=SZTU20260001"
        "&section=%E9%87%87%E8%B4%AD%E5%85%AC%E5%91%8A#/publish/PUBLICSYNC1"
    )
    assert (
        campus_procurement_payloads.procurement_publish_id(
            article.url,
            {"syncId": "../../secret"},
        )
        == ""
    )


def test_procurement_fragment_fallback_and_ocr_metadata_are_normalized_safely():
    content = campus_procurement_payloads.procurement_cms_content(
        "<h2>更正公告</h2><table><tr><td rowspan='2'>项目</td></tr></table>",
        content_selectors=("article",),
    )
    fallback = campus_procurement_payloads.procurement_fallback_article(
        "https://ztb.sztu.edu.cn/example",
        {"section": "采购公告", "keyword": "<script>alert(1)</script>"},
    )
    metadata = campus_procurement_payloads.procurement_document_ocr_metadata(
        SimpleNamespace(status="not_configured", cloud_submitted=False, error="")
    )

    assert content is not None
    assert content.name == "section"
    assert content.select_one("td")["rowspan"] == "2"
    assert "<script>" not in fallback["body_html"]
    assert "&lt;script&gt;" in fallback["body_html"]
    assert metadata == {
        "attempted": False,
        "status": "not_configured",
        "cloud_submitted": False,
        "error": "",
    }
