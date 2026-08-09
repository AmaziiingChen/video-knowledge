"""Pure parsing and compatibility rules for report-section planner JSON."""

from __future__ import annotations

from services.group_report_models import _Section, _SupportingSource


def normalize_report_plan_shape(data: object) -> tuple[object, list[str]]:
    """Convert known legacy planner shapes without another model call."""
    adjustments: list[str] = []
    if isinstance(data, list):
        data = {"sections": data}
        adjustments.append("将顶层栏目数组转换为 sections")
    if not isinstance(data, dict):
        return data, adjustments

    normalized = dict(data)
    raw_sections = normalized.get("sections")
    if not isinstance(raw_sections, list) and isinstance(normalized.get("columns"), list):
        raw_sections = normalized["columns"]
        normalized["sections"] = raw_sections
        adjustments.append("将旧字段 columns 转换为 sections")
    if not isinstance(raw_sections, list):
        return normalized, adjustments

    normalized_sections: list[object] = []
    converted_section_count = 0
    for item in raw_sections:
        if not isinstance(item, dict):
            normalized_sections.append(item)
            continue
        section = dict(item)
        if not str(section.get("title") or "").strip():
            for alias in ("heading", "name"):
                if str(section.get(alias) or "").strip():
                    section["title"] = section[alias]
                    converted_section_count += 1
                    break
        if not isinstance(section.get("source_ids"), list):
            source_ids = section.get("primary_source_ids")
            if not isinstance(source_ids, list):
                source_ids = nested_plan_source_ids(section)
            if isinstance(source_ids, list) and source_ids:
                section["source_ids"] = source_ids
                converted_section_count += 1
        if not str(section.get("writing_brief") or "").strip():
            for alias in ("writing_instruction", "brief"):
                if str(section.get(alias) or "").strip():
                    section["writing_brief"] = section[alias]
                    converted_section_count += 1
                    break
        section.setdefault("supporting_sources", [])
        normalized_sections.append(section)
    normalized["sections"] = normalized_sections
    if converted_section_count:
        adjustments.append(f"兼容转换 {converted_section_count} 个旧版栏目字段")
    return normalized, adjustments


def nested_plan_source_ids(section: dict[str, object]) -> list[str]:
    source_ids: list[str] = []
    seen: set[str] = set()
    for container_key in ("content_groups", "events"):
        groups = section.get(container_key)
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            values = group.get("source_ids")
            if not isinstance(values, list):
                values = group.get("primary_source_ids")
            if not isinstance(values, list):
                continue
            for value in values:
                source_id = str(value or "").strip()
                if source_id and source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
    return source_ids


def describe_report_plan_shape(data: object) -> str:
    if isinstance(data, list):
        return f"顶层类型=array，元素数={len(data)}"
    if not isinstance(data, dict):
        return f"顶层类型={type(data).__name__}"
    keys = ",".join(sorted(str(key) for key in data)) or "无"
    sections = data.get("sections")
    if not isinstance(sections, list):
        columns = data.get("columns")
        if isinstance(columns, list):
            sections = columns
    if not isinstance(sections, list):
        return f"顶层字段={keys}；未找到栏目数组"
    first_keys = "无"
    if sections and isinstance(sections[0], dict):
        first_keys = ",".join(sorted(str(key) for key in sections[0])) or "无"
    return f"顶层字段={keys}；栏目数={len(sections)}；首个栏目字段={first_keys}"


def parse_report_plan(data: object, valid_ids: set[str]) -> tuple[str, list[_Section]]:
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        return "", []
    strategy = " ".join(str(data.get("report_strategy") or "").split())[:2000]
    sections: list[_Section] = []
    for item in data["sections"]:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())[:80]
        raw_source_ids = item.get("source_ids")
        if not title or not isinstance(raw_source_ids, list):
            continue
        source_ids = tuple(str(value).strip() for value in raw_source_ids if str(value).strip())
        if not source_ids:
            continue
        supporting: list[_SupportingSource] = []
        raw_supporting = item.get("supporting_sources")
        if isinstance(raw_supporting, list):
            for support in raw_supporting:
                if not isinstance(support, dict):
                    continue
                source_id = str(support.get("source_id") or "").strip()
                use_scope = " ".join(str(support.get("use_scope") or "").split())[:300]
                if source_id and use_scope:
                    supporting.append(_SupportingSource(source_id=source_id, use_scope=use_scope))
        writing_brief = " ".join(str(item.get("writing_brief") or "").split())[:2000]
        sections.append(
            _Section(
                title=title,
                source_ids=source_ids,
                supporting_sources=tuple(supporting),
                writing_brief=writing_brief,
            )
        )
    return strategy, sections
