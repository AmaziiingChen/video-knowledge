import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.published_at import PUBLISHED_AT_PARSER_VERSION
from services.content_index import ensure_content_item_for_media
from services.cache import cache_dir_for_url, write_cache_meta
from services.database import connect, initialize_database
from services.local_file_imports import HTML_DOCUMENT_EXTRACTOR_VERSION, extract_html_document
from services.markdown_sync import get_markdown_state


def test_article_preparation_status_endpoint_exposes_live_queue_state():
    with TestClient(app) as client:
        response = client.get("/api/content/article-preparation-status")

    assert response.status_code == 200
    body = response.json()
    assert {"active_count", "queued_count", "pending_count", "completed_count", "failed_count"}.issubset(body)


def test_article_preview_returns_sanitized_cached_html(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://mp.weixin.qq.com/s/example"
    with connect() as connection:
        item = ensure_content_item_for_media(
            source_provider="wechat",
            source_url=source_url,
            video_info={"title": "原始文章"},
            content_type="article",
        )
        connection.commit()

    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "文章标题",
            "author": "作者",
            "published_at": "2026-07-13",
            "body_html": '''
              <div style="visibility:hidden">
                <p onclick="alert(1)">正文</p>
                <img data-src="https://example.com/a.jpg">
                <p data-wechat-image-ocr="true">[图片文字 1]\n图片中的报名时间\n[/图片文字 1]</p>
                <script>bad()</script>
              </div>
            ''',
        }
    })

    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "文章标题"
    assert 'visibility' not in body["html"]
    assert 'onclick' not in body["html"]
    assert '<script' not in body["html"]
    assert 'src="https://example.com/a.jpg"' in body["html"]
    assert "图片文字" not in body["html"]
    assert "图片中的报名时间" not in body["html"]


def test_local_html_import_exposes_clean_text_and_full_safe_source_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "obsidian")
    initialize_database()
    saved_html = b'''<!doctype html>
    <!-- saved from url=(0042)https://example.edu/news/42 -->
    <html><head><title>HTML \xe5\xaf\xbc\xe5\x85\xa5\xe6\xb5\x8b\xe8\xaf\x95</title><style>.article-copy { color: #333; }</style></head>
    <body class="source-page">
      <nav><a href="/a">\xe6\xa0\x8f\xe7\x9b\xae\xe4\xb8\x80</a><a href="/b">\xe6\xa0\x8f\xe7\x9b\xae\xe4\xba\x8c</a></nav>
      <article class="article-copy" onclick="bad()"><h1>\xe6\xad\xa3\xe6\x96\x87\xe6\xa0\x87\xe9\xa2\x98</h1>
        <p>\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xb8\x80\xe6\xae\xb5\xe5\xae\x8c\xe6\x95\xb4\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82</p>
        <p>\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xba\x8c\xe6\xae\xb5\xe5\xae\x8c\xe6\x95\xb4\xe6\xad\xa3\xe6\x96\x87\xe3\x80\x82</p>
        <table><tr><th>\xe9\xa1\xb9\xe7\x9b\xae</th><th>\xe7\x8a\xb6\xe6\x80\x81</th></tr><tr><td>A</td><td>\xe5\xae\x8c\xe6\x88\x90</td></tr></table>
        <img src="images/cover.png"><script>alert('bad')</script></article>
      <footer>\xe9\xa1\xb5\xe8\x84\x9a</footer>
    </body></html>'''

    with TestClient(app) as client:
        imported = client.post(
            "/api/content/import-file",
            files={"file": ("saved-page.html", saved_html, "text/html")},
        )
        assert imported.status_code == 200
        item_id = imported.json()["item"]["id"]
        markdown_path = Path(get_markdown_state(item_id).markdown_draft_path)
        markdown_path.write_text(
            markdown_path.read_text(encoding="utf-8")
            .replace(f"<!-- html-extractor:{HTML_DOCUMENT_EXTRACTOR_VERSION} -->\n\n", "")
            .replace("<!-- ", "legacy-summary-sentinel\n<!-- ", 1),
            encoding="utf-8",
        )
        response = client.get(f"/api/content/{item_id}/article-preview")

    assert response.status_code == 200
    body = response.json()
    assert "第一段完整正文" in body["html"]
    assert "第二段完整正文" in body["html"]
    assert "栏目一" not in body["html"]
    assert 'class="article-table-scroll"' in body["html"]
    assert 'src="https://example.edu/news/images/cover.png"' in body["html"]
    assert "Content-Security-Policy" in body["source_html"]
    assert '<body class="source-page">' in body["source_html"]
    assert 'src="https://example.edu/news/images/cover.png"' in body["source_html"]
    assert "栏目一" in body["source_html"]
    assert "页脚" in body["source_html"]
    assert "padding: 18px 22px 42px" not in body["source_html"]
    assert "onclick" not in body["source_html"]
    assert "<script" not in body["source_html"]
    refreshed_markdown = markdown_path.read_text(encoding="utf-8")
    assert f"<!-- html-extractor:{HTML_DOCUMENT_EXTRACTOR_VERSION} -->" in refreshed_markdown
    assert "legacy-summary-sentinel" in refreshed_markdown


