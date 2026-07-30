"""Stable, WeChat-safe HTML rendering for generated daily and weekly reports.

The report Markdown remains the editable source of truth.  This module is only
responsible for the publication representation: a deliberately small report
layout, source-aware citations, and inline styles that survive the Official
Account draft editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown_it import MarkdownIt


_CITATION = re.compile(r"\[\^S(\d+)\]")
_CITATION_RUN = re.compile(r"\[\^S\d+\](?:\s*\[\^S\d+\])*")
_FOOTNOTE_DEFINITION = re.compile(r"(?m)^\[\^S\d+\]:[^\n]*(?:\n|$)")
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class ReportSource:
    citation_id: str
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""


def render_wechat_report(
    *,
    title: str,
    markdown: str,
    digest: str,
    report_type: str,
    sources: Iterable[ReportSource],
) -> str:
    """Return a self-contained, inline-styled report fragment for WeChat."""
    source_list = list(sources)
    source_by_number = {
        int(source.citation_id.removeprefix("S")): source
        for source in source_list
        if source.citation_id.startswith("S") and source.citation_id[1:].isdigit()
    }
    publication_markdown = _publication_markdown(markdown)
    citation_numbers = _citation_numbers_in_reading_order(publication_markdown)
    display_number_by_source = {
        source_number: display_number
        for display_number, source_number in enumerate(citation_numbers, start=1)
    }
    # Publication references are numbered by their first occurrence in the
    # reader-facing text, rather than by the storage ID assigned upstream.
    # This keeps the superscript marker and the source list in the same,
    # paper-like 1, 2, 3... order.
    referenced_sources = [
        (display_number_by_source[source_number], source_by_number[source_number])
        for source_number in citation_numbers
        if source_number in source_by_number
    ]
    rendered = MarkdownIt("commonmark", {"html": False, "breaks": False}).enable("table").render(
        publication_markdown
    )
    soup = BeautifulSoup(rendered, "html.parser")
    _replace_citations(soup, source_by_number, display_number_by_source)
    character_count, reading_minutes = _reading_metrics(soup)
    _insert_contents_preview(soup)
    _style_document(soup, report_type=report_type)

    root = soup.new_tag(
        "section",
        attrs={
            "style": (
                "max-width:677px;margin:0 auto;padding:8px;box-sizing:border-box;"
                "background:#fdfdf8;color:#4d4f46;font-family:-apple-system,BlinkMacSystemFont,"
                "'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.75;"
            )
        },
    )
    # WeChat renders the article title in its own header.  The body therefore
    # starts with a compact editorial kicker rather than a second, competing
    # H1 card or an internal-status summary.
    root.append(
        _masthead(
            soup,
            report_type=report_type,
            source_count=len(referenced_sources),
            character_count=character_count,
            reading_minutes=reading_minutes,
        )
    )
    for child in list(soup.contents):
        if isinstance(child, NavigableString) and not child.strip():
            continue
        root.append(child.extract())
    if referenced_sources:
        root.append(_source_list(soup, referenced_sources))
    root.append(_original_reading_prompt(soup))
    _wrap_text_nodes(root, soup)
    return str(root)


def _publication_markdown(markdown: str) -> str:
    value = _FRONTMATTER.sub("", str(markdown or "").replace("\r\n", "\n").replace("\r", "\n"))
    value = _FOOTNOTE_DEFINITION.sub("", value)
    lines = value.splitlines()
    kept: list[str] = []
    latest_section = ""
    for line in lines:
        normalized = line.strip().lstrip("#").strip()
        # These are workbench-only headings, not reader-facing report sections.
        if normalized in {"AI 摘要", "报告正文"}:
            continue
        if normalized == "追问记录":
            break
        if line.startswith("# "):
            continue
        if line.startswith("> 分组："):
            continue
        if line.startswith("## "):
            latest_section = normalized
        # The group report generator sometimes repeats an H2 verbatim as its
        # first H3.  It is useful in the workbench, but looks like a mistaken
        # duplicate in a reader-facing article.
        if line.startswith("### ") and normalized == latest_section:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _citation_numbers_in_reading_order(markdown: str) -> list[int]:
    """Collect each citation once, ordered by its first appearance."""
    seen: set[int] = set()
    numbers: list[int] = []
    for match in _CITATION.finditer(markdown):
        number = int(match.group(1))
        if number not in seen:
            seen.add(number)
            numbers.append(number)
    return numbers


def _reading_metrics(soup: BeautifulSoup) -> tuple[int, int]:
    """Return reader-facing characters and an estimate at 400 chars/minute."""
    preview = BeautifulSoup(str(soup), "html.parser")
    # Citation markers are navigational metadata, not part of the article's
    # reading length. The source list has not been appended at this stage.
    for marker in preview.find_all("sup"):
        marker.extract()
    text = preview.get_text("", strip=True)
    character_count = len(re.sub(r"\s+", "", text))
    return character_count, max(1, (character_count + 399) // 400)


def _masthead(
    soup: BeautifulSoup,
    *,
    report_type: str,
    source_count: int,
    character_count: int,
    reading_minutes: int,
) -> Tag:
    labels = {"daily": "每日简报", "weekly": "每周回顾", "range": "专题汇总"}
    card = soup.new_tag(
        "section",
        attrs={
            "style": (
                "margin:0 0 26px;padding:0 0 12px;border-bottom:1px solid #bfc1b7;"
            )
        },
    )
    meta = soup.new_tag("section", attrs={"style": "display:flex;align-items:center;gap:8px;"})
    dot = soup.new_tag("span", attrs={"style": "width:8px;height:8px;background:#1e1f23;border-radius:50%;display:inline-block;overflow:hidden;font-size:0;line-height:0;"})
    dot.string = " "
    meta.append(dot)
    label = soup.new_tag("span", attrs={"style": "font-size:10px;font-weight:700;letter-spacing:3px;color:#65675e;"})
    label.string = labels.get(report_type, "报告")
    meta.append(label)
    rule = soup.new_tag("span", attrs={"style": "flex:1;height:1px;background:#bfc1b7;display:inline-block;overflow:hidden;font-size:0;line-height:0;"})
    rule.string = " "
    meta.append(rule)
    count = soup.new_tag("span", attrs={"style": "font-size:11px;white-space:nowrap;color:#65675e;font-weight:600;"})
    count.string = f"参考 {source_count} 篇资料"
    meta.append(count)
    card.append(meta)
    reading = soup.new_tag(
        "section",
        attrs={
            "style": (
                "display:flex;align-items:baseline;justify-content:space-between;gap:12px;"
                "margin-top:8px;font-size:11px;line-height:1.6;color:#65675e;"
            )
        },
    )
    metrics = soup.new_tag("span")
    metrics.string = f"全文共 {character_count} 字，预计 {reading_minutes} 分钟阅读"
    reading.append(metrics)
    notice = soup.new_tag(
        "span",
        attrs={
            "style": (
                "margin-left:auto;color:#8a7658;font-size:10px;line-height:1.6;"
                "text-align:right;"
            )
        },
    )
    notice.string = "内容由 AI 辅助整理，请以原始来源为准"
    reading.append(notice)
    card.append(reading)
    return card


def _style_document(soup: BeautifulSoup, *, report_type: str) -> None:
    section_subtitle = {
        "daily": "DAILY BRIEF",
        "weekly": "WEEKLY REVIEW",
        "range": "TOPIC DIGEST",
    }.get(report_type, "REPORT BRIEF")
    section_number = 0
    for tag in list(soup.find_all(True)):
        if tag.name == "h2":
            title = tag.get_text(" ", strip=True)
            if title == "本期概览":
                wrapper = soup.new_tag("section", attrs={"style": "margin-top:28px;"})
                line = soup.new_tag(
                    "section",
                    attrs={"style": "display:flex;align-items:center;gap:10px;padding-bottom:10px;border-bottom:1px solid #bfc1b7;"},
                )
                label = soup.new_tag(
                    "span",
                    attrs={"style": "font-size:10px;font-weight:800;letter-spacing:3px;color:#ed7b2f;"},
                )
                label.string = "OVERVIEW"
                heading = soup.new_tag(
                    "p",
                    attrs={"style": "margin:0;font-size:17px;line-height:1.45;font-weight:800;color:#23251d;"},
                )
                heading.string = title
                line.extend([label, heading])
                wrapper.append(line)
                tag.replace_with(wrapper)
                continue

            section_number += 1
            wrapper = soup.new_tag("section", attrs={"style": "margin-top:28px;"})
            line = soup.new_tag("section", attrs={"style": "display:flex;align-items:center;gap:14px;"})
            number_block = soup.new_tag("section", attrs={"style": "text-align:center;flex-shrink:0;"})
            number = soup.new_tag("p", attrs={"style": "margin:0;font-size:24px;font-weight:800;color:#23251d;line-height:1;letter-spacing:-2px;"})
            number.string = f"{section_number:02d}"
            number_block.append(number)
            part = soup.new_tag("p", attrs={"style": "margin:0;font-size:8px;font-weight:700;color:#9ea096;letter-spacing:2px;"})
            part.string = "PART"
            number_block.append(part)
            divider = soup.new_tag("span", attrs={"style": "width:1px;height:36px;background:#bfc1b7;flex-shrink:0;display:inline-block;overflow:hidden;font-size:0;line-height:0;"})
            divider.string = " "
            heading_block = soup.new_tag("section")
            heading = soup.new_tag("p", attrs={"style": "margin:0 0 2px;font-size:17px;line-height:1.45;font-weight:800;color:#23251d;"})
            heading.string = title
            heading_block.append(heading)
            subtitle = soup.new_tag("p", attrs={"style": "margin:0;font-size:10px;font-weight:600;color:#65675e;letter-spacing:1.2px;"})
            subtitle.string = section_subtitle
            heading_block.append(subtitle)
            line.extend([number_block, divider, heading_block])
            wrapper.append(line)
            tag.replace_with(wrapper)
        elif tag.name == "h3":
            tag.name = "p"
            tag["style"] = "margin:22px 0 10px;padding:0 0 8px;border-bottom:1px solid #bfc1b7;font-size:15px;line-height:1.55;font-weight:800;color:#23251d;"
        elif tag.name == "h4":
            tag.name = "p"
            tag["style"] = "margin:20px 0 8px;padding-left:10px;border-left:3px solid #ed7b2f;font-size:14px;line-height:1.6;font-weight:800;color:#23251d;"
        elif tag.name == "p":
            tag["style"] = "margin:0 0 14px;font-size:14px;line-height:1.9;text-align:left;color:#4d4f46;"
        elif tag.name in {"ul", "ol"}:
            tag["style"] = "margin:0 0 16px;padding-left:20px;color:#4d4f46;"
        elif tag.name == "li":
            tag["style"] = "margin:0 0 8px;font-size:14px;line-height:1.85;text-align:left;"
        elif tag.name == "blockquote":
            tag["style"] = "margin:0 0 16px;padding:12px 14px;border-left:3px solid #ed7b2f;background:#eeefe9;color:#4d4f46;"
        elif tag.name == "table":
            tag["style"] = "width:100%;margin:0 0 18px;border-collapse:collapse;font-size:13px;color:#4d4f46;"
        elif tag.name in {"th", "td"}:
            tag["style"] = "padding:8px;border:1px solid #bfc1b7;line-height:1.65;text-align:left;"
        elif tag.name == "strong":
            tag["style"] = "color:#23251d;font-weight:800;"
        elif tag.name == "em":
            tag["style"] = "color:#65675e;"
        elif tag.name == "a":
            if tag.find_parent("sup"):
                tag["style"] = "color:#9ea096;text-decoration:none;font-size:10px;font-weight:500;"
            else:
                tag["style"] = "color:#1e1f23;text-decoration:none;font-weight:700;"
        elif tag.name == "hr":
            tag["style"] = "border:0;border-top:1px solid #bfc1b7;margin:28px 0;"
        elif tag.name == "img":
            tag["style"] = "max-width:100%;height:auto;display:block;margin:0 auto 18px;border-radius:6px;"
    _flatten_lists(soup)


def _insert_contents_preview(soup: BeautifulSoup) -> None:
    """Add a complete, non-clickable reading guide after the overview.

    Official Account drafts do not reliably preserve in-page anchors.  A short
    directory still gives readers a quick map of a long report without making
    a promise that the editor cannot keep.
    """
    headings = [heading.get_text(" ", strip=True) for heading in soup.find_all("h2")]
    entries = [heading for heading in headings if heading not in {"本期概览", "参考来源"}]
    if not entries:
        return

    anchor = next(
        (heading for heading in soup.find_all("h2") if heading.get_text(" ", strip=True) != "本期概览"),
        None,
    )
    if not anchor:
        return

    # Reuse the olive-journal light masthead language: quiet olive surface,
    # thin rule, compact uppercase-style label.  This is a complete outline
    # by request, so readers can see every subject covered by a long report.
    card = soup.new_tag(
        "section",
        attrs={
            "style": (
                "margin:22px 0 26px;background:#eeefe9;border:1px solid #bfc1b7;"
                "border-radius:6px;padding:12px 16px;"
            )
        },
    )
    header = soup.new_tag(
        "section",
        attrs={
            "style": "display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px;"
        },
    )
    label = soup.new_tag(
        "span",
        attrs={"style": "font-size:10px;font-weight:800;letter-spacing:3px;color:#23251d;"},
    )
    label.string = "本期目录"
    header.append(label)
    total = soup.new_tag("span", attrs={"style": "font-size:10px;color:#65675e;font-weight:700;"})
    total.string = f"共 {len(entries)} 个主题"
    header.append(total)
    card.append(header)

    for index, entry in enumerate(entries, start=1):
        row = soup.new_tag(
            "section",
            attrs={"style": "margin:0 0 5px;font-size:12px;line-height:1.7;color:#4d4f46;"},
        )
        number = soup.new_tag(
            "span",
            attrs={"style": "display:inline-block;width:24px;color:#ed7b2f;font-weight:800;"},
        )
        number.string = f"{index:02d}"
        row.append(number)
        row.append(NavigableString(entry))
        card.append(row)
    anchor.insert_before(card)


def _flatten_lists(soup: BeautifulSoup) -> None:
    """Avoid the draft editor's unstable nested-list normalization.

    Native lists are rendered consistently in the application preview but the
    Official Account editor may introduce an extra empty bullet for a tight
    list, especially when an item begins with bold text.  Publish a visual
    list made of ordinary paragraphs instead: it keeps every item and nested
    level while leaving no platform-controlled marker to be duplicated.
    """
    for source_list in reversed(list(soup.find_all(["ul", "ol"]))):
        ordered = source_list.name == "ol"
        block = soup.new_tag("section", attrs={"style": "margin:0 0 16px;max-width:100%;box-sizing:border-box;"})
        items = source_list.find_all("li", recursive=False)
        for index, item in enumerate(items, start=1):
            line = soup.new_tag(
                "section",
                attrs={
                    "style": (
                        "display:flex;align-items:flex-start;gap:8px;margin:0 0 10px;"
                        "max-width:100%;box-sizing:border-box;"
                    )
                },
            )
            marker = soup.new_tag(
                "span",
                attrs={"style": "flex:0 0 28px;width:28px;text-align:center;padding-top:8px;box-sizing:border-box;"},
            )
            if ordered:
                number = soup.new_tag(
                    "span",
                    attrs={"style": "font-size:13px;line-height:1.5;color:#ed7b2f;font-weight:800;"},
                )
                number.string = f"{index}."
                marker.append(number)
            else:
                dot = soup.new_tag(
                    "span",
                    attrs={
                        "style": (
                            "display:inline-block;width:9px;height:9px;background:#ed7b2f;"
                            "border-radius:50%;overflow:hidden;vertical-align:middle;font-size:0;line-height:0;"
                        )
                    },
                )
                dot.string = " "
                marker.append(dot)
            line.append(marker)
            content = soup.new_tag(
                "section",
                attrs={
                    "style": (
                        "flex:1;min-width:0;font-size:14px;line-height:1.9;text-align:left;"
                        "color:#4d4f46;word-break:break-word;overflow-wrap:anywhere;"
                    )
                },
            )
            nested_blocks: list[Tag] = []
            for child in list(item.contents):
                if isinstance(child, NavigableString) and not child.strip():
                    child.extract()
                    continue
                # A paragraph inside a list item is only a Markdown parser
                # wrapper.  Move its inline children into our one clean row.
                if isinstance(child, Tag) and child.name == "p":
                    for inline in list(child.contents):
                        content.append(inline.extract())
                    child.extract()
                elif isinstance(child, Tag) and child.name == "section":
                    nested_blocks.append(child.extract())
                else:
                    content.append(child.extract())
            line.append(content)
            block.append(line)
            if nested_blocks:
                nested = soup.new_tag(
                    "section",
                    attrs={"style": "margin:-2px 0 6px;padding-left:28px;max-width:100%;box-sizing:border-box;"},
                )
                for nested_block in nested_blocks:
                    nested.append(nested_block)
                block.append(nested)
        source_list.replace_with(block)


def _replace_citations(
    soup: BeautifulSoup,
    source_by_number: dict[int, ReportSource],
    display_number_by_source: dict[int, int],
) -> None:
    for text_node in list(soup.find_all(string=_CITATION)):
        text = str(text_node)
        parent = text_node.parent
        if not parent:
            continue
        cursor = 0
        replacement: list[object] = []
        for citation_run in _CITATION_RUN.finditer(text):
            if citation_run.start() > cursor:
                replacement.append(NavigableString(text[cursor:citation_run.start()]))
            marker = soup.new_tag(
                "sup",
                attrs={
                    "style": (
                        "display:inline-block;margin-left:2px;white-space:nowrap;line-height:1;"
                        "vertical-align:super;color:#9ea096;font-size:10px;font-weight:500;"
                    )
                },
            )
            citation_numbers = sorted(
                {int(citation.group(1)) for citation in _CITATION.finditer(citation_run.group(0))},
                key=lambda number: (display_number_by_source.get(number, number), number),
            )
            for index, number in enumerate(citation_numbers):
                if index:
                    marker.append(NavigableString("，"))
                source = source_by_number.get(number)
                display_number = display_number_by_source.get(number, number)
                if source and _safe_url(source.url):
                    link = soup.new_tag(
                        "a",
                        href=source.url,
                        attrs={
                            "style": (
                                "color:#9ea096;text-decoration:none;font-size:10px;font-weight:500;"
                            )
                        },
                    )
                    link.string = str(display_number)
                    marker.append(link)
                else:
                    marker.append(NavigableString(str(display_number)))
            replacement.append(marker)
            cursor = citation_run.end()
        if cursor < len(text):
            replacement.append(NavigableString(text[cursor:]))
        for node in replacement[::-1]:
            text_node.insert_after(node)
        text_node.extract()


def _source_list(soup: BeautifulSoup, sources: list[tuple[int, ReportSource]]) -> Tag:
    section = soup.new_tag("section", attrs={"style": "margin-top:32px;padding-top:18px;border-top:1px solid #bfc1b7;"})
    heading_row = soup.new_tag("section", attrs={"style": "display:flex;align-items:baseline;gap:8px;margin-bottom:13px;"})
    heading = soup.new_tag("p", attrs={"style": "margin:0;font-size:14px;font-weight:800;color:#23251d;"})
    heading.string = "参考来源"
    heading_row.append(heading)
    count = soup.new_tag("span", attrs={"style": "font-size:11px;color:#65675e;"})
    count.string = f"{len(sources)} 篇资料"
    heading_row.append(count)
    section.append(heading_row)
    for number, source in sources:
        row = soup.new_tag("p", attrs={"style": "margin:0 0 9px;font-size:12px;line-height:1.75;color:#4d4f46;"})
        prefix = soup.new_tag("span", attrs={"style": "display:inline-block;min-width:20px;color:#b45d20;font-weight:800;"})
        prefix.string = f"{number}."
        row.append(prefix)
        if _safe_url(source.url):
            link = soup.new_tag(
                "a",
                href=source.url,
                attrs={"style": "color:#23251d;text-decoration:none;font-weight:600;"},
            )
            link.string = source.title or "原始文章"
            row.append(link)
        else:
            row.append(NavigableString(source.title or "原始文章"))
        details = " · ".join(value for value in (source.publisher, source.published_at) if value)
        if details:
            meta = soup.new_tag("span", attrs={"style": "color:#65675e;"})
            meta.string = f" · {details}"
            row.append(meta)
        section.append(row)
    return section


def _original_reading_prompt(soup: BeautifulSoup) -> Tag:
    """Point readers to WeChat's native ``阅读原文`` entry without duplicating its URL."""
    section = soup.new_tag(
        "section",
        attrs={
            "style": (
                "margin-top:26px;padding:14px 0 2px;border-top:1px solid #d8d9d1;"
                "text-align:center;"
            )
        },
    )
    label = soup.new_tag(
        "p",
        attrs={"style": "margin:0 0 4px;color:#23251d;font-size:13px;font-weight:800;letter-spacing:1px;"},
    )
    label.string = "延伸阅读"
    section.append(label)
    description = soup.new_tag(
        "p",
        attrs={"style": "margin:0;color:#65675e;font-size:11px;line-height:1.7;"},
    )
    description.append(NavigableString("点击文末“"))
    action = soup.new_tag("span", attrs={"style": "color:#b45d20;font-weight:800;"})
    action.string = "阅读原文"
    description.append(action)
    description.append(NavigableString("”，查看网页阅读版与完整资料链接"))
    section.append(description)
    return section


def _wrap_text_nodes(root: Tag, soup: BeautifulSoup) -> None:
    for text_node in list(root.find_all(string=True)):
        if not str(text_node).strip() or text_node.parent is None:
            continue
        parent = text_node.parent
        if parent.name in {"script", "style"} or (parent.name == "span" and parent.has_attr("leaf")):
            continue
        leaf_tag = soup.new_tag("span", attrs={"leaf": ""})
        leaf_tag.string = str(text_node)
        text_node.replace_with(leaf_tag)


def _safe_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
