from __future__ import annotations

import re
from html import escape
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup, Comment, Tag


ARTICLE_NORMALIZER_VERSION = 6
_DROP_TAGS = {
    "script", "style", "noscript", "iframe", "object", "embed", "form", "input",
    "button", "select", "option", "textarea", "svg", "canvas", "video", "audio",
}
_SAFE_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "del", "div", "dl", "dt", "em", "figcaption", "figure", "h1", "h2",
    "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "li", "mark", "ol", "p",
    "pre", "s", "section", "small", "span", "strong", "sub", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
_VOID_TAGS = {"br", "col", "hr", "img"}
_MEANINGFUL_EMPTY_TAGS = {"table", "td", "th"}
_SAFE_SEMANTIC_CLASSES = {"article-section-heading", "article-math", "article-xhs-tag"}
_INLINE_ONLY_TAGS = {
    "a", "abbr", "b", "br", "code", "del", "em", "i", "ins", "mark",
    "s", "small", "span", "strong", "sub", "sup", "u",
}
_TAG_STYLE_PROPERTIES = {
    "table": {"width", "min-width", "max-width", "table-layout"},
    "col": {"width", "min-width", "max-width"},
    "td": {"width", "min-width", "max-width", "text-align", "vertical-align"},
    "th": {"width", "min-width", "max-width", "text-align", "vertical-align"},
    "img": {"width", "height", "max-width", "object-fit"},
    "p": {"text-align"},
    "div": {"text-align"},
    "h1": {"text-align"},
    "h2": {"text-align"},
    "h3": {"text-align"},
    "h4": {"text-align"},
    "h5": {"text-align"},
    "h6": {"text-align"},
}
_STYLE_FORBIDDEN_VALUES = ("url(", "expression", "javascript:", "@import", "behavior:")
_SECTION_HEADING_RE = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十百]+(?:[、.．]|是(?=\S))|"
    r"第[一二三四五六七八九十百\d]+(?:章|节|条|篇|部分)|"
    r"[（(【][一二三四五六七八九十百\d]+[）)】]|"
    r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|"
    r"\d{1,2}(?:\.\d{1,2}){1,3}(?:[.．、）)]|\s+)|"
    r"\d{1,2}(?:[.．、）)]|\s+(?![\s年月日]))|"
    r"(?:PART|NO\.)\s*\d{1,2}\b|"
    r"[IVX]{1,5}[.．、]"
    r")",
    re.IGNORECASE,
)
_IMAGE_OCR_BLOCK_RE = re.compile(
    r"\[图片文字\s*(\d+)\].*?\[/图片文字\s*\1\]",
    re.DOTALL,
)
_IMAGE_ONLY_PLACEHOLDER_RE = re.compile(
    r"^图文内容，\s*共\s*\d+\s*张图片。图片文字(?:正在后台解析|会在后台\s*OCR\s*后补齐)。$"
)


