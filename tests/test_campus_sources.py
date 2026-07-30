import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from routers import campus_sources as campus_router
from services.article_preview import normalize_article_html
from services.cache import cache_dir_for_url, read_cache_meta
from services.campus_sources import (
    CampusArticle,
    discover_campus_articles,
    fetch_campus_article,
    get_campus_source,
    parse_campus_list,
)
from services import article_fetcher
from services import campus_sources as campus_source_service
from services.article_fetcher import ArticleFetchResult
from services.paddle_ocr import OcrImageResult
from services.campus_source_settings import (
    enable_unconfigured_sources_for_digest,
    load_campus_source_settings,
    record_campus_source_sync,
    update_campus_source_setting,
)
from services.campus_sync import persist_campus_articles
from services.content_index import backfill_campus_source_folders, ensure_campus_source_folder
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.wechat_reports import create_group


def test_gwt_list_parser_keeps_notice_metadata_and_rejects_navigation():
    html = """
    <ul class="news-ul">
      <li class="clearfix">
        <div class="width02"><a>通知公告</a></div>
        <div class="width03"><a>教务处</a></div>
        <div class="width04"><a href="/info/1029/1234.htm" title="关于选课安排的通知">关于选课安排的通知</a></div>
        <div class="width06">2026-07-15</div>
      </li>
      <li class="clearfix"><div class="width04"><a href="/index.htm">首页</a></div></li>
    </ul>
    """

    articles = parse_campus_list(html, source=get_campus_source("gwt"), section="公文通")

    assert len(articles) == 1
    assert articles[0].title == "关于选课安排的通知"
    assert articles[0].published_at == "2026-07-15"
    assert articles[0].department == "教务处"


def test_sztu_source_exposes_only_campus_news():
    source = get_campus_source("sztu")

    assert source.name == "深圳技术大学"
    assert source.sections == {
        "校园新闻": "https://www.sztu.edu.cn/jdjd/xyxw.htm",
    }
    assert source.include_wechat_links is False


def test_procurement_source_exposes_public_announcement_sections():
    source = get_campus_source("sztu-procurement")

    assert source.name == "采购与招投标管理中心"
    assert list(source.sections) == ["采购公告", "成交公告", "采购意向", "合同公示"]
    assert source.sections["采购公告"].endswith("typeDetail=XQ")


def test_procurement_discovery_uses_public_json_feed_and_keeps_canonical_detail_url(monkeypatch):
    records = {
        "resultset": [
            {
                "id": "public-record-1",
                "syncId": "PUBLICSYNC1",
                "subject": "实验设备采购公告（SZTU20260001）",
                "beginTime": "2026-07-18 10:30:00",
                "tenderNo": "SZTU20260001",
            }
        ]
    }
    monkeypatch.setattr(campus_source_service, "_query_sztu_procurement", lambda *_: records)

    articles = discover_campus_articles(
        "sztu-procurement",
        section="采购公告",
        session=object(),
    )

    assert len(articles) == 1
    assert articles[0].title == "实验设备采购公告（SZTU20260001）"
    assert articles[0].published_at == "2026-07-18 10:30:00"
    assert articles[0].section == "采购公告"
    assert "record_id=public-record-1" in articles[0].url
    assert articles[0].url.endswith("#/publish/PUBLICSYNC1")


def test_procurement_article_reader_uses_public_payload_and_preserves_article_body(monkeypatch):
    record = {
        "id": "public-record-1",
        "subject": "实验设备采购公告（SZTU20260001）",
        "beginTime": "2026-07-18 10:30:00",
        "tenderNo": "SZTU20260001",
        "contentHtml": """
            <div class='detail-content'>
              <p>项目名称：实验设备</p>
              <p>预算金额：100000 元</p>
              <a href='/files/notice.pdf'>采购文件</a>
            </div>
        """,
    }
    monkeypatch.setattr(campus_source_service, "_query_sztu_procurement", lambda *_: {"resultset": [record]})
    url = (
        "https://ztb.sztu.edu.cn/provider/?record_id=public-record-1"
        "&keyword=SZTU20260001&section=%E9%87%87%E8%B4%AD%E5%85%AC%E5%91%8A#/publish/PUBLICSYNC1"
    )

    article = fetch_campus_article(url, session=object())

    assert article["title"] == "实验设备采购公告（SZTU20260001）"
    assert article["published_at"] == "2026-07-18 10:30:00"
    assert "预算金额：100000 元" in article["body_text"]
    assert article["attachments"] == [
        {
            "name": "采购文件",
            "url": "https://ztb.sztu.edu.cn/files/notice.pdf",
            "download_type": "external",
        }
    ]


