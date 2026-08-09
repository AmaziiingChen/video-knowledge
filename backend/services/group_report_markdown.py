"""Deterministic Markdown and citation rendering for group reports.

This module intentionally contains no model calls, persistence, or task state.
It is the pure presentation boundary used by the report orchestrator.
"""

from __future__ import annotations

import re

from services.group_report_models import GroupReportSource, _Section


_CITATION_RE = re.compile(r"\[\^(S\d+)\]")
_MALFORMED_CITATION_RE = re.compile(r"(?<!\^)\[(S\d+)\]")
_CITATION_ONLY_LINE_RE = re.compile(r"^\s*(?:\[\^S\d+\]\s*)+\s*$")
_MODEL_FOOTNOTE_DEFINITION_RE = re.compile(r"^\s*\[\^S\d+\]:.*$")


def _normalize_citation_tokens(markdown: str, valid_ids: set[str]) -> str:
    """Repair a valid ``[S001]`` typo before coverage is evaluated."""
    return _MALFORMED_CITATION_RE.sub(
        lambda match: f"[^{match.group(1)}]" if match.group(1) in valid_ids else match.group(0),
        str(markdown or ""),
    )


def _remove_invalid_citation_tokens(markdown: str, valid_ids: set[str]) -> str:
    """Keep only citations that have a source in the current report."""
    return _CITATION_RE.sub(
        lambda match: match.group(0) if match.group(1) in valid_ids else "",
        str(markdown or ""),
    )


def _missing_source_summary_fallback(
    sources: list[GroupReportSource], summaries: dict[str, str]
) -> str:
    """Render already-generated short summaries only when repair calls fail."""
    if not sources:
        return ""
    blocks = ["### 补充材料"]
    for source in sources:
        title = " ".join(source.title.split()) or "未命名材料"
        summary = " ".join(str(summaries.get(source.citation_id) or "").split())
        summary = _CITATION_RE.sub("", summary).strip() or f"{title}已纳入本栏目。"
        blocks.append(f"- **{title}**：{_append_inline_citation(summary, source.citation_id)}")
    return "\n".join(blocks)


def _append_inline_citation(text: str, citation_id: str) -> str:
    citation = f"[^{citation_id}]"
    match = re.search(r"([。！？；：，、.!?;:,])\s*$", text)
    if match:
        return f"{text[:match.start(1)]}{citation}{text[match.start(1):]}"
    return f"{text}{citation}"


def _append_inline_citations(text: str, citations: str) -> str:
    """Place a prebuilt citation bundle before closing punctuation."""
    match = re.search(r"([。！？；：，、.!?;:,])\s*$", text)
    if match:
        return f"{text[:match.start(1)]}{citations}{text[match.start(1):]}"
    return f"{text}{citations}"


def _coalesce_repeated_single_source_citations(markdown: str) -> str:
    """Keep one citation at the end of a same-source Markdown fact block."""
    chunks = re.split(r"(\n{2,})", str(markdown or ""))
    citation_pattern = re.compile(r"\[\^([A-Za-z0-9_-]+)\]")
    terminal_punctuation = re.compile(r"([。！？；：，、.!?;:,])\s*$")

    for index in range(0, len(chunks), 2):
        block = chunks[index]
        citations = citation_pattern.findall(block)
        unique_ids = set(citations)
        if len(citations) < 2 or len(unique_ids) != 1:
            continue
        if any(line.lstrip().startswith("|") for line in block.splitlines()):
            continue
        citation = f"[^{citations[0]}]"
        without_citations = citation_pattern.sub("", block)
        without_citations = re.sub(r"[ \t]+([。！？；：，、.!?;:,])", r"\1", without_citations)
        without_citations = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", without_citations).rstrip()
        match = terminal_punctuation.search(without_citations)
        if match:
            chunks[index] = f"{without_citations[:match.start(1)]}{citation}{without_citations[match.start(1):]}"
        else:
            chunks[index] = f"{without_citations}{citation}"
    return "".join(chunks)


def _normalize_generated_section_markdown(markdown: str) -> str:
    """Enforce deterministic Markdown and citation presentation contracts."""
    normalized_lines: list[str] = []
    for line in str(markdown or "").splitlines():
        if _MODEL_FOOTNOTE_DEFINITION_RE.match(line):
            continue
        if _CITATION_ONLY_LINE_RE.match(line):
            citation_ids = _CITATION_RE.findall(line)
            normalized_lines.append(
                "以上信息依据相关来源整理。"
                + "".join(f"[^{source_id}]" for source_id in citation_ids)
            )
            continue
        trailing_citations = re.match(
            r"^(\s*\|.*\|)\s*((?:\[\^S\d+\])+)\s*$",
            line,
        )
        if trailing_citations and not _is_markdown_table_separator(
            trailing_citations.group(1)
        ):
            row = trailing_citations.group(1).rstrip()
            line = row[:-1].rstrip() + trailing_citations.group(2) + " |"
        normalized_lines.append(line)
    normalized_lines = _restore_interrupted_markdown_tables(normalized_lines)
    return _coalesce_repeated_single_source_citations(
        "\n".join(normalized_lines)
    ).strip()


