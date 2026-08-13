"""Deterministic repair rules for parsed report-section plans."""

from __future__ import annotations

from services.group_report_models import _Section, _SupportingSource


def normalize_report_plan(
    report_strategy: str,
    sections: list[_Section],
    excluded_source_ids: set[str],
    valid_ids: set[str],
) -> tuple[str, list[_Section], set[str], list[str]]:
    """Repair deterministic plan defects while preserving the model's structure."""
    adjustments: list[str] = []
    invalid_primary_count = 0
    duplicate_within_section_count = 0
    removed_supporting_count = 0
    missing_brief_count = 0
    dropped_section_count = 0
    normalized_sections: list[_Section] = []

    for section in sections:
        primary_ids: list[str] = []
        seen_primary: set[str] = set()
        for source_id in section.source_ids:
            if source_id not in valid_ids:
                invalid_primary_count += 1
                continue
            if source_id in seen_primary:
                duplicate_within_section_count += 1
                continue
            seen_primary.add(source_id)
            primary_ids.append(source_id)
        if not primary_ids:
            dropped_section_count += 1
            continue

        supporting: list[_SupportingSource] = []
        seen_supporting: set[str] = set()
        for support in section.supporting_sources:
            if (
                support.source_id not in valid_ids
                or support.source_id in seen_primary
                or support.source_id in seen_supporting
            ):
                removed_supporting_count += 1
                continue
            seen_supporting.add(support.source_id)
            supporting.append(support)

        writing_brief = section.writing_brief.strip()
        if not writing_brief:
            missing_brief_count += 1
            writing_brief = (
                f"围绕“{section.title}”按材料实际主题组织，合并重复来源，"
                "保留独立事项差异，并选择适合的段落、列表或表格。"
            )
        normalized_sections.append(
            _Section(
                title=section.title,
                source_ids=tuple(primary_ids),
                supporting_sources=tuple(supporting),
                writing_brief=writing_brief,
            )
        )

    assigned_primary_ids = {
        source_id
        for section in normalized_sections
        for source_id in section.source_ids
    }
    conflicting_excluded = excluded_source_ids & assigned_primary_ids
    normalized_excluded = excluded_source_ids - conflicting_excluded
    if normalized_excluded:
        without_excluded_supporting: list[_Section] = []
        for section in normalized_sections:
            supporting = tuple(
                support
                for support in section.supporting_sources
                if support.source_id not in normalized_excluded
            )
            removed_supporting_count += len(section.supporting_sources) - len(supporting)
            without_excluded_supporting.append(
                _Section(
                    title=section.title,
                    source_ids=section.source_ids,
                    supporting_sources=supporting,
                    writing_brief=section.writing_brief,
                )
            )
        normalized_sections = without_excluded_supporting

    normalized_strategy = report_strategy.strip()
    if not normalized_strategy and normalized_sections:
        normalized_strategy = (
            "按材料实际主题组织，合并重复来源，突出重要与时效性内容，"
            "并保持栏目之间详略有别。"
        )
        adjustments.append("补充通用报告策略")
    if invalid_primary_count:
        adjustments.append(f"移除 {invalid_primary_count} 个无效主来源编号")
    if duplicate_within_section_count:
        adjustments.append(f"移除 {duplicate_within_section_count} 个栏目内重复主来源编号")
    if removed_supporting_count:
        adjustments.append(f"移除 {removed_supporting_count} 个无效、重复或冲突的辅助来源")
    if conflicting_excluded:
        adjustments.append(f"取消 {len(conflicting_excluded)} 个与主栏目冲突的排除标记")
    if missing_brief_count:
        adjustments.append(f"为 {missing_brief_count} 个栏目补充通用写作要求")
    if dropped_section_count:
        adjustments.append(f"删除 {dropped_section_count} 个没有可用主来源的空栏目")
    return normalized_strategy, normalized_sections, normalized_excluded, adjustments