def test_procurement_article_reader_keeps_bare_cms_html_fragment_without_provider_fallback(monkeypatch):
    record = {
        "id": "cms-fragment-record",
        "subject": "紫外-可见分光光度计更正公告",
        "beginTime": "2026-07-16 11:04:17",
        # This mirrors the affected CMS shape: valid sibling nodes but no
        # outer div/body/article container.
        "contentHtml": """
            <h2>一、项目基本情况</h2>
            <p>原采购项目编号：SZDL2026001049</p>
            <table><tr><td rowspan='2'>序号</td><td>技术要求</td></tr><tr><td>光谱带宽≤1.8nm</td></tr></table>
            <h2>二、更正信息</h2><p>更正日期：2026年7月16日</p>
        """,
    }
    monkeypatch.setattr(campus_source_service, "_query_sztu_procurement", lambda *_: {"resultset": [record]})

    def unexpected_provider(*args, **kwargs):
        raise AssertionError("inline CMS fragment must not enter provider fallback")

    monkeypatch.setattr(campus_source_service, "_fetch_sztu_procurement_provider_article", unexpected_provider)
    url = "https://ztb.sztu.edu.cn/sfw_cms/e?page=cms.detail&record_id=cms-fragment-record&section=%E9%87%87%E8%B4%AD%E5%85%AC%E5%91%8A"

    article = fetch_campus_article(url, session=object())

    assert "SZDL2026001049" in article["body_text"]
    assert "更正日期：2026年7月16日" in article["body_text"]
    soup = BeautifulSoup(str(article["body_html"]), "html.parser")
    assert soup.select_one("table td")["rowspan"] == "2"


def test_procurement_article_reader_uses_provider_pdf_when_cms_has_no_body(monkeypatch):
    record = {
        "id": "public-record-pdf",
        "syncId": "PUBLICPDF1",
        "subject": "嵌入式 PDF 采购公告（SZTU20260002）",
        "beginTime": "2026-07-18 10:30:00",
        "tenderNo": "SZTU20260002",
        "contentHtml": "",
    }
    monkeypatch.setattr(campus_source_service, "_query_sztu_procurement", lambda *_: {"resultset": [record]})
    captured = {}

    def provider_article(url, session, *, record, title, published_at, content_item_id):
        captured.update({"url": url, "record": record, "title": title, "published_at": published_at, "content_item_id": content_item_id})
        return {
            "url": url,
            "platform": "campus",
            "title": title,
            "body_text": "这是从公开 PDF 中提取的完整采购公告正文。",
            "body_html": "<article><p>这是从公开 PDF 中提取的完整采购公告正文。</p></article>",
            "author": "采购与招投标管理中心",
            "published_at": published_at,
            "images": [],
            "attachments": [{"name": "采购公告.pdf", "url": "https://provider.yuncaitong.cn/publish/a.pdf", "download_type": "external"}],
        }

    monkeypatch.setattr(campus_source_service, "_fetch_sztu_procurement_provider_article", provider_article)
    url = "https://ztb.sztu.edu.cn/provider/?record_id=public-record-pdf&keyword=SZTU20260002&section=%E9%87%87%E8%B4%AD%E5%85%AC%E5%91%8A#/publish/PUBLICPDF1"

    article = fetch_campus_article(url, session=object())

    assert captured["record"] == record
    assert captured["title"] == "嵌入式 PDF 采购公告（SZTU20260002）"
    assert "完整采购公告正文" in article["body_text"]
    assert article["attachments"][0]["url"].startswith("https://provider.yuncaitong.cn/")


def test_procurement_provider_pdf_url_uses_china_time_and_fragment_publish_id():
    assert campus_source_service._procurement_publish_id_from_fragment("/publish/PUBLICPDF1") == "PUBLICPDF1"
    assert campus_source_service._procurement_provider_document_url(
        {"contentType": "PDF", "createTime": 1784278855791},
        "20MROPK8DRARWAII",
    ) == "https://provider.yuncaitong.cn/publish/2026/07/17/20MROPK8DRARWAII/content.pdf"


def test_procurement_pdf_uses_existing_paddle_ocr_pipeline(monkeypatch):
    class Response:
        content = b"%PDF-1.7 scanned procurement notice"

    monkeypatch.setattr(campus_source_service, "_safe_get_procurement_provider", lambda *_: Response())
    monkeypatch.setattr(
        campus_source_service,
        "recognize_document_bytes",
        lambda payload, **kwargs: OcrImageResult(
            url=kwargs["url"],
            text="# 采购公告\n\n扫描件中的采购需求、技术要求及投标安排。",
            status="succeeded",
            cloud_submitted=True,
        ),
    )

    article = campus_source_service._fetch_procurement_provider_pdf(
        object(),
        url="https://ztb.sztu.edu.cn/provider/?record_id=record",
        document_url="https://provider.yuncaitong.cn/publish/notice.pdf",
        title="扫描件采购公告",
        published_at="2026-07-18 10:30:00",
        content_item_id="item-pdf",
    )

    assert article is not None
    assert "扫描件中的采购需求" in article["body_text"]
    assert article["document_ocr"] == {
        "attempted": True,
        "status": "succeeded",
        "cloud_submitted": True,
        "error": "",
    }
    assert article["document_markdown"].startswith("# 采购公告\n\n")