def test_html_extraction_prefers_a_known_content_container_over_navigation_heavy_body():
    navigation = "".join(f'<a href="/section/{number}">栏目导航{number}</a>' for number in range(90))
    source = f'''<!doctype html><html><head><title>辅修通知</title></head><body>
      <header>站点页眉</header><nav>{navigation}</nav>
      <div id="vsb_content_4" class="news_conent_two_text"><div class="v_news_content">
        <p>各学院学生：</p><p>这是需要保留的通知正文，包含具体安排和报名时间。</p>
        <table><tr><th>事项</th><th>日期</th></tr><tr><td>报名</td><td>六月十七日</td></tr></table>
      </div></div><footer>版权信息</footer>
    </body></html>'''.encode()

    extraction = extract_html_document(source, "notice.html")

    assert "需要保留的通知正文" in extraction.text
    assert "报名时间" in extraction.text
    assert "栏目导航" not in extraction.text
    assert "站点页眉" not in extraction.text
    assert "版权信息" not in extraction.text
    assert "栏目导航" not in extraction.body_html
    assert "版权信息" not in extraction.body_html


def test_article_preview_hides_ocr_from_legacy_body_text_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://mp.weixin.qq.com/s/legacy-ocr-preview"
    item = ensure_content_item_for_media(
        source_provider="wechat",
        source_url=source_url,
        video_info={"title": "旧 OCR 文章"},
        content_type="article",
    )
    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "旧 OCR 文章",
            "body_text": "正文开始\n[图片文字 1]\n图片里的表格内容\n[/图片文字 1]\n正文结束",
        }
    })

    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    preview_html = response.json()["html"]
    assert "正文开始" in preview_html
    assert "正文结束" in preview_html
    assert "图片文字" not in preview_html
    assert "图片里的表格内容" not in preview_html


def test_article_preview_hides_image_only_ocr_queue_markers():
    normalized = normalize_article_html(
        '<p data-wechat-image-only-placeholder="true">图文内容，共 1 张图片。图片文字正在后台解析。</p>'
        '<img data-src="https://example.com/image.jpg">'
        '<p>图文内容，共 2 张图片。图片文字会在后台 OCR 后补齐。</p>'
        '<p>这是一段真实正文。</p>'
    )

    assert "图片文字正在后台解析" not in normalized
    assert "图片文字会在后台 OCR 后补齐" not in normalized
    assert "这是一段真实正文。" in normalized
    assert 'src="https://example.com/image.jpg"' in normalized


def test_article_preview_accepts_cached_campus_article(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://ai.sztu.edu.cn/info/1001/example.htm"
    item = ensure_content_item_for_media(
        source_provider="campus",
        source_url=source_url,
        video_info={"title": "学院通知"},
        content_type="article",
    )
    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "学院通知",
            "author": "人工智能学院",
            "published_at": "2026-07-15",
            "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
            "body_html": "<div><p>校园文章正文</p></div>",
            "attachments": [
                {
                    "name": "实验室介绍",
                    "url": "https://ai.sztu.edu.cn/images/lab/SYS.pdf",
                    "download_type": "external",
                },
                {
                    "name": "申请表.docx",
                    "url": "https://ai.sztu.edu.cn/system/_content/download.jsp?id=1",
                    "download_type": "external",
                }
            ],
        }
    })

    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    assert response.json()["author"] == "人工智能学院"
    assert "校园文章正文" in response.json()["html"]
    assert response.json()["attachments"] == [
        {
            "name": "申请表.docx",
            "url": "https://ai.sztu.edu.cn/system/_content/download.jsp?id=1",
            "download_type": "external",
        }
    ]