def _restore_interrupted_markdown_tables(lines: list[str]) -> list[str]:
    """Repeat the nearest compatible header before orphaned continuation rows."""
    normalized: list[str] = []
    last_header: tuple[str, str, int] | None = None
    inside_table = False
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_markdown_table_row(line) and _is_markdown_table_separator(next_line):
            cell_count = _markdown_table_cell_count(line)
            last_header = (line, next_line, cell_count)
            normalized.extend((line, next_line))
            inside_table = True
            index += 2
            continue
        if _is_markdown_table_row(line):
            cell_count = _markdown_table_cell_count(line)
            if not inside_table and last_header is not None and cell_count == last_header[2]:
                if normalized and normalized[-1].strip():
                    normalized.append("")
                normalized.extend(last_header[:2])
            normalized.append(line)
            inside_table = True
            index += 1
            continue
        normalized.append(line)
        if line.strip() or inside_table:
            inside_table = False
        index += 1
    return normalized


def _is_markdown_table_separator(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(
        bool(cell) and re.fullmatch(r":?-{3,}:?", cell) is not None
        for cell in cells
    )


def _is_markdown_table_row(line: str) -> bool:
    stripped = str(line or "").strip()
    return (
        stripped.startswith("|")
        and stripped.endswith("|")
        and _markdown_table_cell_count(stripped) >= 2
    )


def _markdown_table_cell_count(line: str) -> int:
    stripped = str(line or "").strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return 0
    return len(stripped[1:-1].split("|"))


def _normalize_section_heading_levels(markdown: str, section_title: str) -> str:
    """Reserve H2 for system-owned report sections and prevent skipped levels."""
    previous_level = 2
    normalized: list[str] = []
    normalized_section_title = " ".join(str(section_title or "").split())
    for line in str(markdown or "").splitlines():
        bold_title = re.fullmatch(r"\s*\*\*(.+?)\*\*\s*", line)
        if (
            bold_title
            and not any(item.strip() for item in normalized)
            and " ".join(bold_title.group(1).split()) == normalized_section_title
        ):
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            normalized.append(line)
            continue
        heading_text = match.group(2)
        if not normalized and " ".join(heading_text.split()) == normalized_section_title:
            continue
        requested_level = len(match.group(1))
        level = max(3, requested_level)
        level = min(level, previous_level + 1, 6)
        normalized.append(f"{'#' * level} {match.group(2)}")
        previous_level = level
    return "\n".join(normalized).strip()


def _normalize_report_overview(markdown: str) -> str:
    """Keep a single system-defined H2 overview, never a wrapper heading."""
    body_lines: list[str] = []
    for line in str(markdown or "").strip().splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if not match:
            body_lines.append(line)
            continue
        heading_text = match.group(1).strip()
        if heading_text in {"报告正文", "本期概览"}:
            continue
        body_lines.append(heading_text)
    body = "\n".join(body_lines).strip()
    blocks = [
        " ".join(block.split())
        for block in re.split(r"\n\s*\n", body)
        if block.strip()
    ]
    if len(blocks) >= 3 and not any(
        re.match(r"^[-*+]\s+", block) for block in blocks
    ):
        body = blocks[0] + "\n\n" + "\n".join(f"- {block}" for block in blocks[1:])
    return "## 本期概览" + (f"\n\n{body}" if body else "")


def _fallback_report_overview(sections: list[_Section]) -> str:
    titles = [section.title for section in sections if section.title]
    if not titles:
        return "## 本期概览\n\n本期材料已完成整理，具体内容见下文。"
    visible = "、".join(titles[:4])
    suffix = "等主题" if len(titles) > 4 else ""
    return (
        "## 本期概览\n\n"
        f"本期共整理 {len(titles)} 个主题，涵盖{visible}{suffix}。"
        "下文按信息脉络展开，并保留对应来源以便核对。"
    )


def _append_footnotes(
    markdown: str, sources: list[GroupReportSource], cited_ids: set[str]
) -> str:
    references = [
        _source_footnote(source)
        for source in sources
        if source.citation_id in cited_ids
    ]
    return markdown.rstrip() + ("\n\n" + "\n".join(references) if references else "")


def _source_footnote(source: GroupReportSource) -> str:
    label = _markdown_link_label(source.title) or "未命名来源"
    url = source.source_url.strip()
    target = f"[{label}]({url})" if url else label
    metadata = [
        _report_source_kind_label(source.source_kind),
        source.publisher.replace("\n", " ").strip() or "未知来源",
        _report_source_date(source.published_at),
    ]
    return f"[^{source.citation_id}]: {target} · {' · '.join(metadata)}"


def _markdown_link_label(value: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", str(value or "").replace("\n", " ").strip())


def _report_source_kind_label(value: str) -> str:
    return {
        "wechat": "微信公众号",
        "campus": "校园官网",
        "rss": "RSS订阅",
        "wechat_miniprogram": "微信小程序",
        "bilibili": "B站",
        "douyin": "抖音",
    }.get(str(value or "").strip(), "其他来源")


def _report_source_date(value: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else "日期未知"
