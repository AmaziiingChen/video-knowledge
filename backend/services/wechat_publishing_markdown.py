"""Pure Markdown and digest formatting for WeChat draft publication."""

from __future__ import annotations

import textwrap

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

# The draft API rejects descriptions that exceed this UTF-8 byte limit. A
# character-count limit is unsafe for Chinese reports.
WECHAT_DIGEST_MAX_BYTES = 120


def markdown_to_wechat_html(markdown: str) -> str:
    """Render the report body to conservative HTML accepted by WeChat drafts."""
    source = _strip_report_frontmatter(markdown)
    renderer = MarkdownIt("commonmark", {"html": False, "breaks": False}).enable("table")
    html = renderer.render(source)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "iframe", "form", "input", "button"]):
        tag.decompose()
    allowed = {
        "p", "br", "strong", "em", "del", "blockquote", "ul", "ol", "li",
        "h1", "h2", "h3", "h4", "table", "thead", "tbody", "tr", "th", "td",
        "a", "img", "hr", "code", "pre",
    }
    for tag in soup.find_all(True):
        if tag.name not in allowed:
            tag.unwrap()
            continue
        attributes = {}
        if tag.name == "a" and tag.get("href"):
            attributes["href"] = str(tag["href"])
        if tag.name == "img" and tag.get("src"):
            attributes["src"] = str(tag["src"])
        if tag.name in {"img", "a"} and tag.get("title"):
            attributes["title"] = str(tag["title"])
        tag.attrs = attributes
    return str(soup)


def default_digest(markdown: str) -> str:
    """Produce the reader-facing digest without internal report metadata."""
    lines = [
        line
        for line in str(markdown or "").splitlines()
        if not line.strip().startswith("> 分组：") and not line.strip().startswith("[^S")
    ]
    text = plain_text("\n".join(lines))
    return textwrap.shorten(text, width=120, placeholder="…") if text else ""


def wechat_digest(value: str) -> str:
    """Keep the digest under WeChat's byte-based description limit."""
    return truncate_utf8(str(value or "").strip(), WECHAT_DIGEST_MAX_BYTES)


def truncate_utf8(value: str, max_bytes: int) -> str:
    kept: list[str] = []
    size = 0
    for character in value:
        character_size = len(character.encode("utf-8"))
        if size + character_size > max_bytes:
            break
        kept.append(character)
        size += character_size
    return "".join(kept)


def plain_text(value: str) -> str:
    return " ".join(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True).split())


def _strip_report_frontmatter(markdown: str) -> str:
    source = str(markdown or "").strip()
    source = source.replace("\r\n", "\n")
    source = source.replace("\r", "\n")
    if source.startswith("---\n"):
        closing = source.find("\n---", 4)
        if closing >= 0:
            source = source[closing + 4 :].lstrip("\n")
    # The reader already presents the document title. Avoid a duplicated H1 in
    # the public article while retaining all report headings below it.
    return _drop_first_heading(source)


def _drop_first_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[:index] + lines[index + 1 :]).lstrip()
        if line.strip():
            break
    return markdown