def test_article_preview_repairs_legacy_wechat_epoch_precision(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://mp.weixin.qq.com/s/legacy-time"
    item = ensure_content_item_for_media(
        source_provider="wechat",
        source_url=source_url,
        video_info={"title": "旧公众号文章"},
        content_type="article",
    )
    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "旧公众号文章",
            "published_at": "2026-07-17 14:58:41",
            "body_html": "<p>旧正文</p>",
        }
    })

    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    assert response.json()["published_at"] == "2026-07-17 14:58"


def test_article_preview_renders_wide_table_with_safe_scroll_container(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://utl.sztu.edu.cn/info/1016/table.htm"
    item = ensure_content_item_for_media(
        source_provider="campus",
        source_url=source_url,
        video_info={"title": "转专业测试结果"},
        content_type="article",
    )
    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "转专业测试结果",
            "body_html": """
              <div class="v_news_content">
                <table border="1" cellpadding="4" onclick="bad()" style="width: 960px">
                  <caption>测试结果汇总</caption>
                  <thead><tr><th scope="col">姓名</th><th>申请专业</th><th>结果</th></tr></thead>
                  <tbody><tr><td rowspan="2">张同学</td><td>物流管理</td><td>通过</td></tr>
                  <tr><td colspan="2">请按通知办理后续手续</td></tr></tbody>
                </table>
              </div>
            """,
            "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
        }
    })

    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    preview_html = response.json()["html"]
    assert 'class="article-table-scroll"' in preview_html
    assert 'aria-label="文章表格，可横向滚动"' in preview_html
    assert '<table style="width: 960px">' in preview_html
    assert 'rowspan="2"' in preview_html
    assert 'colspan="2"' in preview_html
    assert "border-right: 1px solid" in preview_html
    assert "overflow-x: auto" in preview_html
    assert "onclick" not in preview_html
    assert "cellpadding" not in preview_html


def test_article_preview_preserves_only_safe_math_placeholders():
    normalized = normalize_article_html(
        '<p><span class="article-math unsafe" data-latex="\\underline{\\text{专业名称}}" data-display="inline" onclick="bad()">公式</span></p>'
        '<p><span class="article-math" data-latex="' + ("x" * 4001) + '">过长公式</span></p>'
    )

    soup = BeautifulSoup(normalized, "html.parser")
    token = soup.select_one(".article-math")
    assert token is not None
    assert token["data-latex"] == r"\underline{\text{专业名称}}"
    assert token["data-display"] == "inline"
    assert "onclick" not in normalized
    assert len(soup.select(".article-math")) == 1