def test_procurement_pdf_renders_paddle_markdown_and_embedded_tables():
    html = campus_source_service._text_to_article_html(
        """# 采购公告

## 采购需求

<table border=1><tr><td rowspan=2>标的名称</td><td colspan=2>数量</td></tr><tr><td>数值</td><td>单位</td></tr><tr><td>探测平台</td><td>1</td><td>套</td></tr></table>

1. 在线下载
2. 按时提交
"""
    )

    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("h1").get_text(strip=True) == "采购公告"
    assert soup.find("h2").get_text(strip=True) == "采购需求"
    assert [item.get_text(strip=True) for item in soup.select("ol > li")] == ["在线下载", "按时提交"]
    assert soup.select_one("table th").get_text(strip=True) == "标的名称"
    assert soup.select_one("table th")["rowspan"] == "2"
    assert soup.select_one("table th").find_next("th")["colspan"] == "2"
    assert "&lt;table" not in html

    normalized = normalize_article_html(html)
    assert '<th rowspan="2" scope="col">标的名称</th>' in normalized
    assert '<th colspan="2" scope="colgroup">数量</th>' in normalized


def test_procurement_pdf_marks_spaced_latex_for_the_safe_reader_renderer():
    rendered = campus_source_service.render_document_markdown_html(
        "$ \\underline{\\text{轨道交通运营管理专业三维虚拟仿真实验平台}} $的潜在投标人应按时递交文件。"
    )
    soup = BeautifulSoup(rendered, "html.parser")
    token = soup.select_one(".article-math")

    assert token is not None
    assert token["data-latex"] == r"\underline{\text{轨道交通运营管理专业三维虚拟仿真实验平台}}"
    assert token["data-display"] == "inline"
    assert "$ " not in rendered


def test_sztu_news_parser_keeps_internal_articles_and_skips_wechat_links():
    html = """
    <div class="yy-lt"><ul>
      <li id="line_u17_0">
        <a href="../info/1003/4444.htm">
          <div class="yy-ifo">
            <span>2026/07/17</span>
            <h3>深技大召开2026年上半年工作总结大会</h3>
            <p>会议总结了学校上半年工作。</p>
          </div>
        </a>
      </li>
      <li id="line_u17_1">
        <a href="https://mp.weixin.qq.com/s/example">
          <div class="yy-ifo">
            <span>2026/07/16</span>
            <h3>公众号已经发布的校园新闻</h3>
          </div>
        </a>
      </li>
    </ul></div>
    """

    articles = parse_campus_list(
        html,
        source=get_campus_source("sztu"),
        section="校园新闻",
    )

    assert [(article.title, article.published_at, article.url) for article in articles] == [
        (
            "深技大召开2026年上半年工作总结大会",
            "2026-07-17",
            "https://www.sztu.edu.cn/info/1003/4444.htm",
        )
    ]


def test_sztu_article_metadata_keeps_department_and_visible_date():
    soup = BeautifulSoup(
        """
        <div class="c-ifo">
          <p><span>时间: 2026/07/17</span> 信息来源: 党委组织部 党委办公室 浏览量:</p>
        </div>
        """,
        "html.parser",
    )

    assert campus_source_service._extract_article_date(soup) == "2026-07-17"
    assert campus_source_service._extract_article_author(
        soup,
        source=get_campus_source("sztu"),
    ) == "党委组织部 党委办公室"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<div class="detail_message"><div class="message_right">2026/06/16 10:08:07</div></div>', "2026-06-16 10:08:07"),
        ('<div class="ar_title"><span>发布时间：2026-07-13 10:39</span></div>', "2026-07-13 10:39"),
        ('<div class="article-meta"><span>发布时间：2026年07月16日 16:07</span></div>', "2026-07-16 16:07"),
        ('<div class="newsd-left"><div>July 15, 2026</div></div>', "2026-07-15"),
    ],
)
def test_campus_article_date_keeps_visible_precision(html, expected):
    soup = BeautifulSoup(html, "html.parser")

    assert campus_source_service._extract_article_date(soup) == expected


def test_campus_article_date_prefers_header_metadata_over_dates_in_body():
    soup = BeautifulSoup(
        """
        <div class="article_box"><div class="sub_box">发布日期：2024年06月14日 10:59</div></div>
        <div class="v_news_content"><p>活动于2024年4月8日举行。</p></div>
        """,
        "html.parser",
    )

    assert campus_source_service._extract_article_date(soup) == "2024-06-14 10:59"


