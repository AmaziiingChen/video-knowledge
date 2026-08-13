from bs4 import BeautifulSoup

from services.campus_html_content import (
    absolutize_content_urls,
    article_attachment_scope,
    candidate_nodes,
    dedupe_attachments,
)


def test_content_helpers_keep_article_urls_scope_and_unique_nodes():
    soup = BeautifulSoup(
        '<form name="_newscontent_fromname"><section><div><img data-src="images/a.png"><a href="files/a.pdf">附件</a></div></section></form>',
        "html.parser",
    )
    content = soup.div
    assert content is not None

    absolutize_content_urls(content, "https://example.edu.cn/news/item.html")

    assert content.img["src"] == "https://example.edu.cn/news/images/a.png"
    assert "data-src" not in content.img.attrs
    assert content.a["href"] == "https://example.edu.cn/news/files/a.pdf"
    assert article_attachment_scope(content).name == "form"
    assert dedupe_attachments([{"url": "a"}, {"url": "a"}, {"url": "b"}]) == [
        {"url": "a"},
        {"url": "b"},
    ]
    assert list(candidate_nodes(soup, ("a", "form a"))) == [content.a]
