from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.wechat_report_layout import ReportSource, render_wechat_report


def test_report_layout_replaces_footnotes_with_clickable_sources():
    html = render_wechat_report(
        title="电力市场日报",
        markdown="""---
title: internal
---

# 电力市场日报

## AI 摘要

这是一段工作台摘要。

## 本期概览

跨区交易取得进展[^S002]，市场规则继续细化[^S01]。

## 交易动态

正文内容。

[^S002]: 内部脚注，不应出现在发布稿
[^S01]: 内部脚注，不应出现在发布稿
""",
        digest="报告摘要",
        report_type="daily",
        sources=[
            ReportSource("S002", "跨区交易报道", "https://mp.weixin.qq.com/s/example-2", "行业公众号", "2026-07-20"),
            ReportSource("S01", "市场规则报道", "https://example.com/source-1", "行业网站", "2026-07-20"),
        ],
    )

    soup = BeautifulSoup(html, "html.parser")
    assert "[^S002]" not in soup.get_text()
    assert "内部脚注" not in soup.get_text()
    assert "AI 摘要" not in soup.get_text()
    assert "参考来源" in soup.get_text()
    assert "参考 2 篇资料" in soup.get_text()
    assert "全文共" in soup.get_text()
    assert "预计 1 分钟阅读" in soup.get_text()
    assert "内容由 AI 辅助整理，请以原始来源为准" in soup.get_text()
    assert "点击文末“阅读原文”，查看网页阅读版与完整资料链接" in soup.get_text()
    markers = [marker.get_text(strip=True) for marker in soup.find_all("sup")]
    assert markers == ["1", "2"]
    # The source list follows first appearance in the text (S002, then S01),
    # instead of the upstream storage identifiers.
    source_rows = [row.get_text(" ", strip=True) for row in soup.select("section > p") if "报道" in row.get_text()]
    assert source_rows == ["1. 跨区交易报道 · 行业公众号 · 2026-07-20", "2. 市场规则报道 · 行业网站 · 2026-07-20"]
    assert soup.find("a", href="https://mp.weixin.qq.com/s/example-2")
    assert soup.find("a", href="https://example.com/source-1")
    assert all(text.parent and text.parent.name == "span" for text in soup.find_all(string=True) if text.strip())
    assert not soup.find(attrs={"class": True})


def test_report_layout_keeps_unknown_citation_as_readable_marker():
    html = render_wechat_report(
        title="日报",
        markdown="## 动态\n\n这条信息尚未匹配来源[^S999]。",
        digest="",
        report_type="daily",
        sources=[],
    )

    soup = BeautifulSoup(html, "html.parser")
    assert "[^S999]" not in soup.get_text()
    assert "1" in soup.get_text()


def test_report_layout_hides_internal_stats_and_flattens_lists_for_wechat():
    html = render_wechat_report(
        title="校园生活",
        markdown="""> 分组：校园生活 · 分析文章：2 篇 · 正文引用：2 篇

## 本期概览

本期有两项安排。[^S001]

## 具体安排

* **陕西**：录取安排已发布。[^S001]
* **广东**：服务时间已公布。[^S002]
  * 图书馆照常开放。
""",
        digest="内部统计不应出现",
        report_type="range",
        sources=[
            ReportSource("S001", "陕西安排", "https://mp.weixin.qq.com/s/1"),
            ReportSource("S002", "广东安排", "https://mp.weixin.qq.com/s/2"),
        ],
    )

    soup = BeautifulSoup(html, "html.parser")
    assert "分组：" not in soup.get_text()
    assert "分析文章" not in soup.get_text()
    assert "内部统计不应出现" not in soup.get_text()
    assert not soup.find("ul")
    assert not soup.find("ol")
    assert "陕西：录取安排已发布。" in soup.get_text()
    assert "图书馆照常开放。" in soup.get_text()
    assert not soup.find("p", style=lambda value: value and "text-indent" in value)
    assert soup.find("span", style=lambda value: value and "width:9px;height:9px" in value)
    assert soup.find("section", style=lambda value: value and "min-width:0" in value and "overflow-wrap:anywhere" in value)


def test_report_layout_numbers_topics_but_not_the_overview():
    html = render_wechat_report(
        title="校园日报",
        markdown="""## 本期概览

概览内容。

## 招生动态

主题一。

## 校园服务

主题二。""",
        digest="",
        report_type="daily",
        sources=[],
    )

    soup = BeautifulSoup(html, "html.parser")
    section_numbers = [
        tag.get_text(strip=True)
        for tag in soup.find_all("p")
        if "font-size:24px" in tag.get("style", "")
    ]
    assert section_numbers == ["01", "02"]
    assert "OVERVIEW 本期概览" in soup.get_text(" ", strip=True)