def test_gwt_discovery_paginates_until_two_week_date_boundary():
    def page_html(rows):
        return "<ul class='news-ul'>" + "".join(
            f"""
            <li class="clearfix">
              <div class="width03"><a>{department}</a></div>
              <div class="width04"><a href="/info/1029/{notice_id}.htm" title="{title}">{title}</a></div>
              <div class="width06">{published_at}</div>
            </li>
            """
            for notice_id, title, published_at, department in rows
        ) + "</ul>"

    pages = {
        "1": page_html([
            ("1001", "第一则近期公文通知", "2026-07-15", "教务处"),
            ("1002", "第二则近期公文通知", "2026-07-10", "学生处"),
        ]),
        "2": page_html([
            ("1003", "边界当天公文通知", "2026-07-02", "科研处"),
            ("1004", "边界之前公文通知", "2026-07-01", "后勤基建部"),
        ]),
        "3": page_html([
            ("1005", "更早历史公文通知", "2026-06-30", "党政办公室"),
        ]),
    }

    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url, text):
            self.url = url
            self.text = text

        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.pages = []

        def get(self, url, **kwargs):
            page_number = parse_qs(urlparse(url).query)["PAGENUM"][0]
            self.pages.append(page_number)
            return Response(url, pages[page_number])

    session = Session()
    articles = discover_campus_articles(
        "gwt",
        limit=300,
        published_after=date(2026, 7, 2),
        session=session,
    )

    assert [article.title for article in articles] == [
        "第一则近期公文通知",
        "第二则近期公文通知",
        "边界当天公文通知",
    ]
    assert session.pages == ["1", "2", "3"]


def test_design_list_parser_normalizes_english_date():
    html = """
    <ul>
      <li class="news-item">
        <a href="/info/1100/2233.htm"><h3 class="news-item__title">毕业展开放安排</h3></a>
        <time>July 5, 2026</time>
      </li>
    </ul>
    """

    articles = parse_campus_list(html, source=get_campus_source("design"), section="通知公告")

    assert len(articles) == 1
    assert articles[0].published_at == "2026-07-05"


@pytest.mark.parametrize(
    ("source_slug", "section", "html", "expected_title", "expected_date"),
    [
        (
            "ai",
            "通知公告",
            '<div class="filter List_row"><a class="filterList_row" href="../../info/1221/6871.htm"><h5>人工智能学院转专业学生课程修读指引</h5><dl><dd>2026/07/10</dd></dl></a></div>',
            "人工智能学院转专业学生课程修读指引",
            "2026-07-10",
        ),
        (
            "icoc",
            "学院新闻",
            '<div class="havepicturelist1"><ul><li><a href="../info/1008/2005.htm"><div><h4>学院新闻</h4><h3>校园开放日活动顺利举行</h3><p>2026-07-16</p></div></a></li></ul></div>',
            "校园开放日活动顺利举行",
            "2026-07-16",
        ),
        (
            "sfl",
            "学院新闻",
            '<ul class="picture_fly"><li><a href="info/1002/6588.htm"><span>2026/07/16</span><p title="外语演讲比赛取得佳绩">外语演讲比赛取得佳绩</p><div>Read More</div></a></li></ul>',
            "外语演讲比赛取得佳绩",
            "2026-07-16",
        ),
        (
            "utl",
            "通知公告",
            '<div class="new_item"><a href="../info/1016/3721.htm"><div class="day"><span>26</span></div><div class="year-month"><div class="month">06月</div><div class="year">2026</div></div><h3>辅修专业拟录取名单公示</h3></a></div>',
            "辅修专业拟录取名单公示",
            "2026-06-26",
        ),
        (
            "cop",
            "教学通知",
            '<div class="no-pic-article-item" onclick="window.location.href = \'../../info/1013/2431.htm\'"><div><h3 class="article-item-title">药学院全英选修课正式开课</h3><p>正文中包含2023年10月6日等干扰日期</p></div><div class="article-item-date">2026年07月14日</div></div>',
            "药学院全英选修课正式开课",
            "2026-07-14",
        ),
        (
            "nmne",
            "学院动态",
            '<ul><li id="line_u9_1"><a href="../info/1073/4372.htm">新能源材料团队取得新进展</a><span>2026/07/13</span></li></ul>',
            "新能源材料团队取得新进展",
            "2026-07-13",
        ),
        (
            "sgim",
            "学院新闻",
            '<div class="content-list"><div class="item"><a href="info/1023/3210.htm"><div class="title">学院赴企业开展校企交流</div><p>项目始于2022年5月1日</p><div class="date">2026-07-12</div></a></div></div>',
            "学院赴企业开展校企交流",
            "2026-07-12",
        ),
        (
            "hsee",
            "学院动态",
            '<div class="n_tulist"><ul><li><a href="info/1002/3001.htm"><h4>绿色校园主题活动举行</h4><p>回顾2021年6月2日活动</p><h6>2026-07-11</h6></a></li></ul></div>',
            "绿色校园主题活动举行",
            "2026-07-11",
        ),
        (
            "cep",
            "通知公告",
            '<div class="main_list"><ul><li><a href="../info/1103/3528.htm"><h3>工程物理学院招生咨询安排</h3><p>可参考2024年7月1日材料</p><span class="date">2026/07/10</span></a></li></ul></div>',
            "工程物理学院招生咨询安排",
            "2026-07-10",
        ),
        (
            "business",
            "通知公告",
            '<div class="list-box"><div class="list"><ul><li><a href="../../info/1032/4001.htm">商学院暑期值班安排</a><span>2026-07-09</span></li></ul></div></div>',
            "商学院暑期值班安排",
            "2026-07-09",
        ),
        (
            "future-tech",
            "教务通知",
            '<ul class="hireBox"><li><a href="../../info/1052/5001.htm"><h3>未来技术学院课程调整通知</h3><p>原计划为2023年7月1日</p></a><time>2026-07-08</time></li></ul>',
            "未来技术学院课程调整通知",
            "2026-07-08",
        ),
        (
            "music",
            "学生事务",
            '<ul class="picture_fly"><li><a href="https://mp.weixin.qq.com/s/example"><h3>音乐学院迎新演出招募</h3><p>回顾2022年7月1日</p><div class="info"><span>2026-07-07</span></div></a></li></ul>',
            "音乐学院迎新演出招募",
            "2026-07-07",
        ),
    ],
)
def test_college_list_parsers_keep_source_specific_dom(
    source_slug,
    section,
    html,
    expected_title,
    expected_date,
):
    articles = parse_campus_list(html, source=get_campus_source(source_slug), section=section)

    assert len(articles) == 1
    assert articles[0].title == expected_title
    assert articles[0].published_at == expected_date


