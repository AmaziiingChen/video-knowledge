"""Pure BeautifulSoup helpers shared by campus article extraction paths."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


def absolutize_content_urls(content: Tag, base_url: str) -> None:
    for image in content.find_all("img"):
        src = str(
            image.get("data-src")
            or image.get("data-original")
            or image.get("src")
            or ""
        ).strip()
        if src:
            image["src"] = urljoin(base_url, src)
            image.attrs.pop("data-src", None)
            image.attrs.pop("data-original", None)
    for anchor in content.find_all("a", href=True):
        anchor["href"] = urljoin(base_url, str(anchor.get("href") or ""))


def dedupe_attachments(value: list[dict[str, str]]) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for attachment in value:
        url = str(attachment.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append(attachment)
    return attachments


def article_attachment_scope(content: Tag) -> Tag:
    """Keep attachment discovery inside the article wrapper when possible."""
    form = content.find_parent("form", attrs={"name": "_newscontent_fromname"})
    if isinstance(form, Tag):
        return form

    parent = content.parent
    if isinstance(parent, Tag):
        grandparent = parent.parent
        if isinstance(grandparent, Tag):
            return grandparent
        return parent
    return content


def attachment_name_from_url(url: str) -> str:
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    return path_name if "." in path_name else "查看附件"


def candidate_nodes(soup: BeautifulSoup, selectors: Iterable[str]) -> Iterator[Tag]:
    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            if not isinstance(node, Tag) or id(node) in seen:
                continue
            seen.add(id(node))
            yield node
