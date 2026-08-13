"""Deterministic HTML rendering for OCR-derived campus documents."""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt


_DOCUMENT_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"html": True})
_DOCUMENT_MATH_BLOCK_RE = re.compile(
    r"(?P<dollar>\$\$\s*(?P<dollar_value>[\s\S]*?)\s*\$\$)|"
    r"(?P<bracket>\\\[\s*(?P<bracket_value>[\s\S]*?)\s*\\\])"
)
_DOCUMENT_MATH_INLINE_RE = re.compile(
    r"(?P<dollar>\$(?!\$)\s*(?P<dollar_value>[^\n$]{1,4000}?)\s*\$(?!\$))|"
    r"(?P<paren>\\\(\s*(?P<paren_value>[^\n]{1,4000}?)\s*\\\))"
)
_DOCUMENT_TABLE_HEADER_HINT_RE = re.compile(
    r"(?:序号|项目|名称|型号|规格|数量|单位|品牌|预算|金额|日期|时间|联系人|地址|内容|要求|类别|标的|备注|姓名|学院|结果)"
)


def render_document_markdown_html(text: str) -> str:
    """Render PaddleOCR document Markdown for the existing article reader."""
    prepared = _replace_document_math_tokens(str(text or "").strip())
    rendered = _DOCUMENT_MARKDOWN_RENDERER.render(prepared)
    rendered = _promote_document_table_headers(rendered)
    return '<article class="procurement-pdf-content">' + rendered + "</article>"


def text_to_article_html(text: str) -> str:
    """Compatibility renderer for existing procurement PDF callers."""
    return render_document_markdown_html(text)


def _replace_document_math_tokens(text: str) -> str:
    """Mark constrained LaTeX tokens for the reader's deterministic renderer."""

    def replacement(match: re.Match[str], *, display: bool) -> str:
        value = next(
            (
                match.group(name)
                for name in ("dollar_value", "bracket_value", "paren_value")
                if match.groupdict().get(name) is not None
            ),
            "",
        )
        expression = str(value or "").strip()
        if not _looks_like_document_math(expression):
            return match.group(0)
        encoded = html.escape(expression, quote=True)
        fallback = html.escape(expression)
        return (
            f'<span class="article-math" data-latex="{encoded}" '
            f'data-display="{"block" if display else "inline"}">{fallback}</span>'
        )

    text = _DOCUMENT_MATH_BLOCK_RE.sub(
        lambda match: replacement(match, display=True), text
    )
    return _DOCUMENT_MATH_INLINE_RE.sub(
        lambda match: replacement(match, display=False), text
    )


def _looks_like_document_math(expression: str) -> bool:
    if not expression or len(expression) > 4000 or "\x00" in expression:
        return False
    return bool(re.search(r"\\[A-Za-z]+|[{}_^]|(?:<=|>=|≤|≥|≈|≠|=)", expression))


def _promote_document_table_headers(fragment: str) -> str:
    """Give OCR document tables semantic headers without losing merged cells."""
    soup = BeautifulSoup(fragment, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_rows = [rows[0]]
        first_cells = rows[0].find_all(["td", "th"], recursive=False)
        if (
            any(
                str(cell.get("colspan") or "1") not in {"", "1"} for cell in first_cells
            )
            and len(rows) > 1
        ):
            header_rows.append(rows[1])
        for row in header_rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if not _looks_like_document_header_row(cells):
                continue
            for cell in cells:
                if cell.name == "td":
                    cell.name = "th"
                if not cell.get("scope"):
                    cell["scope"] = (
                        "colgroup"
                        if str(cell.get("colspan") or "1") not in {"", "1"}
                        else "col"
                    )
    return "".join(str(node) for node in soup.contents)


def _looks_like_document_header_row(cells: list[Tag]) -> bool:
    if len(cells) < 2 or any(not cell.get_text(" ", strip=True) for cell in cells):
        return False
    labels = [cell.get_text(" ", strip=True) for cell in cells]
    if any(len(label) > 32 for label in labels):
        return False
    hits = sum(bool(_DOCUMENT_TABLE_HEADER_HINT_RE.search(label)) for label in labels)
    return hits >= max(1, (len(labels) + 1) // 2)