def test_college_discovery_follows_next_pages_and_merges_sections_by_date():
    pages = {
        "https://ai.sztu.edu.cn/xwzx/yxxw1.htm": """
          <div class="havePictureList_list">
            <a href="../../info/1048/1.htm"><h4>学院新闻甲</h4><span>2026-07-10</span></a>
          </div><a href="yxxw1/1.htm">下页</a>
        """,
        "https://ai.sztu.edu.cn/xwzx/yxxw1/1.htm": """
          <div class="havePictureList_list">
            <a href="../../../info/1048/2.htm"><h4>学院新闻乙</h4><span>2026-07-01</span></a>
          </div>
        """,
        "https://ai.sztu.edu.cn/xwzx/tzgg1/qb.htm": """
          <a class="filterList_row" href="../../../info/1221/3.htm"><h5>最新教学通知</h5><dd>2026-07-15</dd></a>
          <a class="filterList_row" href="../../../info/1221/4.htm"><h5>次新教学通知</h5><dd>2026-07-05</dd></a>
        """,
    }

    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.text = pages[url]

        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.requested = []

        def get(self, url, **kwargs):
            self.requested.append(url)
            return Response(url)

    session = Session()
    articles = discover_campus_articles("ai", limit=3, session=session)

    assert [(item.published_at, item.title) for item in articles] == [
        ("2026-07-15", "最新教学通知"),
        ("2026-07-10", "学院新闻甲"),
        ("2026-07-05", "次新教学通知"),
    ]
    assert "https://ai.sztu.edu.cn/xwzx/yxxw1/1.htm" in session.requested


def test_college_discovery_keeps_healthy_sections_when_one_section_fails():
    notice_html = '<a class="filterList_row" href="../../../info/1221/3.htm"><h5>仍可同步的教学通知</h5><dd>2026-07-15</dd></a>'

    class Session:
        def get(self, url, **kwargs):
            response = requests.Response()
            response.url = url
            response.encoding = "utf-8"
            if "yxxw1" in url:
                response.status_code = 404
                response._content = b"not found"
            else:
                response.status_code = 200
                response._content = notice_html.encode("utf-8")
            return response

    articles = discover_campus_articles("ai", limit=20, session=Session())

    assert [item.title for item in articles] == ["仍可同步的教学通知"]


def test_fetch_campus_article_extracts_safe_absolute_content():
    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        url = "https://ai.sztu.edu.cn/info/1001/9999.htm"
        text = """
        <html><head><title>测试通知</title></head><body>
          <nav>
            <a href="/images/lab/SYS.pdf">实验室介绍</a>
            <a href="/downloads/college-guide.pdf">学院宣传册.pdf</a>
          </nav>
          <form name="_newscontent_fromname">
            <div class="v_news_content">
              <p>这是用于测试的校园通知正文，包含足够长度的信息。</p>
              <img src="../../images/a.jpg">
              <script>alert(1)</script>
            </div>
            <div class="article-attachments">
              <a href="/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1">报名表.docx</a>
            </div>
          </form>
        </body></html>
        """

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    article = fetch_campus_article(Response.url, session=Session())

    assert article["title"] == "测试通知"
    assert "校园通知正文" in article["body_text"]
    assert article["images"] == ["https://ai.sztu.edu.cn/images/a.jpg"]
    assert "<script" not in article["body_html"]
    assert article["attachments"] == [
        {
            "name": "报名表.docx",
            "url": "https://ai.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1",
            "download_type": "external",
        }
    ]


