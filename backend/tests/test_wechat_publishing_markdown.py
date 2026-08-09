from services.wechat_publishing_markdown import (
    WECHAT_DIGEST_MAX_BYTES,
    default_digest,
    markdown_to_wechat_html,
    wechat_digest,
)


def test_wechat_html_omits_frontmatter_title_and_unsafe_elements():
    html = markdown_to_wechat_html(
        "---\ntitle: 本期\n---\n# 本期标题\n\n## 正文\n\n[链接](https://example.com '来源')\n\n<script>bad()</script>"
    )

    assert "本期标题" not in html
    assert "<h2>正文</h2>" in html
    assert 'href="https://example.com"' in html
    assert 'title="来源"' in html
    assert "<script" not in html


def test_wechat_digest_skips_internal_metadata_and_respects_utf8_limit():
    digest = default_digest(
        "> 分组：校园动态\n[^S001]: 内部脚注\n\n# 标题\n\n" + ("中文内容" * 80)
    )

    assert "分组" not in digest
    assert "内部脚注" not in digest
    truncated = wechat_digest("中" * 100)
    assert len(truncated.encode("utf-8")) <= WECHAT_DIGEST_MAX_BYTES
    assert truncated == "中" * 40