def normalize_article_html(body_html: str, *, preserve_local_media: bool = True) -> str:
    """Convert captured site HTML into a compact, safe document fragment.

    The result deliberately keeps document semantics such as headings, lists,
    merged table cells, figures and links, while removing the source website's
    layout system.  It is safe to retain after the original capture is pruned.
    """
    soup = BeautifulSoup(body_html or "", "lxml")
    root = soup.body or soup

    # OCR augments the text material consumed by search and AI, but it is not
    # part of the source document's visual layout.  New snapshots retain an
    # explicit attribute; legacy normalized snapshots only retain the marker
    # text, so handle both representations before applying display semantics.
    for node in list(root.select("[data-wechat-image-ocr]")):
        node.decompose()
    _remove_image_only_placeholders(root)
    legacy_fragment = _IMAGE_OCR_BLOCK_RE.sub(
        "",
        "".join(str(node) for node in root.contents),
    )
    soup = BeautifulSoup(legacy_fragment, "lxml")
    root = soup.body or soup

    for comment in list(root.find_all(string=lambda value: isinstance(value, Comment))):
        comment.extract()
    for node in list(root.find_all(_DROP_TAGS)):
        node.decompose()

    for node in list(root.find_all(True)):
        if node.parent is None:
            continue
        tag_name = str(node.name or "").lower()
        if tag_name not in _SAFE_TAGS:
            node.unwrap()
            continue

        original_style = str(node.get("style") or "")
        original_classes = {
            str(value).strip()
            for value in (node.get("class") or [])
            if str(value).strip() in _SAFE_SEMANTIC_CLASSES
        }
        # Generic source spans are purely presentational and should not leak
        # source layout. Retain only application-owned semantic inline tokens.
        if tag_name == "span" and not {"article-math", "article-xhs-tag"}.intersection(original_classes):
            node.unwrap()
            continue
        safe_attributes: dict[str, str | list[str]] = {}
        safe_style = _safe_tag_style(tag_name, original_style)
        if safe_style:
            safe_attributes["style"] = safe_style

        if tag_name == "img":
            if not _normalize_image(node, safe_attributes, preserve_local_media=preserve_local_media):
                node.decompose()
                continue
        elif tag_name == "a":
            href = str(node.get("href") or "").strip()
            if href.startswith(("https://", "http://")):
                safe_attributes.update({"href": href, "target": "_blank", "rel": "noreferrer"})
                title = str(node.get("title") or "").strip()
                if title:
                    safe_attributes["title"] = title[:240]
            else:
                node.unwrap()
                continue
        elif tag_name in {"td", "th"}:
            for attribute in ("colspan", "rowspan"):
                value = _safe_positive_integer(node.get(attribute), maximum=100)
                if value:
                    safe_attributes[attribute] = value
            if tag_name == "th":
                scope = str(node.get("scope") or "").strip().lower()
                if scope in {"col", "row", "colgroup", "rowgroup"}:
                    safe_attributes["scope"] = scope
        elif tag_name == "col":
            span = _safe_positive_integer(node.get("span"), maximum=100)
            if span:
                safe_attributes["span"] = span
        elif tag_name in {"ol", "li"}:
            start = _safe_positive_integer(node.get("start") if tag_name == "ol" else node.get("value"))
            if start:
                safe_attributes["start" if tag_name == "ol" else "value"] = start

        if tag_name == "span" and "article-math" in original_classes:
            latex = _safe_latex_expression(node.get("data-latex"))
            display = str(node.get("data-display") or "").strip().lower()
            if latex:
                safe_attributes["data-latex"] = latex
                safe_attributes["data-display"] = "block" if display == "block" else "inline"
            else:
                node.unwrap()
                continue

        if original_classes:
            safe_attributes["class"] = sorted(original_classes)
        node.attrs = safe_attributes

    _recover_implicit_paragraphs(root)
    _promote_table_header_rows(root)
    _mark_section_headings(root)
    _remove_empty_layout_nodes(root)
    return "".join(str(node) for node in root.contents).strip()


def _remove_image_only_placeholders(root: Tag) -> None:
    """Hide internal OCR queue markers from every reader-preview generation.

    Image-only WeChat notices need a small body-text marker while their OCR
    job is pending, otherwise they are rejected as empty during capture.  It
    is pipeline metadata, not article content, and must never enter the
    reader.  The text fallback also handles snapshots normalized before the
    explicit marker attribute was introduced.
    """
    for node in list(root.select("[data-wechat-image-only-placeholder]")):
        node.decompose()
    for node in list(root.find_all(["p", "div", "section"])):
        if node.find("img") is not None:
            continue
        if _IMAGE_ONLY_PLACEHOLDER_RE.fullmatch(node.get_text(" ", strip=True)):
            node.decompose()


def _safe_latex_expression(value: object) -> str:
    expression = str(value or "").strip()
    if not expression or len(expression) > 4000 or "\x00" in expression:
        return ""
    return expression