def test_college_article_keeps_external_cdn_attachment_but_gwt_does_not():
    html = """
      <html><head><title>校外附件测试</title></head><body>
        <div class="v_news_content">
          <p>学院通知正文包含托管在外部文件服务上的附件。</p>
          <a href="https://files.example.edu/forms/signup.xlsx">报名信息表.xlsx</a>
        </div>
      </body></html>
    """

    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.text = html

        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            return Response(url)

    college = fetch_campus_article(
        "https://ai.sztu.edu.cn/info/1001/9999.htm",
        session=Session(),
    )
    gwt = fetch_campus_article(
        "https://nbw.sztu.edu.cn/info/1029/9999.htm",
        session=Session(),
    )

    assert [item["name"] for item in college["attachments"]] == ["报名信息表.xlsx"]
    assert gwt["attachments"] == []


def test_fetch_campus_article_keeps_image_and_attachment_only_notice():
    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        url = "https://cep.sztu.edu.cn/info/1103/3528.htm"
        text = """
        <html><head><title>工程物理学院录取分数情况-深圳技术大学工程物理学院</title></head><body>
          <form name="_newscontent_fromname">
            <div class="v_news_content"><img src="/images/score.png"></div>
            <a href="/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=8">录取分数情况.xlsx</a>
          </form>
        </body></html>
        """

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    article = fetch_campus_article(Response.url, session=Session())

    assert article["title"] == "工程物理学院录取分数情况"
    assert article["body_text"] == ""
    assert article["images"] == ["https://cep.sztu.edu.cn/images/score.png"]
    assert [item["name"] for item in article["attachments"]] == ["录取分数情况.xlsx"]


def test_fetch_campus_article_reuses_authenticated_session_for_iframe_content():
    page_url = "https://ai.sztu.edu.cn/info/1001/9999.htm"
    frame_url = "https://ai.sztu.edu.cn/system/resource/content/frame.htm"
    pages = {
        page_url: """
          <html><head><title>内嵌附件通知</title></head><body>
            <div class="v_news_content">
              <p>主页面正文包含内嵌的学校内容页面。</p>
              <iframe src="/system/resource/content/frame.htm"></iframe>
            </div>
          </body></html>
        """,
        frame_url: """
          <html><body><div class="v_news_content">
            <p>这是登录会话内才能看到的内嵌正文。</p>
            <a href="/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=9">内嵌报名表.docx</a>
          </div></body></html>
        """,
    }

    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.text = pages[url]

        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.requested = []

        def get(self, url, **kwargs):
            self.requested.append(url)
            return Response(url)

    session = Session()
    article = fetch_campus_article(page_url, session=session)

    assert session.requested == [page_url, frame_url]
    assert "内嵌正文" in article["body_text"]
    assert [item["name"] for item in article["attachments"]] == ["内嵌报名表.docx"]


def test_campus_request_retries_transient_failure_then_succeeds(monkeypatch):
    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            response = requests.Response()
            response.url = url
            response.status_code = 503 if self.calls < 3 else 200
            response.encoding = "utf-8"
            response._content = b"ok"
            return response

    monkeypatch.setattr(campus_source_service.time, "sleep", lambda *_: None)
    session = Session()

    response = campus_source_service._safe_get(session, "https://ai.sztu.edu.cn/xwzx/yxxw1.htm")

    assert response.status_code == 200
    assert session.calls == 3


def test_short_college_pointer_page_resolves_to_wechat_article():
    class Response:
        status_code = 200
        headers = {}
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        url = "https://ai.sztu.edu.cn/info/1001/redirect.htm"
        text = """
        <html><body><p>点击查看原文</p>
        <a href="https://mp.weixin.qq.com/s/example-article">阅读原文</a></body></html>
        """

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

        def close(self):
            return None

    article = fetch_campus_article(Response.url, session=Session())

    assert article["platform"] == "wechat_redirect"
    assert article["redirect_url"] == "https://mp.weixin.qq.com/s/example-article"


def test_campus_reader_hands_resolved_pointer_to_wechat_ocr_pipeline(monkeypatch):
    target = "https://mp.weixin.qq.com/s/example-article"
    monkeypatch.setattr(
        article_fetcher,
        "fetch_campus_article",
        lambda url: {"platform": "wechat_redirect", "url": url, "redirect_url": target},
    )
    expected = ArticleFetchResult(
        url=target,
        platform="wechat",
        title="学院公众号文章",
        body_text="[图片文字 1] 海报中的活动时间 [/图片文字 1]",
    )
    monkeypatch.setattr(article_fetcher, "fetch_wechat_article", lambda url: expected)

    result = article_fetcher.fetch_article("https://ai.sztu.edu.cn/info/1001/redirect.htm", "campus")

    assert result == expected


