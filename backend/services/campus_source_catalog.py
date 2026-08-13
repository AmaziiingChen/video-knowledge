"""Campus-source models, registry, and URL ownership boundaries."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

PROCUREMENT_SOURCE_SLUG = "sztu-procurement"


@dataclass(frozen=True)
class CampusSource:
    slug: str
    name: str
    base_url: str
    sections: dict[str, str]
    list_selectors: tuple[str, ...] = field(default_factory=tuple)
    include_wechat_links: bool = True


@dataclass(frozen=True)
class CampusArticle:
    title: str
    url: str
    published_at: str = ""
    section: str = ""
    source_slug: str = ""
    source_name: str = ""
    department: str = ""


def _source(
    slug: str,
    name: str,
    base_url: str,
    sections: dict[str, str],
    *selectors: str,
    include_wechat_links: bool = True,
) -> CampusSource:
    return CampusSource(
        slug=slug,
        name=name,
        base_url=base_url,
        sections={label: urljoin(base_url.rstrip("/") + "/", path) for label, path in sections.items()},
        list_selectors=tuple(selectors),
        include_wechat_links=include_wechat_links,
    )


# College URLs and template selectors are adapted from MicroFlow's built-in
# SZTU spiders. Keeping every campus source in the same data registry makes
# source maintenance independent from ingestion and article reading.
CAMPUS_SOURCES: tuple[CampusSource, ...] = (
    _source(
        "gwt", "公文通", "https://nbw.sztu.edu.cn/",
        {"公文通": "list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029"},
        "ul.news-ul li.clearfix",
    ),
    _source(
        "sztu", "深圳技术大学", "https://www.sztu.edu.cn/",
        {"校园新闻": "jdjd/xyxw.htm"},
        "div.yy-lt > ul > li",
        include_wechat_links=False,
    ),
    _source(
        "ai", "人工智能学院", "https://ai.sztu.edu.cn/",
        {"院系新闻": "xwzx/yxxw1.htm", "通知公告": "xwzx/tzgg1/qb.htm"},
        ".havePictureList_list a", ".news_list a", "ul.list-gl a", ".filterList_row[href]",
    ),
    _source(
        "nmne", "新材料与新能源学院", "https://nmne.sztu.edu.cn/",
        {
            "学院动态": "xwzx/xydt.htm", "通知公告": "xwzx/tzgg.htm",
            "讲座通知": "xwzx/jzt.htm", "学术动态": "xwzx/xsd.htm",
            "合作交流": "xwzx/hzj.htm", "实验平台": "xwzx/sypt.htm",
        },
        "li[id^='line_u9_']", "ul.list-gl li",
    ),
    _source(
        "sgim", "中德智能制造学院", "https://sgim.sztu.edu.cn/",
        {
            "学院新闻": "xyxw.htm",
            "通知公告": "list2022.jsp?urltype=tree.TreeTempUrl&wbtreeid=1045",
        },
        ".content-list .item", "ul.list-gl li", "ul.news-list li",
    ),
    _source(
        "utl", "城市交通与物流学院", "https://utl.sztu.edu.cn/",
        {"学院动态": "xwzx/xydt.htm", "通知公告": "xwzx/tzgg.htm"},
        "div.new_center_item", "div.new_item",
    ),
    _source(
        "hsee", "健康与环境工程学院", "https://hsee.sztu.edu.cn/",
        {"学院动态": "xydt.htm", "通知公告": "tzgg.htm"},
        ".n_tulist ul li", ".n_list ul li.cleafix", "li.cleafix",
    ),
    _source(
        "cep", "工程物理学院", "https://cep.sztu.edu.cn/",
        {"新闻动态": "tzgg1/xwdt.htm", "通知公告": "tzgg1/tzg.htm"},
        ".main_list li",
    ),
    _source(
        "cop", "药学院", "https://cop.sztu.edu.cn/",
        {
            "学院新闻": "index/yyyw.htm", "党群通知": "index/tzgg/dq.htm",
            "教学通知": "index/tzgg/jx.htm", "学工通知": "index/tzgg/xg.htm",
            "科研通知": "index/tzgg/ky.htm", "行政通知": "index/tzgg/xz.htm",
            "竞赛通知": "index/tzgg/js.htm", "招生就业": "index/tzgg/zsjy.htm",
        },
        ".article-card[onclick]", ".no-pic-article-item[onclick]",
    ),
    _source(
        "design", "创意设计学院", "https://design.sztu.edu.cn/",
        {
            "学院焦点": "xydt/xyjd.htm", "院系新闻": "xydt/yxxw.htm",
            "通知公告": "xydt/tzgg.htm", "党团工作": "xydt/dtgz.htm",
            "社会服务": "xydt/shfw.htm", "校园生活": "xydt/xysh.htm",
        },
        "li.news-item", "a.notice-item",
    ),
    _source(
        "business", "商学院", "https://bs.sztu.edu.cn/",
        {
            "新闻动态": "index/xwdt.htm", "通知公告": "index/tzgg.htm",
            "学术动态": "index/xsdt.htm", "校园生活": "index/xysh.htm",
        },
        "ul.list-gl > li", "ul.news-list > li", ".list-box .list ul > li",
    ),
    _source(
        "icoc", "集成电路与光电芯片学院", "https://icoc.sztu.edu.cn/",
        {"通知公告": "xwzx/tzgg.htm", "学术成果": "kxyj/xscg.htm", "学院新闻": "xwzx/xyxw.htm"},
        "ul.list-gl > li", "ul.news-list > li", "ul.list_pic > li", ".nopicturelist_main > ul > li",
        ".havepicturelist1 > ul > li",
    ),
    _source(
        "future-tech", "未来技术学院", "https://futuretechnologyschool.sztu.edu.cn/",
        {
            "新闻中心": "xw_hd/xwzx.htm", "教务通知": "xw_hd/tzgg1/jw.htm",
            "科研通知": "xw_hd/tzgg1/ky.htm", "学工通知": "xw_hd/tzgg1/xg.htm",
            "校园通知": "xw_hd/tzgg1/xy.htm", "行政通知": "xw_hd/tzgg1/xz.htm",
        },
        "ul.hireBox > li", "ul.listBox > li",
    ),
    _source(
        "sfl", "外国语学院", "https://sfl.sztu.edu.cn/",
        {"通知公告": "tzgg.htm", "学院新闻": "xyxw.htm"},
        "ul.news_fly > li", "ul.picture_fly > li",
    ),
    _source(
        "music", "音乐学院", "https://musicyyds.sztu.edu.cn/",
        {"封面新闻": "zxdt/fmxw.htm", "学生事务": "zxdt/xssw.htm", "教研活动": "zxdt/jyhd.htm"},
        "ul.picture_fly li", ".list ul li", ".news_list ul li", ".list-box ul li", "ul.list-gl li",
    ),
    _source(
        PROCUREMENT_SOURCE_SLUG, "采购与招投标管理中心", "https://ztb.sztu.edu.cn/sfw_cms/",
        {
            "采购公告": "e?page=cms.psms.gglist&typeDetail=XQ",
            "成交公告": "e?page=cms.psms.gglist&typeDetail=GG",
            "采购意向": "e?page=cms.psms.gglist&typeDetail=YX",
            "合同公示": "e?page=cms.psms.gglist&typeDetail=HT",
        },
        include_wechat_links=False,
    ),
)

_SOURCE_BY_SLUG = {source.slug: source for source in CAMPUS_SOURCES}
_ALLOWED_HOSTS = {urlparse(source.base_url).hostname or "" for source in CAMPUS_SOURCES}


def get_campus_source(slug: str) -> CampusSource:
    try:
        return _SOURCE_BY_SLUG[slug]
    except KeyError as exc:
        raise LookupError(f"未知校园来源: {slug}") from exc


def is_campus_article_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return is_allowed_campus_host(host)


def campus_source_for_url(url: str) -> CampusSource | None:
    host = (urlparse(url).hostname or "").lower()
    return next((source for source in CAMPUS_SOURCES if urlparse(source.base_url).hostname == host), None)


def is_allowed_campus_host(host: str) -> bool:
    normalized = str(host or "").lower().rstrip(".")
    return normalized in _ALLOWED_HOSTS or (
        normalized.startswith("www.") and normalized[4:] in _ALLOWED_HOSTS
    )


__all__ = [
    "CAMPUS_SOURCES",
    "PROCUREMENT_SOURCE_SLUG",
    "CampusArticle",
    "CampusSource",
    "campus_source_for_url",
    "get_campus_source",
    "is_allowed_campus_host",
    "is_campus_article_url",
]