def test_article_preview_uses_retained_normalized_html_without_refetching(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://nbw.sztu.edu.cn/info/1020/retained.htm"
    item = ensure_content_item_for_media(
        source_provider="campus",
        source_url=source_url,
        video_info={"title": "长期保留的通知"},
        content_type="article",
    )
    write_cache_meta(cache_dir_for_url(source_url), {
        "article_info": {
            "title": "长期保留的通知",
            "body_text": "表格正文已经保留",
            "body_html": "",
            "normalized_html": "<p><strong>一、名单</strong></p><table><tr><th>姓名</th></tr><tr><td>张同学</td></tr></table>",
            "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
        }
    })

    def unexpected_refetch(*args, **kwargs):
        raise AssertionError("retained normalized HTML should not trigger a WebVPN refetch")

    monkeypatch.setattr("routers.content.load_content_source_text", unexpected_refetch)
    with TestClient(app) as client:
        response = client.get(f"/api/content/{item.id}/article-preview")

    assert response.status_code == 200
    assert "张同学" in response.json()["html"]
    assert 'class="article-table-scroll"' in response.json()["html"]


def test_normalizer_recovers_document_semantics_without_site_layout_styles():
    normalized = normalize_article_html(
        """
        <div class="v_news_content" style="width:1200px;margin-left:200px">
          <p style="font-size:24px;color:red"><span><strong>一、报名安排</strong></span></p>
          <p style="text-indent:40px;line-height:300%"><span>请按时提交材料。</span></p>
          <table style="width:960px;background-image:url(https://bad.example/a.png)">
            <tr><td><strong>姓名</strong></td><td><strong>学院</strong></td></tr>
            <tr><td rowspan="2">张同学</td><td>人工智能学院</td></tr>
          </table>
          <script>bad()</script>
        </div>
        """
    )

    assert 'class="article-section-heading"' in normalized
    assert "一、报名安排" in normalized
    assert "font-size" not in normalized
    assert "text-indent" not in normalized
    assert "line-height" not in normalized
    assert "margin-left" not in normalized
    assert "background-image" not in normalized
    assert "<span" not in normalized
    assert '<th scope="col"><strong>姓名</strong></th>' in normalized
    assert 'rowspan="2"' in normalized
    assert "<script" not in normalized


def test_normalizer_recovers_wechat_div_paragraphs_and_preserves_soft_breaks():
    normalized = normalize_article_html(
        "<div><span>第一段的完整正文。</span></div>"
        "<div><span>活动地点：</span><br><span>教学楼 A101</span></div>"
        "<div><span>第三段的完整正文。</span></div>"
    )

    soup = BeautifulSoup(normalized, "html.parser")
    paragraphs = soup.find_all("p")
    assert [paragraph.get_text("", strip=True) for paragraph in paragraphs] == [
        "第一段的完整正文。",
        "活动地点：教学楼 A101",
        "第三段的完整正文。",
    ]
    assert paragraphs[1].find("br") is not None
    assert not soup.find_all("div")


def test_normalizer_splits_explicit_and_sentence_grade_wechat_line_breaks():
    normalized = normalize_article_html(
        "<p>第一段内容。</p><div>第二段已经结束。<br>第三段从单个换行开始。</div>"
        "<div>第四段。<br><br>第五段。</div>"
    )

    soup = BeautifulSoup(normalized, "html.parser")
    assert [paragraph.get_text("", strip=True) for paragraph in soup.find_all("p")] == [
        "第一段内容。",
        "第二段已经结束。",
        "第三段从单个换行开始。",
        "第四段。",
        "第五段。",
    ]
    assert ARTICLE_NORMALIZER_VERSION == 6


def test_normalizer_hides_ocr_blocks_from_legacy_normalized_snapshots():
    normalized = normalize_article_html(
        "<p>原文上段</p>"
        "<p>[图片文字 2]</p><p>旧缓存中的识别文字</p><p>[/图片文字 2]</p>"
        "<p>原文下段</p>"
    )

    assert "原文上段" in normalized
    assert "原文下段" in normalized
    assert "图片文字" not in normalized
    assert "旧缓存中的识别文字" not in normalized


@pytest.mark.parametrize(
    "heading",
    [
        "一、活动介绍",
        "一. 活动介绍",
        "一是活动介绍",
        "（一）活动介绍",
        "第2章 活动介绍",
        "第一节 活动介绍",
        "1）活动介绍",
        "1.1 活动介绍",
        "01 活动介绍",
        "PART 01 活动介绍",
        "IV. Event overview",
    ],
)
def test_normalizer_recognizes_common_simulated_section_headings(heading):
    normalized = normalize_article_html(f"<div><p>{heading}</p><p>普通正文。</p></div>")

    assert 'class="article-section-heading"' in normalized


def test_normalizer_does_not_promote_dates_long_list_items_or_table_cells_as_headings():
    normalized = normalize_article_html(
        """
        <div>
          <p>2026 年 7 月 18 日发布活动安排。</p>
          <p>1. 参加测试学生需携带本人校园卡入场，凭校园卡核对身份。</p>
          <table><tr><td><p><strong>1. 成绩</strong></p></td></tr></table>
        </div>
        """
    )

    assert "article-section-heading" not in normalized