def test_sync_campus_source_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    article = CampusArticle(
        title="测试学院通知",
        url="https://ai.sztu.edu.cn/info/1001/9999.htm",
        published_at="2026-07-15",
        section="通知公告",
        source_slug="ai",
        source_name="人工智能学院",
    )
    monkeypatch.setattr(campus_router, "discover_campus_articles", lambda *args, **kwargs: [article])

    first = campus_router.sync_campus_source("ai", campus_router.CampusSyncRequest(limit=10))
    second = campus_router.sync_campus_source("ai", campus_router.CampusSyncRequest(limit=10))

    assert first.created == 1
    assert second.created == 0
    assert second.duplicates == 1
    with connect() as connection:
        row = connection.execute(
            """SELECT published_at, source_name, source_section
               FROM content_items WHERE source_provider = 'campus'"""
        ).fetchone()
        folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = (SELECT library_folder_id FROM content_items LIMIT 1)"
        ).fetchone()
        source_folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = ?",
            (folder["parent_folder_id"],),
        ).fetchone()
        root_folder = connection.execute(
            "SELECT name FROM library_folders WHERE id = ?",
            (source_folder["parent_folder_id"],),
        ).fetchone()
    assert row["published_at"] == "2026-07-15"
    assert row["source_name"] == "人工智能学院"
    assert row["source_section"] == "通知公告"
    assert folder["name"] == "通知公告"
    assert source_folder["name"] == "人工智能学院"
    assert root_folder["name"] == "校园官网"