def test_report_layout_directory_is_compact_and_placed_after_overview():
    html = render_wechat_report(
        title="校园日报",
        markdown="""## 本期概览

这是今日概览。

## 招生动态

内容一。

## 校园服务

内容二。

## 学生活动

内容三。

## 假期安排

内容四。""",
        digest="",
        report_type="daily",
        sources=[],
    )

    soup = BeautifulSoup(html, "html.parser")
    directory = next(
        section
        for section in soup.find_all("section")
        if "margin:22px 0 26px" in section.get("style", "")
    )
    directory_text = directory.get_text(" ", strip=True)
    assert "共 4 个主题" in directory_text
    assert "01 招生动态" in directory_text
    assert "02 校园服务" in directory_text
    assert "03 学生活动" in directory_text
    assert "04 假期安排" in directory_text
    assert html.index("这是今日概览") < html.index("本期目录") < html.index("招生动态")


def test_report_layout_uses_only_referenced_sources_in_reading_order():
    html = render_wechat_report(
        title="校园日报",
        markdown="""## 本期概览

先引用第二篇[^S002]，再引用第一篇[^S001]，重复时仍是第二篇[^S002]。""",
        digest="",
        report_type="daily",
        sources=[
            ReportSource("S001", "第一篇", "https://example.com/1"),
            ReportSource("S002", "第二篇", "https://example.com/2"),
            ReportSource("S003", "未引用文章", "https://example.com/3"),
        ],
    )

    soup = BeautifulSoup(html, "html.parser")
    assert "参考 2 篇资料" in soup.get_text()
    assert [marker.get_text(strip=True) for marker in soup.find_all("sup")] == ["1", "2", "1"]
    source_section = next(
        section
        for section in soup.find_all("section")
        if "margin-top:32px" in section.get("style", "")
    )
    source_rows = [row.get_text(" ", strip=True) for row in source_section.find_all("p", recursive=False)]
    assert source_rows == ["1. 第二篇", "2. 第一篇"]
    assert "未引用文章" not in soup.get_text()


def test_report_layout_keeps_every_table_citation_link_without_underlines():
    html = render_wechat_report(
        title="课程汇总",
        markdown="""## 课程安排

| 课程名称 | 推荐对象 |
| --- | --- |
| 高等分子生物学 | 全学院本科生[^S056][^S057][^S058] |

正文中的校园动态同样引用来源[^S072]。""",
        digest="",
        report_type="range",
        sources=[
            ReportSource("S056", "药学院通知", "https://cop.sztu.edu.cn/info/1004/2433.htm"),
            ReportSource("S057", "招聘通知", "https://mp.weixin.qq.com/s/recruitment"),
            ReportSource("S058", "信息化通知", "https://mp.weixin.qq.com/s/digital-campus"),
            ReportSource("S072", "学院新闻", "https://hsee.sztu.edu.cn/info/1112/4131.htm"),
        ],
    )

    soup = BeautifulSoup(html, "html.parser")
    table_markers = soup.find_all("td")[1].find_all("sup")
    assert [marker.get_text(strip=True) for marker in table_markers] == ["1，2，3"]
    assert [link["href"] for link in table_markers[0].find_all("a")] == [
        "https://cop.sztu.edu.cn/info/1004/2433.htm",
        "https://mp.weixin.qq.com/s/recruitment",
        "https://mp.weixin.qq.com/s/digital-campus",
    ]
    assert "color:#9ea096" in table_markers[0].get("style", "")
    assert all("color:#9ea096" in link.get("style", "") for link in table_markers[0].find_all("a"))
    assert all("font-weight:500" in link.get("style", "") for link in table_markers[0].find_all("a"))
    assert all("text-decoration:none" in link.get("style", "") for link in soup.find_all("a"))
    assert all("border-bottom" not in link.get("style", "") for link in soup.find_all("a"))


def test_report_layout_sorts_and_deduplicates_each_citation_run_by_display_number():
    first_run = "".join(f"[^S{number:03d}]" for number in range(1, 12))
    html = render_wechat_report(
        title="校园日报",
        markdown=(
            f"## 本期概览\n\n首次引用依次建立展示编号{first_run}。\n\n"
            "## 校园动态\n\n同一事实的来源顺序由模型打乱"
            "[^S011][^S010][^S007][^S003][^S007]。"
        ),
        digest="",
        report_type="daily",
        sources=[
            ReportSource(f"S{number:03d}", f"来源 {number}", f"https://example.com/{number}")
            for number in range(1, 12)
        ],
    )

    soup = BeautifulSoup(html, "html.parser")
    markers = soup.find_all("sup")
    assert [marker.get_text(strip=True) for marker in markers] == [
        "1，2，3，4，5，6，7，8，9，10，11",
        "3，7，10，11",
    ]
    assert [link["href"] for link in markers[1].find_all("a")] == [
        "https://example.com/3",
        "https://example.com/7",
        "https://example.com/10",
        "https://example.com/11",
    ]


def test_report_layout_uses_report_specific_labels_and_mobile_safe_alignment():
    html = render_wechat_report(
        title="每周回顾",
        markdown="## 本期概览\n\n一周重点。\n\n## 行业动态\n\n这里是正文。",
        digest="",
        report_type="weekly",
        sources=[],
    )

    soup = BeautifulSoup(html, "html.parser")
    assert "每周回顾" in soup.get_text()
    assert "WEEKLY REVIEW" in soup.get_text()
    assert "CAMPUS UPDATE" not in soup.get_text()
    assert "text-align:justify" not in html