def build_local_article_html(body_html: str, *, media_base_url: str) -> str:
    """Build sandbox-ready article HTML using the shared campus reading style."""
    normalized = normalize_article_html(body_html)
    soup = BeautifulSoup(normalized, "lxml")
    root = soup.body or soup
    _rewrite_local_media_urls(root, media_base_url=media_base_url)
    _wrap_article_tables(soup, root)
    fragment = "".join(str(node) for node in root.contents).strip()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src http://127.0.0.1:* http://localhost:* https: data:; style-src 'unsafe-inline'">
  <style>
    :root {{
      color-scheme: light;
      --article-ink: #282c30;
      --article-muted: #697078;
      --article-rule: #dfe3e6;
      --article-soft: #f5f7f8;
      --article-accent: #2878ad;
      scrollbar-color: rgba(92, 101, 109, 0.25) transparent;
      scrollbar-width: thin;
    }}
    html, body {{ scrollbar-gutter: auto; }}
    * {{ box-sizing: border-box; scrollbar-color: rgba(92, 101, 109, 0.25) transparent; scrollbar-width: thin; }}
    html::-webkit-scrollbar, body::-webkit-scrollbar, *::-webkit-scrollbar {{ width: 6px; height: 6px; background: transparent; }}
    html::-webkit-scrollbar-track, body::-webkit-scrollbar-track, *::-webkit-scrollbar-track {{ border: 0; background: transparent; box-shadow: none; }}
    html::-webkit-scrollbar-thumb, body::-webkit-scrollbar-thumb, *::-webkit-scrollbar-thumb {{
      min-height: 40px;
      border: 2px solid transparent;
      border-radius: 999px;
      background: transparent;
      background-clip: padding-box;
      box-shadow: none;
    }}
    html:hover::-webkit-scrollbar-thumb, body:hover::-webkit-scrollbar-thumb, *:hover::-webkit-scrollbar-thumb {{ background: rgba(92, 101, 109, 0.25); background-clip: padding-box; }}
    html::-webkit-scrollbar-thumb:hover, body::-webkit-scrollbar-thumb:hover, *::-webkit-scrollbar-thumb:hover {{ background: rgba(92, 101, 109, 0.4); background-clip: padding-box; }}
    html::-webkit-scrollbar-corner, body::-webkit-scrollbar-corner, *::-webkit-scrollbar-corner {{ background: transparent; }}
    html, body {{ min-height: 100%; margin: 0; background: transparent; }}
    body {{
      width: min(680px, 100%);
      margin: 0 auto;
      padding: 2px 20px 38px;
      color: var(--article-ink);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 16px;
      line-height: 1.82;
      letter-spacing: 0.005em;
      overflow-wrap: anywhere;
      text-rendering: optimizeLegibility;
    }}
    main {{ display: block; }}
    p, div, section {{ max-width: 100%; }}
    p {{ margin: 0 0 1.1em; }}
    blockquote > p:last-child {{ margin-bottom: 0; }}
    h1, h2, h3, h4, h5, h6, .article-section-heading {{
      margin: 1.85em 0 0.72em;
      color: #202428;
      font-family: "Songti SC", "STSong", "SimSun", "NSimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif;
      font-weight: 700;
      line-height: 1.48;
      letter-spacing: 0.01em;
    }}
    h1 {{ font-size: 1.48em; }}
    h2 {{ font-size: 1.32em; }}
    h3, .article-section-heading {{ font-size: 1.16em; }}
    h4, h5, h6 {{ font-size: 1.04em; }}
    body > main > :is(h1, h2, h3, h4, h5, h6, .article-section-heading):first-child {{ margin-top: 0.5em; }}
    strong, b {{ font-weight: 650; }}
    ul, ol {{ margin: 0.72em 0 1.12em; padding-left: 1.65em; }}
    li {{ margin: 0.3em 0; padding-left: 0.16em; }}
    li > p {{ margin-bottom: 0.45em; }}
    li > p:last-child {{ margin-bottom: 0; }}
    li::marker {{ color: var(--article-muted); font-variant-numeric: tabular-nums; }}
    blockquote {{
      margin: 1.2em 0;
      padding: 0.82em 1em;
      color: #485058;
      background: var(--article-soft);
    }}
    blockquote > :first-child {{ margin-top: 0; }}
    blockquote > :last-child {{ margin-bottom: 0; }}
    hr {{ height: 1px; margin: 1.8em 0; border: 0; background: var(--article-rule); }}
    figure {{ margin: 1.45em 0; text-align: center; }}
    figcaption {{ margin-top: 0.62em; color: var(--article-muted); font-size: 13px; line-height: 1.55; }}
    img {{ display: block; max-width: 100%; height: auto; margin: 1.3em auto; object-fit: contain; }}
    figure img {{ margin: 0 auto; }}
    .article-table-scroll {{
      width: 100%;
      margin: 1.45em 0;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      border: 1px solid #d8dde1;
      background: #fff;
      scrollbar-width: thin;
      scrollbar-color: #aeb5ba transparent;
    }}
    .article-table-scroll:focus-visible {{ outline: 2px solid var(--article-accent); outline-offset: 2px; }}
    .article-table-scroll::-webkit-scrollbar {{ height: 7px; }}
    .article-table-scroll::-webkit-scrollbar-thumb {{ background: #aeb5ba; }}
    table {{
      width: max-content;
      min-width: 100%;
      max-width: none;
      margin: 0 !important;
      border: 0;
      border-collapse: collapse;
      border-spacing: 0;
      table-layout: auto;
      background: #fff;
      color: #30363b;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 14px;
      line-height: 1.58;
    }}
    caption {{ padding: 11px 12px; color: #515a61; font-weight: 650; text-align: left; background: var(--article-soft); }}
    th, td {{
      min-width: 88px;
      padding: 9px 11px;
      border-right: 1px solid #dfe3e6;
      border-bottom: 1px solid #dfe3e6;
      color: inherit;
      text-align: left;
      vertical-align: top;
      white-space: normal;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    th:last-child, td:last-child {{ border-right: 0; }}
    table > tr:last-child > th, table > tr:last-child > td,
    table > tbody:last-child > tr:last-child > th,
    table > tbody:last-child > tr:last-child > td,
    table > tfoot:last-child > tr:last-child > th,
    table > tfoot:last-child > tr:last-child > td {{ border-bottom: 0; }}
    thead th {{ background: #eef2f4; color: #39434a; font-weight: 650; }}
    tbody tr:nth-child(even) {{ background: #fafbfb; }}
    pre, code {{ font-family: "SFMono-Regular", Consolas, monospace; }}
    pre {{ max-width: 100%; padding: 0.85em 1em; overflow-x: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: var(--article-soft); font-size: 13px; line-height: 1.62; }}
    :not(pre) > code {{ padding: 0.08em 0.28em; background: var(--article-soft); font-size: 0.9em; }}
    a {{ color: var(--article-accent); text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    a:hover {{ color: #175d8b; }}
    a:focus-visible {{ outline: 2px solid var(--article-accent); outline-offset: 2px; }}
    .article-xhs-tag {{
      display: inline-block;
      margin: 0 0.18em;
      padding: 0.04em 0.46em;
      border: 1px solid #c9dce8;
      border-radius: 999px;
      background: #edf5f9;
      color: #22678f;
      font-size: 0.84em;
      font-weight: 600;
      line-height: 1.5;
      white-space: nowrap;
    }}
    sup, sub {{ line-height: 0; }}
    .article-math {{ display: inline-block; max-width: 100%; vertical-align: -0.16em; overflow-x: auto; overflow-y: hidden; }}
    .article-math[data-display="block"] {{ display: block; margin: 1em 0; text-align: center; vertical-align: baseline; }}
    .article-math math {{ font-size: 1.03em; }}
    @media (max-width: 520px) {{
      body {{ padding-inline: 14px; font-size: 15px; line-height: 1.76; }}
      th, td {{ min-width: 76px; padding: 8px 9px; }}
    }}
    @media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; }} }}
  </style>
</head>
<body><main class="article-document">{fragment}</main></body>
</html>"""


def build_local_html_source_preview(
    document_html: str,
    *,
    source_url: str = "",
) -> str:
    """Render a retained HTML file in a non-executable local iframe.

    This deliberately keeps much more of the source document than the reader
    normalizer, but removes executable/interactive elements and supplies a
    strict CSP. It is an inspection view, not a browser session.
    """
    soup = BeautifulSoup(document_html or "", "lxml")
    body = soup.body or soup
    for comment in list(body.find_all(string=lambda value: isinstance(value, Comment))):
        comment.extract()
    for node in list(body.find_all({"script", "noscript", "iframe", "object", "embed", "form", "input", "button", "select", "option", "textarea"})):
        node.decompose()
    for node in list(body.find_all(True)):
        for attribute in list(node.attrs):
            lowered = str(attribute).lower()
            if lowered.startswith("on") or lowered in {"srcdoc", "action", "formaction"}:
                del node.attrs[attribute]
        if node.name == "img":
            source = str(node.get("src") or node.get("data-src") or "").strip()
            if source and source_url and not source.startswith(("https://", "http://", "data:")):
                source = urljoin(source_url, source)
            if source.startswith(("https://", "http://", "data:")):
                node["src"] = source
            else:
                node.decompose()
                continue
            node.attrs.pop("data-src", None)
        elif node.name == "a":
            href = str(node.get("href") or "").strip()
            if href and source_url and not href.startswith(("https://", "http://", "#")):
                href = urljoin(source_url, href)
            if href.startswith(("https://", "http://")):
                node["href"] = href
                node["target"] = "_blank"
                node["rel"] = "noreferrer"
            else:
                node.attrs.pop("href", None)

    body_attributes = _safe_source_body_attributes(body)
    source_styles = "\n".join(
        _safe_source_style_tag(style.get_text("\n", strip=True))
        for style in soup.find_all("style")
    )
    # Styles are copied into our controlled document head.  Remove the
    # original nodes as well: a style element in the source body would
    # otherwise bypass the small sanitiser above when the fragment is rebuilt.
    for style in soup.find_all("style"):
        style.decompose()
    fragment = "".join(str(node) for node in body.contents).strip()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'">
  <style>
    {source_styles}
    html, body {{ margin: 0; min-height: 100%; }}
  </style>
</head>
<body{body_attributes}>{fragment}</body>
</html>"""


def _safe_source_body_attributes(body: Tag) -> str:
    """Retain presentation hooks needed by the saved page without copying code."""
    attributes: list[str] = []
    for name in ("class", "id", "style", "dir", "lang"):
        value = body.get(name)
        if isinstance(value, list):
            value = " ".join(str(part) for part in value if str(part).strip())
        text = str(value or "").strip()
        if text:
            attributes.append(f' {name}="{escape(text, quote=True)}"')
    return "".join(attributes)


def _safe_source_style_tag(style: str) -> str:
    """Keep source typography but reject CSS constructs that load/execute code."""
    value = str(style or "")
    value = re.sub(r"@import\s+[^;]+;", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:expression|javascript:|behavior\s*:)", "", value, flags=re.IGNORECASE)
    # BeautifulSoup decodes character entities in style text. Prevent an
    # encoded closing tag from escaping the controlled style block we create.
    value = re.sub(r"</style", r"<\\/style", value, flags=re.IGNORECASE)
    return value[:200_000]


def _normalize_image(
    node: Tag,
    safe_attributes: dict[str, str | list[str]],
    *,
    preserve_local_media: bool,
) -> bool:
    local_media_path = str(node.get("data-local-media-path") or "").strip()
    source = str(node.get("data-src") or node.get("src") or "").strip()
    remote_source = source if source.startswith(("https://", "http://")) else ""
    if preserve_local_media and local_media_path:
        safe_attributes["data-local-media-path"] = local_media_path
    if remote_source:
        safe_attributes["src"] = remote_source
    if not safe_attributes.get("data-local-media-path") and not remote_source:
        return False
    alt = str(node.get("alt") or "").strip()
    if alt:
        safe_attributes["alt"] = alt[:500]
    natural_width = _safe_positive_integer(node.get("data-w") or node.get("width"))
    if natural_width:
        safe_attributes["width"] = natural_width
    natural_height = _safe_positive_integer(node.get("height"))
    if not natural_height and natural_width:
        try:
            image_ratio = float(str(node.get("data-ratio") or "").strip())
        except ValueError:
            image_ratio = 0
        if 0 < image_ratio <= 10:
            natural_height = _safe_positive_integer(round(int(natural_width) * image_ratio))
    if natural_height:
        safe_attributes["height"] = natural_height
    safe_attributes["loading"] = "lazy"
    safe_attributes["decoding"] = "async"
    return True


def _recover_implicit_paragraphs(root: Tag | BeautifulSoup) -> None:
    """Turn visual line breaks from captured pages into readable paragraphs.

    Many WeChat editors export prose as ``div`` blocks or as a text run split
    by ``<br>`` tags instead of using ``<p>``.  Source styles are intentionally
    discarded in this reader, so leaving those nodes untouched makes adjacent
    paragraphs visually merge.  We recover only unambiguous document prose:
    block wrappers with inline content, explicit blank lines, and single line
    breaks that clearly separate two complete sentences.  Intentional soft
    breaks (poetry, addresses and short labels) remain ``<br>`` elements.
    """
    # Split existing paragraphs first.  A paragraph never contains another
    # block-level element, so this is safe and lets the heading detector see
    # each recovered block independently.
    for paragraph in list(root.find_all("p")):
        _split_inline_node_into_paragraphs(paragraph)

    # Process inner wrappers first: an outer layout div can then retain its
    # structural children while simple ``<div>一段正文</div>`` becomes a real p.
    for container in reversed(list(root.find_all(["div", "section"]))):
        if container.parent is None or _should_keep_container(container):
            continue
        groups = _inline_paragraph_groups(container)
        if not groups:
            continue
        if len(groups) == 1:
            container.name = "p"
            continue
        _replace_node_with_paragraphs(container, groups)

    # A few pages put a plain text run directly under body.  Promote it only
    # when the root is genuinely inline-only; media and document structures
    # keep their existing placement.
    direct_tags = [child for child in root.contents if isinstance(child, Tag)]
    if not direct_tags or all(child.name in _INLINE_ONLY_TAGS for child in direct_tags):
        groups = _inline_paragraph_groups(root)
        if groups:
            for child in list(root.contents):
                child.extract()
            for group in groups:
                root.append(_new_paragraph(root, group, {}))


def _should_keep_container(container: Tag) -> bool:
    if container.find_parent(["table", "figure", "figcaption", "pre"]) is not None:
        return True
    for child in container.contents:
        if isinstance(child, Tag) and child.name not in _INLINE_ONLY_TAGS:
            return True
    return not _nodes_text(container.contents)


def _split_inline_node_into_paragraphs(paragraph: Tag) -> None:
    if paragraph.parent is None:
        return
    groups = _inline_paragraph_groups(paragraph)
    if len(groups) > 1:
        _replace_node_with_paragraphs(paragraph, groups)


def _inline_paragraph_groups(container: Tag | BeautifulSoup) -> list[list[object]]:
    """Return inline child groups separated by paragraph-grade line breaks."""
    children = list(container.contents)
    groups: list[list[object]] = []
    current: list[object] = []
    index = 0
    while index < len(children):
        child = children[index]
        if isinstance(child, Tag) and child.name == "br":
            run_end = index
            while run_end < len(children):
                run_child = children[run_end]
                if not isinstance(run_child, Tag) or run_child.name != "br":
                    break
                run_end += 1
            following = children[run_end:]
            is_paragraph_break = (
                run_end - index >= 2
                or _looks_like_sentence_boundary(current, following)
            )
            if is_paragraph_break:
                if _nodes_text(current):
                    groups.append(current)
                current = []
            else:
                current.extend(children[index:run_end])
            index = run_end
            continue
        current.append(child)
        index += 1
    if _nodes_text(current):
        groups.append(current)
    return groups


def _looks_like_sentence_boundary(before: list[object], after: list[object]) -> bool:
    """Identify the common ``完整句子<br>完整句子`` WeChat export pattern."""
    before_text = _nodes_text(before)
    after_text = _nodes_text(after)
    if len(before_text) < 5 or len(after_text) < 6:
        return False
    if _SECTION_HEADING_RE.match(after_text):
        return True
    return before_text[-1:] in {"。", "！", "？", "；", ".", "!", "?", ";"}


def _nodes_text(nodes: list[object]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Tag):
            parts.append(node.get_text(" ", strip=True))
        else:
            parts.append(str(node).strip())
    return " ".join(part for part in parts if part).strip()


def _new_paragraph(root: Tag | BeautifulSoup, nodes: list[object], attributes: dict) -> Tag:
    soup: Tag | BeautifulSoup = root
    while not isinstance(soup, BeautifulSoup) and soup.parent is not None:
        soup = soup.parent
    if not isinstance(soup, BeautifulSoup):
        # Every normalizer root belongs to a BeautifulSoup document.  This is
        # just a defensive fallback for direct unit-level use.
        soup = BeautifulSoup("", "lxml")
    paragraph = soup.new_tag("p")
    paragraph.attrs = dict(attributes)
    for node in nodes:
        if isinstance(node, Tag):
            node.extract()
        paragraph.append(node)
    return paragraph


def _replace_node_with_paragraphs(node: Tag, groups: list[list[object]]) -> None:
    for group in groups:
        node.insert_before(_new_paragraph(node, group, dict(node.attrs)))
    node.decompose()


def _mark_section_headings(root: Tag | BeautifulSoup) -> None:
    for paragraph in root.find_all("p"):
        if paragraph.find_parent("table") is not None:
            continue
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if not text or len(text) > 60 or not _SECTION_HEADING_RE.match(text):
            continue
        meaningful_children = [child for child in paragraph.children if isinstance(child, Tag) or str(child).strip()]
        has_emphasis = any(
            isinstance(child, Tag) and child.name in {"b", "strong"}
            for child in meaningful_children
        )
        if has_emphasis or len(text) <= 24:
            paragraph["class"] = ["article-section-heading"]


def _promote_table_header_rows(root: Tag | BeautifulSoup) -> None:
    """Recover table headers commonly exported by Word as bold ``td`` cells."""
    for table in root.find_all("table"):
        first_row = table.find("tr")
        if first_row is None or first_row.find("th", recursive=False) is not None:
            continue
        cells = first_row.find_all("td", recursive=False)
        if len(cells) < 2 or not all(cell.get_text(" ", strip=True) for cell in cells):
            continue
        if not all(cell.find(["b", "strong"]) is not None for cell in cells):
            continue
        for cell in cells:
            cell.name = "th"
            cell["scope"] = "col"


def _remove_empty_layout_nodes(root: Tag | BeautifulSoup) -> None:
    for node in reversed(list(root.find_all(True))):
        if node.parent is None or node.name in _VOID_TAGS or node.name in _MEANINGFUL_EMPTY_TAGS:
            continue
        has_media = node.find(["img", "table", "hr"]) is not None
        if not has_media and not node.get_text("", strip=True):
            node.decompose()


def _rewrite_local_media_urls(root: Tag | BeautifulSoup, *, media_base_url: str) -> None:
    for image in root.find_all("img"):
        local_media_path = str(image.get("data-local-media-path") or "").strip()
        if local_media_path:
            image["src"] = f"{media_base_url}?path={quote(local_media_path, safe='')}"
        image.attrs.pop("data-local-media-path", None)


def _wrap_article_tables(soup: BeautifulSoup, root: Tag | BeautifulSoup) -> None:
    """Give top-level article tables an accessible horizontal scroll boundary."""
    for table in list(root.find_all("table")):
        if table.find_parent("table") is not None:
            continue
        wrapper = soup.new_tag("div")
        wrapper.attrs = {
            "class": "article-table-scroll",
            "role": "region",
            "aria-label": "文章表格，可横向滚动",
            "tabindex": "0",
        }
        table.wrap(wrapper)


def _safe_tag_style(tag_name: str, style: str) -> str:
    allowed_properties = _TAG_STYLE_PROPERTIES.get(tag_name, set())
    if not allowed_properties:
        return ""
    declarations: list[str] = []
    for declaration in style.split(";"):
        property_name, separator, raw_value = declaration.partition(":")
        property_name = property_name.strip().lower()
        value = raw_value.strip()
        lowered_value = value.lower().replace("\\", "")
        if (
            not separator
            or property_name not in allowed_properties
            or not value
            or len(value) > 120
            or any(forbidden in lowered_value for forbidden in _STYLE_FORBIDDEN_VALUES)
        ):
            continue
        declarations.append(f"{property_name}: {value}")
    return "; ".join(declarations)


def _safe_positive_integer(value, *, maximum: int = 10000) -> str:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return ""
    return str(number) if 0 < number <= maximum else ""
