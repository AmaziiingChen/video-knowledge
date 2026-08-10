from services import campus_list_parsing, campus_sources
from services.campus_source_catalog import CampusSource


def test_campus_sources_re_exports_the_dedicated_list_parser():
    assert campus_sources.parse_campus_list is campus_list_parsing.parse_campus_list


def test_list_parser_rejects_external_hosts_and_normalizes_source_metadata():
    source = CampusSource(
        slug="test-campus",
        name="测试学院",
        base_url="https://ai.sztu.edu.cn/",
        sections={"通知公告": "https://ai.sztu.edu.cn/notices.htm"},
        list_selectors=("li",),
        include_wechat_links=False,
    )
    articles = campus_list_parsing.parse_campus_list(
        """
        <ul>
          <li><a href="/info/1001/1.htm" title="1. 2026-08-10 校园开放日安排">校园开放日安排</a></li>
          <li><a href="https://example.test/info/2.htm">不可信站外页面</a></li>
          <li><a href="https://mp.weixin.qq.com/s/example">未授权公众号页面</a></li>
        </ul>
        """,
        source=source,
        section="通知公告",
    )

    assert len(articles) == 1
    assert articles[0].title == "校园开放日安排"
    assert articles[0].url == "https://ai.sztu.edu.cn/info/1001/1.htm"
    assert articles[0].source_slug == "test-campus"
