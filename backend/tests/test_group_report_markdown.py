from services import group_report_pipeline
from services.group_report_markdown import (
    _append_footnotes,
    _normalize_citation_tokens,
    _normalize_generated_section_markdown,
)
from services.group_report_models import GroupReportSource


def _source() -> GroupReportSource:
    return GroupReportSource(
        citation_id="S001",
        content_item_id="item-1",
        title="标题 [一]",
        source_url="https://example.com/article",
        published_at="2026-08-09T12:00:00+08:00",
        publisher="示例来源",
        source_kind="wechat",
        material="正文",
    )


def test_pipeline_re_exports_pure_markdown_contracts() -> None:
    assert group_report_pipeline._normalize_citation_tokens is _normalize_citation_tokens
    assert (
        group_report_pipeline._normalize_generated_section_markdown
        is _normalize_generated_section_markdown
    )


def test_markdown_boundary_repairs_citations_and_renders_source_metadata() -> None:
    normalized = _normalize_citation_tokens("事实[S001]，未知[S999]。", {"S001"})
    assert normalized == "事实[^S001]，未知[S999]。"

    markdown = _append_footnotes("事实。[^S001]", [_source()], {"S001"})
    assert (
        "[^S001]: [标题 \\[一\\]](https://example.com/article)"
        " · 微信公众号 · 示例来源 · 2026-08-09"
    ) in markdown


def test_markdown_boundary_restores_interrupted_table_and_drops_model_footnote() -> None:
    normalized = _normalize_generated_section_markdown(
        "| 项目 | 状态 |\n"
        "| --- | --- |\n"
        "| 甲 | 完成 |[^S001]\n\n"
        "补充说明。\n\n"
        "| 乙 | 进行中 |\n\n"
        "[^S001]: 不应保留"
    )

    assert "| 甲 | 完成[^S001] |" in normalized
    assert normalized.count("| 项目 | 状态 |") == 2
    assert "[^S001]:" not in normalized