def test_gwt_latest_sync_checks_only_ten_newest_articles(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    captured = {}

    def fake_discover(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(campus_router, "discover_campus_articles", fake_discover)

    result = campus_router.sync_campus_source("gwt", campus_router.CampusSyncRequest())

    assert result.discovered == 0
    assert captured["limit"] == 10
    assert captured["known_urls"] == set()
    assert captured.get("published_after") is None


def test_campus_history_sync_accepts_a_date_range(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    captured = {}

    def fake_discover(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(campus_router, "discover_campus_articles", fake_discover)

    result = campus_router.sync_campus_source(
        "ai",
        campus_router.CampusSyncRequest(
            mode="date_range",
            max_items=80,
            published_after=date(2026, 7, 1),
            published_before=date(2026, 7, 15),
        ),
    )

    assert result.discovered == 0
    assert captured["limit"] == 80
    assert captured["published_after"] == date(2026, 7, 1)
    assert captured["published_before"] == date(2026, 7, 15)


def test_campus_history_sync_checks_gwt_pages_for_count_and_all_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    captured = {}

    def fake_discover(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(campus_router, "discover_campus_articles", fake_discover)

    campus_router.sync_campus_source("gwt", campus_router.CampusSyncRequest(mode="count", max_items=80))
    assert captured["limit"] == 80
    assert captured["published_after"] == date.min

    campus_router.sync_campus_source("gwt", campus_router.CampusSyncRequest(mode="all"))
    assert captured["limit"] == 300
    assert captured["published_after"] == date.min


def test_import_gwt_snapshot_caches_authenticated_article_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://nbw.sztu.edu.cn/info/1029/4321.htm"
    request = campus_router.CampusSnapshotImportRequest(
        articles=[
            campus_router.CampusSnapshotArticle(
                title="关于暑期校园服务安排的通知",
                canonical_url=source_url,
                body_text="这是通过学校 WebVPN 获取的公文通正文，内容足够长并且不包含任何认证凭据。",
                body_html="<div class='v_news_content'><p>这是通过学校 WebVPN 获取的公文通正文。</p><script>bad()</script></div>",
                author="党政办公室",
                published_at="2026-07-15",
                attachments=[
                    {
                        "name": "暑期安排.pdf",
                        "url": "https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1",
                        "download_type": "direct",
                    }
                ],
            )
        ]
    )

    first = campus_router.import_gwt_snapshot(request)
    second = campus_router.import_gwt_snapshot(request)

    assert first.created == 1
    assert second.created == 0
    metadata = read_cache_meta(cache_dir_for_url(source_url))
    assert metadata["article_info"]["capture_transport"] == "sztu_webvpn"
    assert metadata["article_info"]["author"] == "党政办公室"
    assert metadata["article_info"]["attachments"][0]["name"] == "暑期安排.pdf"
    assert "cookie" not in str(metadata).lower()


def test_import_gwt_snapshot_rejects_non_gwt_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    request = campus_router.CampusSnapshotImportRequest(
        articles=[
            campus_router.CampusSnapshotArticle(
                title="伪造的校园通知",
                canonical_url="https://example.com/info/1029/4321.htm",
                body_text="这是一段长度足够的伪造正文，不能被导入校园内容库。",
                body_html="<div><p>这是一段长度足够的伪造正文。</p></div>",
            )
        ]
    )

    try:
        campus_router.import_gwt_snapshot(request)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("非公文通地址不应被接受")


def test_sync_campus_source_routes_wechat_links_to_wechat_reader(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    article = CampusArticle(
        title="学院公众号通知",
        url="https://mp.weixin.qq.com/s/example",
        section="学院新闻",
        source_slug="music",
        source_name="音乐学院",
    )
    monkeypatch.setattr(campus_router, "discover_campus_articles", lambda *args, **kwargs: [article])

    result = campus_router.sync_campus_source("music", campus_router.CampusSyncRequest(limit=10))

    assert result.created == 1
    with connect() as connection:
        row = connection.execute(
            "SELECT source_provider, library_folder_id FROM content_items WHERE canonical_source_id = ?",
            (article.url,),
        ).fetchone()
        folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = ?",
            (row["library_folder_id"],),
        ).fetchone()
        source_folder = connection.execute(
            "SELECT name FROM library_folders WHERE id = ?",
            (folder["parent_folder_id"],),
        ).fetchone()
    assert row["source_provider"] == "wechat"
    assert folder["name"] == "学院新闻"
    assert source_folder["name"] == "音乐学院"


def test_gwt_articles_are_grouped_by_publishing_department(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    article = CampusArticle(
        title="关于选课安排的通知",
        url="https://nbw.sztu.edu.cn/info/1029/1234.htm",
        section="公文通",
        source_slug="gwt",
        source_name="公文通",
        department="教务处",
    )

    records, created = persist_campus_articles("公文通", [article])

    assert created == 1
    with connect() as connection:
        folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = ?",
            (connection.execute(
                "SELECT library_folder_id FROM content_items WHERE id = ?",
                (records[0].content_item_id,),
            ).fetchone()[0],),
        ).fetchone()
        source_folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = ?",
            (folder["parent_folder_id"],),
        ).fetchone()
        root_folder = connection.execute(
            "SELECT name FROM library_folders WHERE id = ?",
            (source_folder["parent_folder_id"],),
        ).fetchone()

    assert folder["name"] == "教务处"
    assert source_folder["name"] == "公文通"
    assert root_folder["name"] == "校园官网"


def test_campus_folder_backfill_moves_existing_articles_into_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        old_folder_id = ensure_campus_source_folder(connection, "人工智能学院")
        item = ContentRepository(connection).create_content_item(
            source_provider="campus",
            content_type="article",
            source_url="https://ai.sztu.edu.cn/info/1001/8888.htm",
            canonical_source_id="https://ai.sztu.edu.cn/info/1001/8888.htm",
            title="已有的学院通知",
            library_folder_id=old_folder_id,
            source_name="人工智能学院",
            source_section="通知公告",
        )
        connection.commit()

    assert backfill_campus_source_folders() == 1
    with connect() as connection:
        folder = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE id = (SELECT library_folder_id FROM content_items WHERE id = ?)",
            (item.id,),
        ).fetchone()
        source_folder = connection.execute(
            "SELECT name FROM library_folders WHERE id = ?",
            (folder["parent_folder_id"],),
        ).fetchone()

    assert folder["name"] == "通知公告"
    assert source_folder["name"] == "人工智能学院"


def test_procurement_source_folder_is_visible_before_first_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    assert backfill_campus_source_folders() == 0
    with connect() as connection:
        folder = connection.execute(
            """SELECT source.name, root.name AS root_name
               FROM library_folders AS source
               JOIN library_folders AS root ON root.id = source.parent_folder_id
               WHERE source.name = ?""",
            ("采购与招投标管理中心",),
        ).fetchone()

    assert folder["name"] == "采购与招投标管理中心"
    assert folder["root_name"] == "校园官网"


def test_campus_source_settings_are_independent_and_persistent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    ai = update_campus_source_setting("ai", enabled=True, interval_minutes=180, auto_analyze=True)
    record_campus_source_sync("ai", status="success", discovered=8, created=3)
    sources = {source["slug"]: source for source in load_campus_source_settings()}

    assert ai["enabled"] is True
    assert sources["ai"]["interval_minutes"] == 180
    assert sources["ai"]["auto_analyze"] is True
    assert sources["ai"]["last_discovered"] == 8
    assert sources["ai"]["last_created"] == 3
    assert sources["gwt"]["enabled"] is False
    assert sources["gwt"]["auto_analyze"] is False
    assert sources["gwt"]["interval_minutes"] == 360


def test_campus_source_groups_are_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    initialize_database()
    group = create_group("教务通知")
    update_campus_source_setting("ai", group_ids=[group["id"]])

    sources = {source["slug"]: source for source in load_campus_source_settings()}
    assert sources["ai"]["group_ids"] == [group["id"]]


def test_digest_startup_enables_only_sources_without_an_explicit_choice(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    update_campus_source_setting("gwt", enabled=False)
    update_campus_source_setting("ai", enabled=True)

    changed = enable_unconfigured_sources_for_digest()
    sources = {source["slug"]: source for source in load_campus_source_settings()}

    assert changed == len(sources) - 2
    assert sources["gwt"]["enabled"] is False
    assert sources["ai"]["enabled"] is True
    assert sources["music"]["enabled"] is True


def test_prompt_seed_retires_obsolete_per_source_campus_prompts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        prompts = connection.execute(
            "SELECT name, variables_schema, is_active FROM prompt_templates WHERE task_type = 'campus_source'"
        ).fetchall()

    assert prompts == []
