from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Event

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services.ai_call_logger import AICallRecord
from services.database import connect, initialize_database
from services.group_report_models import _SupportingSource
from services.group_report_pipeline import (
    GROUP_REPORT_MODEL_CHAIN,
    OVERVIEW_FALLBACK,
    OVERVIEW_TASK,
    SECTION_PLAN_FALLBACK,
    SECTION_WRITER_FALLBACK,
    SOURCE_SUMMARY_FALLBACK,
    GroupReportContext,
    GroupReportSource,
    _chat_json_stream,
    _is_json_payload,
    _load_cached_summaries,
    _normalize_generated_section_markdown,
    _normalize_report_overview,
    _normalize_report_plan_shape,
    _normalize_section_heading_levels,
    _parse_json,
    _parse_report_plan,
    _ProgressUsage,
    _Section,
    _sha256,
    _store_cached_summaries,
    _summarize_one,
    _summarize_sources,
    generate_group_report,
)
from services.group_report_plan_normalization import normalize_report_plan
from services.knowledge_library import write_content_markdown_document
from services.llm_provider import LLMResponse, LLMStreamChunk, LLMUsage
from services.prompt_templates import (
    DEFAULT_GROUP_REPORT_OVERVIEW_PROMPT,
    DEFAULT_GROUP_REPORT_SECTION_PLAN_PROMPT,
    DEFAULT_GROUP_REPORT_SECTION_WRITER_PROMPT,
    DEFAULT_GROUP_REPORT_SOURCE_SUMMARY_PROMPT,
    DEFAULT_PROMPT_TEMPLATES,
    PromptTemplateRepository,
    sync_builtin_prompt_definitions,
)
from services.repository import ContentRepository
from services.wechat_report_generation import (
    REPORT_SYSTEM_PROMPT,
    ReportSource,
    generate_cited_report,
)
from services.wechat_reports import (
    DEFAULT_REPORT_PROMPT_VERSION,
    _campus_report_prompts,
    _default_report_prompt,
    _in_window,
    _persist_generated_report,
    _report_document_name,
    create_group,
)

FACT_JSON = """{
  "summary": "学校发布了一项通知",
  "importance": "high",
  "topics": ["校园通知"],
  "facts": ["通知内容已经公布"],
  "dates": ["2026-07-15"],
  "numbers": [],
  "actions": ["相关人员需要按通知执行"],
  "uncertainties": []
}"""


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, *, temperature=0.2):
        self.calls.append((messages, temperature))
        if not self.responses:
            raise AssertionError("FakeProvider 缺少预设响应")
        return LLMResponse(content=self.responses.pop(0), provider=self.name, model=self.model)


def test_group_report_progress_usage_includes_estimated_cost():
    usage = _ProgressUsage()
    usage.remember(AICallRecord(
        call_type="group_report_source_summary",
        provider="deepseek",
        model="deepseek-v4-flash",
        input_chars=100,
        output_chars=20,
        prompt_tokens=50,
        completion_tokens=10,
        total_tokens=60,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=50,
        estimated_cost=0.01234567,
        elapsed_seconds=0.5,
    ))

    snapshot = usage.snapshot()

    assert snapshot["call_count"] == 1
    assert snapshot["estimated_cost"] == 0.01234567


def source(citation_id: str, material: str, title: str = "测试文章") -> ReportSource:
    return ReportSource(
        citation_id=citation_id,
        content_item_id=f"content-{citation_id}",
        title=title,
        source_url=f"https://mp.weixin.qq.com/s/{citation_id}",
        published_at="2026-07-15T09:00:00+08:00",
        mp_name="测试公众号",
        material=material,
    )


def test_direct_report_appends_deterministic_obsidian_footnotes():
    provider = FakeProvider(["## 重点\n\n学校发布了通知[^S01]。"])

    result = generate_cited_report(
        [source("S01", "正文内容")],
        "请生成周报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert result.mode == "direct"
    assert result.cited_source_count == 1
    assert "学校发布了通知[^S01]。" in result.markdown
    assert "## 参考来源" not in result.markdown
    assert (
        "[^S01]: [测试文章](<https://mp.weixin.qq.com/s/S01>) · 微信公众号 · 测试公众号 · 2026-07-15"
        in result.markdown
    )


def test_report_persists_citations_before_each_clause_punctuation():
    provider = FakeProvider(["## 后续关注\n\n录取查询已开放。[^S01] 补录将在8月进行，[^S02]"])

    result = generate_cited_report(
        [source("S01", "正文一"), source("S02", "正文二")],
        "请生成周报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "录取查询已开放[^S01]。 补录将在8月进行[^S02]，" in result.markdown
    assert "[^S01][^S02]" not in result.markdown
    assert "标点之前" in REPORT_SYSTEM_PROMPT
    assert "分别标注各自来源" in REPORT_SYSTEM_PROMPT


def test_invalid_model_citation_is_repaired_before_persisting():
    provider = FakeProvider([
        "学校发布了通知。[^S99]",
        "学校发布了通知。[^S01]",
    ])

    result = generate_cited_report(
        [source("S01", "正文内容")],
        "请生成日报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "S99" not in result.markdown
    assert "[^S01]" in result.markdown
    assert len(provider.calls) == 2


def test_model_source_appendix_does_not_count_as_inline_citation():
    provider = FakeProvider([
        "学校发布了通知。\n\n## 参考来源\n\n[^S01]: 模型自行编写的来源",
        "学校发布了通知。[^S01]",
    ])

    result = generate_cited_report(
        [source("S01", "正文内容")],
        "请生成日报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "## 参考来源" not in result.markdown
    assert "模型自行编写的来源" not in result.markdown
    assert "[^S01]: [测试文章]" in result.markdown
    assert len(provider.calls) == 2


def test_default_group_report_prompt_is_source_agnostic_and_cited():
    prompt = _default_report_prompt()

    assert "分组覆盖的主题" in prompt
    assert "所有阶段的领域语境" in prompt
    assert "不预设固定栏目" in prompt
    assert "{articles}" not in prompt
    assert "不要重复输出报告名称" in REPORT_SYSTEM_PROMPT
    assert "不得静默遗漏" in REPORT_SYSTEM_PROMPT


def test_group_report_setup_creates_editorial_adapters_and_campus_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    with connect() as connection:
        report_prompts = connection.execute(
            "SELECT report_type, template, template_version FROM wechat_report_prompts WHERE group_id=?",
            (group["id"],),
        ).fetchall()

    report_by_type = {str(row["report_type"]): row for row in report_prompts}
    assert set(report_by_type) == {
        "group_context", "group_report_section_plan",
        "group_report_section_writer", "group_report_overview",
    }
    assert "分组主题：校园生活" in report_by_type["group_context"]["template"]
    assert "不得默认所有信息都面向全体学生" in report_by_type["group_context"]["template"]
    assert "处理全部来源不等于复述来源中的全部细节" in report_by_type["group_context"]["template"]
    assert "相同标题不必然是重复稿" in report_by_type["group_report_section_plan"]["template"]
    assert "同一事件只能安排在一个写作栏目中" in report_by_type["group_report_section_plan"]["template"]
    assert "不得要求保留“正在进行中”“即将截止”“目前有效”等相对状态" in report_by_type["group_report_section_plan"]["template"]
    assert "writing_brief 本身也不得按发布日期枚举正文提纲" in report_by_type["group_report_section_plan"]["template"]
    assert "不得用来源篇数代替" in report_by_type["group_report_section_plan"]["template"]
    assert "直接影响学生行动、学习与发展的内容" in report_by_type["group_report_section_plan"]["template"]
    assert "党建思政、例行会议和宣传性活动默认精简置后" in report_by_type["group_report_section_plan"]["template"]
    assert "无法可靠逐项核对时" in report_by_type["group_report_section_plan"]["template"]
    assert "同一时期多家企业招聘" in report_by_type["group_report_section_writer"]["template"]
    assert "初始规则和联系方式可以忠实保留" in report_by_type["group_report_section_writer"]["template"]
    assert "不得把个体意见写成学校规则" in report_by_type["group_report_section_writer"]["template"]
    assert "不得把一人多稿或转载篇数当成人数" in report_by_type["group_report_section_writer"]["template"]
    assert "下期预告" in report_by_type["group_report_section_writer"]["template"]
    assert "表格或列表已经完整表达的字段" in report_by_type["group_report_section_writer"]["template"]
    assert "引用去重以事件或信息块为作用域" in report_by_type["group_report_section_writer"]["template"]
    assert "可以在各事件末尾分别引用" in report_by_type["group_report_section_writer"]["template"]
    assert "不得输出只有引用标记的独立一行" in report_by_type["group_report_section_writer"]["template"]
    assert "不得展开学习材料目录、讲话与文件清单" in report_by_type["group_report_section_writer"]["template"]
    assert "不同原始文章数量一致" in report_by_type["group_report_section_writer"]["template"]
    assert "科研项目申报属于科研脉络，不得并入“就业与升学”" in report_by_type["group_report_overview"]["template"]
    assert "概览不承担逐栏覆盖" in report_by_type["group_report_overview"]["template"]
    assert "短引导段配合无序列表" in report_by_type["group_report_overview"]["template"]
    assert "不根据报告生成时刻添加" in report_by_type["group_report_overview"]["template"]
    assert "概览不得改写为“已完成、已结束、已经落实”" in report_by_type["group_report_overview"]["template"]
    assert all(
        row["template_version"] == DEFAULT_REPORT_PROMPT_VERSION
        for row in report_by_type.values()
    )


def test_development_prompt_sync_preserves_ui_edits_until_code_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        record = PromptTemplateRepository(connection).get_active_template("group_report_section_writer")
        assert record is not None
        PromptTemplateRepository(connection).update_template(record.id, template="前端正在测试的写作规则")
        connection.commit()

    # No code change: the UI edit remains the live source.
    initialize_database()
    with connect() as connection:
        assert PromptTemplateRepository(connection).get_template(record.id).template == "前端正在测试的写作规则"

    # A backend prompt edit is detected by its content hash and is published
    # back to both the database and the editable workspace.
    definition = next(item for item in DEFAULT_PROMPT_TEMPLATES if item["task_type"] == "group_report_section_writer")
    monkeypatch.setitem(definition, "template", "后端刚修改的写作规则")
    monkeypatch.setitem(definition, "code_revision", int(definition.get("code_revision", 1)) + 1)
    with connect() as connection:
        # A code revision is synchronized at process/database initialization;
        # invoke that maintenance hook explicitly when simulating it in-process.
        sync_builtin_prompt_definitions(connection)
        connection.commit()
        assert PromptTemplateRepository(connection).get_template(record.id).template == "后端刚修改的写作规则"


def test_generated_report_filename_uses_custom_stem_and_compact_identity_suffix(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_report",
            content_type="report",
            canonical_source_id="report:test",
            title="2026-07-13 00时00分至2026-07-19 23时59分区间汇总｜校园生活",
        )
        connection.commit()

    path = write_content_markdown_document(item.id, "# 测试报告\n", document_name="校园生活｜第29周")

    assert path.name == f"校园生活｜第29周--{item.id[:12]}.md"
    assert item.id not in path.name


def test_report_document_name_uses_short_default_and_sanitizes_user_input():
    start = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)

    default_name = _report_document_name(
        None,
        report_type="range",
        start=date(2026, 7, 13),
        end=date(2026, 7, 19),
        group_name="校园生活",
        title_window=(start, end),
    )

    assert default_name == "校园生活｜2026-07-13至07-19汇总"
    assert _report_document_name(
        "校园生活/第29周.md",
        report_type="range",
        start=date(2026, 7, 13),
        end=date(2026, 7, 19),
        group_name="校园生活",
        title_window=(start, end),
    ) == "校园生活_第29周"


def test_persisted_report_tree_title_matches_custom_markdown_filename(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "vault")
    initialize_database()
    group = create_group("校园生活")

    result = _persist_generated_report(
        group_id=group["id"],
        group_name="校园生活",
        report_type="range",
        start=date(2026, 7, 13),
        end=date(2026, 7, 19),
        window_start=datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc),
        source_count=1,
        cited_source_count=1,
        source_coverage=[],
        report_body="## 本期概览\n\n正文。[^S001]",
        generation_mode="test",
        generation_trigger="test",
        file_name="校园生活｜第29周",
        cover_url=None,
        cover_status="placeholder",
        extra_stats={},
        title_window=(
            datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc),
        ),
    )
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(result["content_item_id"])
        path = connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id=?",
            (item.id,),
        ).fetchone()["markdown_path"]

    assert item.title == "校园生活｜第29周"
    assert Path(path).name == f"校园生活｜第29周--{item.id[:12]}.md"


class GroupPipelineProvider:
    name = "fake"
    model = "group-pipeline-model"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
        self.calls.append((messages, temperature, response_format, max_tokens))
        content = self.responses.pop(0)
        if response_format == "json_object":
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("sections"), list):
                payload.setdefault("report_strategy", "测试全局策略")
                for section in payload["sections"]:
                    if not isinstance(section, dict):
                        continue
                    if "source_ids" not in section and isinstance(section.get("events"), list):
                        section["source_ids"] = [
                            source_id
                            for event in section["events"]
                            if isinstance(event, dict)
                            for source_id in event.get("source_ids", [])
                        ]
                    section.setdefault("supporting_sources", [])
                    section.setdefault("writing_brief", "测试栏目写作要求")
                content = json.dumps(payload, ensure_ascii=False)
        return LLMResponse(content=content, provider=self.name, model=self.model)


class UsageGroupPipelineProvider(GroupPipelineProvider):
    def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
        response = super().chat(
            messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
        )
        return LLMResponse(
            content=response.content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )


class StreamingPlanningProvider:
    name = "deepseek"
    model = "deepseek-v4-pro"

    def __init__(self) -> None:
        self.chat_responses = [
            "第一篇摘要",
            "学校公布了安排[^S001]。",
            "## 本期概览\n\n本期安排已经整理。",
        ]
        self.chat_calls = []
        self.stream_calls = []

    def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
        self.chat_calls.append((messages, temperature, response_format, max_tokens))
        return LLMResponse(
            content=self.chat_responses.pop(0),
            provider=self.name,
            model=self.model,
        )

    def chat_stream_events(
        self,
        messages,
        *,
        temperature=0.2,
        response_format=None,
        max_tokens=None,
    ):
        self.stream_calls.append((messages, temperature, response_format, max_tokens))
        yield LLMStreamChunk(reasoning_content="先判断来源之间是否重复。")
        yield LLMStreamChunk(reasoning_content="再确定栏目与详略节奏。")
        yield LLMStreamChunk(
            content=(
                '{"report_strategy":"突出行动信息","sections":['
                '{"title":"校园安排","source_ids":["S001"],'
                '"supporting_sources":[],"writing_brief":"简要呈现"}],'
                '"excluded_source_ids":[]}'
            )
        )
        yield LLMStreamChunk(finish_reason="stop")
        yield LLMStreamChunk(
            usage=LLMUsage(
                prompt_tokens=120,
                completion_tokens=80,
                total_tokens=200,
                prompt_cache_hit_tokens=20,
                prompt_cache_miss_tokens=100,
            )
        )


class RoutingGroupPipelineProvider(GroupPipelineProvider):
    def __init__(self) -> None:
        super().__init__([])

    def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
        self.calls.append((messages, temperature, response_format, max_tokens))
        user = messages[-1].content
        if "来源摘要：" in user:
            content = (
                '{"sections":['
                '{"title":"新版栏目","events":[{"id":"E001","title":"新版事件","source_ids":["S001"],"presentation":"paragraph"}]},'
                '{"title":"旧版栏目","source_ids":["S002"]}'
                "]}"
            )
        elif "当前栏目：新版栏目" in user:
            content = "新版栏目事实[^S001]。"
        elif "当前栏目：旧版栏目" in user:
            content = "旧版栏目事实[^S002]。"
        elif "已经写好的栏目正文" in user:
            content = "## 本期概览\n\n两类信息均已整理。"
        else:
            content = "来源短摘要"
        return LLMResponse(content=content, provider=self.name, model=self.model)


def group_source(source_id: str, material: str) -> GroupReportSource:
    return GroupReportSource(
        citation_id=source_id,
        content_item_id="",
        title=f"文章 {source_id}",
        source_url=f"https://example.test/{source_id}",
        published_at="2026-07-15T09:00:00+08:00",
        publisher="测试来源",
        source_kind="article",
        material=material,
    )


def test_group_pipeline_plans_every_source_and_writes_sections_from_full_material():
    provider = GroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001","S002"]}]}',
        "完整原文中的独有信息甲[^S001]；完整原文中的独有信息乙[^S002]。",
        "## 本期概览\n\n这段时间围绕同一主题出现两项动态。",
    ])
    first = group_source("S001", "完整原文甲：只应在栏目写作阶段出现的细节")
    second = group_source("S002", "完整原文乙：另一条只应在栏目写作阶段出现的细节")

    result = generate_group_report([first, second], "按材料自然组织", flash_provider=provider, pro_provider=provider)

    assert result.section_count == 1
    assert result.classification_retries == 0
    assert "[^S001]: [文章 S001](https://example.test/S001) · 其他来源 · 测试来源 · 2026-07-15" in result.markdown
    assert result.cited_source_count == 2
    assert [item["status"] for item in result.source_coverage] == ["cited", "cited"]
    section_call = provider.calls[3]
    assert "当前栏目：同一主题" in section_call[0][1].content
    assert "整篇策略：测试全局策略" in section_call[0][1].content
    assert "本栏写作要求：测试栏目写作要求" in section_call[0][1].content
    assert "本栏来源短摘要" in section_call[0][1].content
    assert "来源类型：article" in provider.calls[2][0][1].content
    assert "来源类型：article" in section_call[0][1].content
    assert "完整原文甲" in section_call[0][1].content
    assert "完整原文乙" in section_call[0][1].content


def test_model_footnote_definition_does_not_satisfy_inline_coverage():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001"]}]}',
        "正文事实。\n\n[^S001]: 模型错误输出的脚注定义",
        (
            '{"operations":[{"section_title":"同一主题","source_id":"S001",'
            '"action":"append_citation","anchor":"正文事实。",'
            '"markdown":"","reason":"将来源绑定到正文事实"}]}'
        ),
        "## 本期概览\n\n一项事实已经发布。",
    ])

    result = generate_group_report(
        [group_source("S001", "完整原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]: [", 1)[0]
    assert "模型错误输出的脚注定义" not in body
    assert "正文事实[^S001]。" in body
    assert result.cited_source_count == 1
    assert result.repair_call_count == 1


def retired_group_pipeline_uses_event_ledger_before_compact_event_writing():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"实践动态","events":[{"id":"E001","title":"校地实践","source_ids":["S001"],"presentation":"bullets"}]}]}',
        '{"facts":[{"text":"实践队在连平县开展技术帮扶，并完成前期对接","source_ids":["S001"]}]}',
        "- 实践队在连平县开展技术帮扶，并完成前期对接[[F001]]。",
        "## 本期概览\n\n本期实践工作持续推进。",
    ])
    source = group_source("S001", "完整原文：实践队在连平县开展技术帮扶，并完成前期对接的过程细节")

    result = generate_group_report([source], "按材料自然组织", flash_provider=provider, pro_provider=provider)

    assert result.cited_source_count == 1
    ledger_call = provider.calls[2]
    writer_call = provider.calls[3]
    assert "完整原文：实践队" in ledger_call[0][1].content
    assert "事件事实账本" in writer_call[0][1].content
    assert "F001：实践队在连平县开展技术帮扶" in writer_call[0][1].content
    assert "来源：S001" not in writer_call[0][1].content
    assert "完整原文：实践队" not in writer_call[0][1].content
    assert "待补全材料" not in result.markdown


def retired_event_pipeline_replaces_detached_provenance_with_cited_ledger_facts():
    provider = GroupPipelineProvider([
        "甲摘要", "乙摘要",
        '{"sections":[{"title":"招生动态","events":[{"id":"E001","title":"两地录取安排","source_ids":["S001","S002"],"presentation":"bullets"}]}]}',
        '{"facts":[{"text":"甲地录取查询于7月20日开放。","source_ids":["S001"]},{"text":"乙地投档结果已公布。","source_ids":["S002"]}]}',
        "两地安排已更新。\n\n*本项参考：[^S001][^S002]*",
        "## 本期概览\n\n本期录取信息已更新。",
    ])

    result = generate_group_report(
        [group_source("S001", "甲地原文"), group_source("S002", "乙地原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert "本项参考" not in body
    assert "甲地录取查询于7月20日开放[^S001]。" in body
    assert "乙地投档结果已公布[^S002]。" in body
    assert all(item["status"] == "cited" for item in result.source_coverage)


def retired_event_pipeline_accepts_table_presentation_for_compact_structured_data():
    provider = GroupPipelineProvider([
        "投档线摘要",
        '{"sections":[{"title":"招生动态","events":[{"id":"E001","title":"投档线公布","source_ids":["S001"],"presentation":"table"}]}]}',
        '{"facts":[{"text":"广东普通类物理投档线为555分。","source_ids":["S001"]}]}',
        "| 类别 | 投档线 |\n| --- | --- |\n| 普通类物理 | 555分[[F001]] |",
        "## 本期概览\n\n投档线已公布。",
    ])

    result = generate_group_report(
        [group_source("S001", "广东普通类物理投档线为555分")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "| 普通类物理 | 555分[^S001] |" in result.markdown
    writer_call = provider.calls[3]
    assert "输出形式：table" in writer_call[0][1].content


def retired_event_pipeline_merges_duplicate_sources_into_one_fact_with_all_citations():
    provider = GroupPipelineProvider([
        "同一通知摘要", "同一通知摘要", "同一通知摘要", "同一通知摘要",
        (
            '{"sections":[{"title":"校园安排","events":[{"id":"E001","title":"同一通知",'
            '"source_ids":["S001","S002","S003","S004"],"presentation":"paragraph"}]}],'
            '"excluded_source_ids":[]}'
        ),
        (
            '{"facts":[{"text":"学校发布了同一项校园安排。",'
            '"source_ids":["S001","S002","S003","S004"]}]}'
        ),
        "学校发布了同一项校园安排[[F001]]。",
        "## 本期概览\n\n本期校园安排已经发布。",
    ])

    result = generate_group_report(
        [
            group_source("S001", "官网原文"),
            group_source("S002", "公众号转载"),
            group_source("S003", "学院转载"),
            group_source("S004", "重复通知"),
        ],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert body.count("学校发布了同一项校园安排") == 1
    assert "学校发布了同一项校园安排[^S001][^S002][^S003][^S004]。" in body
    assert result.cited_source_count == 4
    assert len(provider.calls) == 8


def retired_event_pipeline_restores_an_omitted_fact_without_another_model_call():
    provider = GroupPipelineProvider([
        "甲摘要", "乙摘要",
        (
            '{"sections":[{"title":"校园安排","events":[{"id":"E001","title":"两项安排",'
            '"source_ids":["S001","S002"],"presentation":"bullets"}]}],"excluded_source_ids":[]}'
        ),
        (
            '{"facts":[{"text":"图书馆开放时间已经公布。","source_ids":["S001"]},'
            '{"text":"食堂供餐安排已经公布。","source_ids":["S002"]}]}'
        ),
        "- 图书馆开放时间已经公布[[F001]]。",
        "## 本期概览\n\n两项校园安排已经发布。",
    ])

    result = generate_group_report(
        [group_source("S001", "图书馆安排"), group_source("S002", "食堂安排")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "图书馆开放时间已经公布[^S001]。" in result.markdown
    assert "- 食堂供餐安排已经公布[^S002]。" in result.markdown
    assert result.cited_source_count == 2
    assert len(provider.calls) == 6


def retired_event_pipeline_discards_unmarked_and_duplicate_fact_prose():
    provider = GroupPipelineProvider([
        "校园通知摘要",
        (
            '{"sections":[{"title":"校园安排","events":[{"id":"E001","title":"校园通知",'
            '"source_ids":["S001"],"presentation":"paragraph"}]}],"excluded_source_ids":[]}'
        ),
        '{"facts":[{"text":"校园通知已经发布。","source_ids":["S001"]}]}',
        "校园通知已经发布[[F001]]。\n\n重复改写[[F001]]。\n\n模型自行补充的无标记事实。",
        "## 本期概览\n\n本期校园通知已经发布。",
    ])

    result = generate_group_report(
        [group_source("S001", "校园通知原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "校园通知已经发布[^S001]。" in result.markdown
    assert "重复改写" not in result.markdown
    assert "模型自行补充" not in result.markdown


def retired_event_pipeline_keeps_a_citation_on_each_fact_from_the_same_source():
    provider = GroupPipelineProvider([
        "校园服务摘要",
        (
            '{"sections":[{"title":"校园服务","events":[{"id":"E001","title":"开放安排",'
            '"source_ids":["S001"],"presentation":"bullets"}]}],"excluded_source_ids":[]}'
        ),
        (
            '{"facts":[{"text":"图书馆暑期开放。","source_ids":["S001"]},'
            '{"text":"自习室延长开放。","source_ids":["S001"]}]}'
        ),
        "- 图书馆暑期开放[[F001]]。\n- 自习室延长开放[[F002]]。",
        "## 本期概览\n\n校园服务安排已经发布。",
    ])

    result = generate_group_report(
        [group_source("S001", "图书馆与自习室开放安排")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert "- 图书馆暑期开放[^S001]。" in body
    assert "- 自习室延长开放[^S001]。" in body
    assert body.count("[^S001]") == 2


def test_group_pipeline_excludes_only_planner_declared_pure_advertising():
    provider = GroupPipelineProvider([
        "校园通知摘要", "驾校暑期价格促销",
        (
            '{"report_strategy":"校园通知优先","sections":[{"title":"校园安排",'
            '"source_ids":["S001"],"supporting_sources":[],"writing_brief":"简要说明通知"}],'
            '"excluded_source_ids":["S002"]}'
        ),
        "校园通知已经发布[^S001]。",
        "## 本期概览\n\n本期校园通知已经发布。",
    ])

    result = generate_group_report(
        [group_source("S001", "校园通知原文"), group_source("S002", "纯驾校价格广告")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert result.cited_source_count == 1
    assert [item["status"] for item in result.source_coverage] == ["cited", "excluded"]
    assert "[^S001]:" in result.markdown
    assert "[^S002]:" not in result.markdown
    assert "纯驾校价格广告" not in result.markdown


def test_group_pipeline_keeps_summaries_generic_and_applies_editorial_adapters():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001"]}]}',
        "正文事实[^S001]。",
        "## 本期概览\n\n一项动态。",
    ])

    generate_group_report(
        [group_source("S001", "完整原文")],
        "组别语境规则",
        stage_guidance={
            "group_report_section_plan": "规划适配",
            "group_report_section_writer": "写作适配",
            "group_report_overview": "概览适配",
        },
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "组别语境规则" not in provider.calls[0][0][1].content
    assert "规划适配" in provider.calls[1][0][1].content
    assert "写作适配" in provider.calls[2][0][1].content
    assert "概览适配" in provider.calls[3][0][1].content


def test_overview_prompts_define_a_report_opening_instead_of_a_reader_guide():
    assert OVERVIEW_FALLBACK == DEFAULT_GROUP_REPORT_OVERVIEW_PROMPT
    assert "概览是报告正文的第一部分" in OVERVIEW_FALLBACK
    assert "不是编者按、阅读指南、内容推荐或栏目目录" in OVERVIEW_FALLBACK
    assert "使用第三人称或无主句，不直接称呼读者" in OVERVIEW_FALLBACK
    assert "必须改用一个短引导段加无序列表分组概括" in OVERVIEW_FALLBACK
    assert "不承担逐栏覆盖" in OVERVIEW_FALLBACK
    assert "性质不同的事项强行归入同一领域" in OVERVIEW_FALLBACK
    assert "概览不得改写为“已完成、已结束、已经落实”" in OVERVIEW_FALLBACK
    assert "不同实体的实际数量一致" in OVERVIEW_FALLBACK

    campus_prompt = _campus_report_prompts(OVERVIEW_TASK)
    assert "不预设每期都必须同时出现“校园运行”和“学校发展”两条主线" in campus_prompt
    assert "校园资讯报告的平实、克制语体" in campus_prompt
    assert "科研项目申报属于科研脉络，不得并入“就业与升学”" in campus_prompt
    assert "不得把概览写成连续多段的压缩目录" in campus_prompt
    assert "直接影响学生行动、学习与发展的安全服务" in campus_prompt
    assert "概览不承担逐栏覆盖" in campus_prompt
    assert "必须使用一个短引导段配合无序列表" in campus_prompt
    assert "提示下文的阅读路径" not in campus_prompt
    assert "本期最重要的生活" not in campus_prompt


def test_planning_and_writing_fallbacks_match_managed_defaults():
    assert SECTION_PLAN_FALLBACK == DEFAULT_GROUP_REPORT_SECTION_PLAN_PROMPT
    assert SECTION_WRITER_FALLBACK == DEFAULT_GROUP_REPORT_SECTION_WRITER_PROMPT
    assert "writing_brief 本身也不得按发布日期逐日枚举正文提纲" in SECTION_PLAN_FALLBACK
    assert "不能要求写作模型保留“正在进行中”“即将截止”“目前有效”等相对状态" in SECTION_PLAN_FALLBACK
    assert "不得把来源篇数当作实体数量" in SECTION_PLAN_FALLBACK
    assert "不同原始文章数量一致" in SECTION_PLAN_FALLBACK
    assert "处理全部来源是来源覆盖约束，不是细节展开约束" in SECTION_PLAN_FALLBACK
    assert "引用去重以事件或信息块为作用域" in SECTION_WRITER_FALLBACK
    assert "可以在各事件末尾分别引用" in SECTION_WRITER_FALLBACK
    assert "不得按来源篇数推算" in SECTION_WRITER_FALLBACK
    assert "无法可靠逐项核对时" in SECTION_WRITER_FALLBACK
    assert "下期预告" in SECTION_WRITER_FALLBACK
    assert "Markdown 表格必须连续输出完整表头" in SECTION_WRITER_FALLBACK
    assert "覆盖全部来源只要求有效事实和引用可追溯" in SECTION_WRITER_FALLBACK
    assert "输出前在内部完成一次自检" in SECTION_WRITER_FALLBACK


def test_section_markdown_normalization_repairs_invalid_model_formatting():
    markdown = """| 项目 | 时间 | 说明 |
| --- | --- | --- |
| 项目甲 | 7月20日 | 已发布 |[^S001]

项目甲的补充条件。[^S001]

| 项目乙 | 7月21日 | 已发布 |

[^S001]: 模型错误输出的脚注定义

[^S002]"""

    normalized = _normalize_generated_section_markdown(markdown)

    assert "[^S001]:" not in normalized
    assert "| 项目甲 | 7月20日 | 已发布[^S001] |" in normalized
    assert normalized.count("| 项目 | 时间 | 说明 |") == 2
    assert "以上信息依据相关来源整理。[^S002]" in normalized


def test_section_heading_normalization_removes_repeated_bold_title():
    normalized = _normalize_section_heading_levels(
        "**社会实践动态**\n\n实践队完成调研。[^S001]",
        "社会实践动态",
    )

    assert normalized == "实践队完成调研。[^S001]"


def test_overview_normalization_turns_many_parallel_paragraphs_into_bullets():
    normalized = _normalize_report_overview(
        "## 本期概览\n\n"
        "本期校园运行出现多项变化。\n\n"
        "招生录取信息陆续发布。\n\n"
        "竞赛与实践形成多项成果。\n\n"
        "科研申报集中发布。"
    )

    assert normalized == (
        "## 本期概览\n\n"
        "本期校园运行出现多项变化。\n\n"
        "- 招生录取信息陆续发布。\n"
        "- 竞赛与实践形成多项成果。\n"
        "- 科研申报集中发布。"
    )


def test_source_summary_prompt_preserves_planning_dimensions_without_group_rules():
    assert SOURCE_SUMMARY_FALLBACK == DEFAULT_GROUP_REPORT_SOURCE_SUMMARY_PROMPT
    assert "适用对象" in SOURCE_SUMMARY_FALLBACK
    assert "何种信息形态" in SOURCE_SUMMARY_FALLBACK
    assert "何种状态" in SOURCE_SUMMARY_FALLBACK
    assert "多个相互独立的事项" in SOURCE_SUMMARY_FALLBACK
    assert "不做分组特定判断" in SOURCE_SUMMARY_FALLBACK


def test_group_pipeline_passes_weekly_period_context_to_every_editorial_stage():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001"]}]}',
        "正文事实[^S001]。",
        "## 本期概览\n\n一周动态已整理。",
    ])
    context = GroupReportContext(
        report_type="weekly",
        group_name="校园生活",
        window_start=datetime(2026, 7, 13, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc),
        status_as_of=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
    )

    generate_group_report(
        [group_source("S001", "完整原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        report_context=context,
    )

    assert "报告类型：周报" not in provider.calls[0][0][1].content
    for call in provider.calls[1:]:
        user_prompt = call[0][1].content
        assert "报告类型：周报" in user_prompt
        assert "报告分组：校园生活" in user_prompt
        assert "2026-07-13T00:00+00:00 至 2026-07-19T23:59+00:00" in user_prompt
        assert "状态判断时点" not in user_prompt
        assert "报告日期由产品外层标注" in user_prompt
        assert "不得根据报告生成时刻计算" in user_prompt
        assert "不要把全周事项都称为“今日”" in user_prompt


def retired_group_pipeline_handles_mixed_new_and_legacy_section_schemas_without_dropping_sources():
    provider = RoutingGroupPipelineProvider()

    result = generate_group_report(
        [group_source("S001", "新版原文"), group_source("S002", "旧版原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert result.cited_source_count == 2
    assert "## 新版栏目\n\n新版栏目事实[^S001]。" in result.markdown
    assert "## 旧版栏目\n\n旧版栏目事实[^S002]。" in result.markdown
    assert all(item["status"] == "cited" for item in result.source_coverage)


def retired_event_writer_falls_back_to_validated_ledger_instead_of_citation_placeholder():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"实践动态","events":[{"id":"E001","title":"校地实践","source_ids":["S001"],"presentation":"bullets"}]}]}',
        '{"facts":[{"text":"实践队完成前期对接","source_ids":["S001"]}]}',
        "模型第一次漏掉引用。",
        "## 本期概览\n\n实践工作持续推进。",
    ])

    result = generate_group_report(
        [group_source("S001", "实践队完成前期对接")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "- 实践队完成前期对接[^S001]" in result.markdown
    assert "本项参考" not in result.markdown
    assert result.cited_source_count == 1


def test_group_pipeline_creates_a_nonempty_overview_when_model_returns_empty_text():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"校园服务","source_ids":["S001"]}]}',
        "开放安排已经公布[^S001]。",
        "",
    ])

    result = generate_group_report(
        [group_source("S001", "开放安排已经公布")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert result.markdown.startswith("## 本期概览\n\n本期共整理 1 个主题，涵盖校园服务。")


def test_report_window_includes_an_item_exactly_at_the_start_boundary():
    start = datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 24, 23, 59, tzinfo=timezone.utc)

    assert _in_window(start.isoformat(), start, end)
    assert _in_window(end.isoformat(), start, end)
    assert not _in_window((start.replace(day=23)).isoformat(), start, end)


def test_group_pipeline_routes_summary_and_repair_to_flash_and_writing_to_pro(monkeypatch):
    providers = {
        "deepseek-v4-flash:enabled": GroupPipelineProvider([
            "一篇摘要",
            (
                '{"operations":[{"section_title":"同一主题","source_id":"S001",'
                '"action":"append_citation","anchor":"正文事实。",'
                '"markdown":"","reason":"补充已有事实引用"}]}'
            ),
        ]),
        "deepseek-v4-pro:enabled": GroupPipelineProvider([
            '{"sections":[{"title":"同一主题","source_ids":["S001"]}]}',
            "正文事实。",
            "## 本期概览\n\n一项动态。",
        ]),
    }
    selected: list[str] = []

    def fake_default_provider(option: str):
        selected.append(option)
        return providers[option]

    monkeypatch.setattr("services.group_report_pipeline.default_llm_provider", fake_default_provider)

    generate_group_report([group_source("S001", "完整原文")], "按材料自然组织")

    assert selected == [
        "deepseek-v4-flash:enabled",
        "deepseek-v4-pro:enabled",
    ]
    assert GROUP_REPORT_MODEL_CHAIN == {
        "source_summary": "deepseek-v4-flash:enabled",
        "section_plan": "deepseek-v4-pro:enabled",
        "section_writer": "deepseek-v4-pro:enabled",
        "overview": "deepseek-v4-pro:enabled",
        "citation_repair": "deepseek-v4-flash:enabled",
    }
    assert len(providers["deepseek-v4-flash:enabled"].calls) == 2
    assert len(providers["deepseek-v4-pro:enabled"].calls) == 3


def test_new_summary_revision_preserves_old_cache_history(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat", content_type="article", canonical_source_id="summary-cache-test", title="缓存测试"
        )
        connection.commit()
    source_item = GroupReportSource(
        citation_id="S001", content_item_id=item.id, title="缓存测试", source_url="", published_at="",
        publisher="测试来源", source_kind="wechat", material="第一版材料"
    )
    _store_cached_summaries([source_item], {"S001": "旧摘要"}, "old-prompt", "test-model")
    _store_cached_summaries([source_item], {"S001": "新摘要"}, "new-prompt", "test-model")

    with connect() as connection:
        rows = connection.execute(
            "SELECT prompt_hash, summary FROM group_report_source_summaries WHERE content_item_id=? AND model=?",
            (item.id, "test-model"),
        ).fetchall()
    assert {
        (row["prompt_hash"], row["summary"])
        for row in rows
    } == {("old-prompt", "旧摘要"), ("new-prompt", "新摘要")}


def test_group_pipeline_repairs_a_planned_source_missing_from_section_citations():
    provider = GroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001","S002"]}]}',
        "正文只写入第一篇事实[^S001]。",
        (
            '{"operations":[{"section_title":"同一主题","source_id":"S002",'
            '"action":"insert_after","anchor":"正文只写入第一篇事实[^S001]。",'
            '"markdown":"第二篇材料的独有安排是7月20日开放报名[^S002]。","reason":"独立信息"}]}'
        ),
        "## 本期概览\n\n两篇材料均已纳入。",
    ])

    result = generate_group_report(
        [group_source("S001", "第一篇原文"), group_source("S002", "第二篇原文：7月20日开放报名")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert result.cited_source_count == 2
    assert [item["status"] for item in result.source_coverage] == ["cited", "cited"]
    assert "第二篇材料的独有安排是7月20日开放报名[^S002]。" in result.markdown
    repair_call = provider.calls[4]
    assert "待核对的遗漏来源" in repair_call[0][1].content
    assert "遗漏来源：S002" in repair_call[0][1].content


def test_group_pipeline_repairs_duplicate_repost_by_appending_only_its_citation():
    provider = GroupPipelineProvider([
        "同一通知摘要", "同一通知转载摘要",
        (
            '{"report_strategy":"合并重复通知","sections":[{"title":"校园安排",'
            '"source_ids":["S001","S002"],"supporting_sources":[],'
            '"writing_brief":"同一事件只写一条事实线"}],"excluded_source_ids":[]}'
        ),
        "学校已公布暑期开放安排[^S001]。",
        (
            '{"operations":[{"section_title":"校园安排","source_id":"S002",'
            '"action":"append_citation","anchor":"学校已公布暑期开放安排[^S001]。",'
            '"markdown":"","reason":"重复转载"}]}'
        ),
        "## 本期概览\n\n本期校园服务安排已经公布。",
    ])

    result = generate_group_report(
        [group_source("S001", "官网通知"), group_source("S002", "同一通知转载")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert body.count("学校已公布暑期开放安排") == 1
    assert "学校已公布暑期开放安排[^S001][^S002]。" in body
    assert result.repair_call_count == 1


def test_report_plan_allows_scoped_supporting_reuse_but_requires_unique_primary_assignment():
    strategy, sections = _parse_report_plan(
        {
            "report_strategy": "先服务后发展",
            "sections": [
                {
                    "title": "校园服务",
                    "source_ids": ["S001"],
                    "supporting_sources": [],
                    "writing_brief": "详细写行动安排",
                },
                {
                    "title": "学校发展",
                    "source_ids": ["S002"],
                    "supporting_sources": [
                        {"source_id": "S001", "use_scope": "只补充服务调整的背景影响"}
                    ],
                    "writing_brief": "压缩过程，保留决定",
                },
            ],
            "excluded_source_ids": [],
        },
        {"S001", "S002"},
    )

    assert strategy == "先服务后发展"
    assert [section.source_ids for section in sections] == [("S001",), ("S002",)]
    assert sections[1].supporting_sources[0].use_scope == "只补充服务调整的背景影响"


def test_summary_cache_lookup_is_independent_of_model_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat",
            content_type="article",
            canonical_source_id="summary-model-independent",
            title="缓存测试",
        )
        connection.commit()
    source_item = GroupReportSource(
        citation_id="S001",
        content_item_id=item.id,
        title="缓存测试",
        source_url="",
        published_at="",
        publisher="测试来源",
        source_kind="wechat",
        material="相同材料",
    )
    _store_cached_summaries(
        [source_item],
        {"S001": "已缓存摘要"},
        "same-prompt",
        "deepseek-v4-flash:enabled",
    )

    assert _load_cached_summaries(
        [source_item],
        "same-prompt",
        "deepseek-v4-pro:enabled",
    ) == {"S001": "已缓存摘要"}


def test_single_source_summary_retries_transient_network_errors(monkeypatch):
    class TransientProvider:
        name = "fake"
        model = "flash"

        def __init__(self):
            self.call_count = 0

        def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
            self.call_count += 1
            if self.call_count < 3:
                raise ConnectionError("network error")
            return LLMResponse(content="重试后成功", provider=self.name, model=self.model)

    provider = TransientProvider()
    events = []
    monkeypatch.setattr("services.group_report_pipeline.sleep", lambda _seconds: None)

    summary = _summarize_one(
        group_source("S001", "原文"),
        "摘要提示词",
        provider,
        progress_callback=events.append,
    )

    assert summary == "重试后成功"
    assert provider.call_count == 3
    retry_events = [
        event for event in events
        if event["stage"] == "report_source_summaries" and event["level"] == "warning"
    ]
    assert len(retry_events) == 2
    assert "S001｜文章 S001" in retry_events[0]["message"]
    assert "第 2/3 次尝试" in retry_events[0]["message"]
    assert "第 3/3 次尝试" in retry_events[1]["message"]


def test_single_source_summary_stops_after_three_transient_failures(monkeypatch):
    class OfflineProvider:
        name = "fake"
        model = "flash"

        def __init__(self):
            self.call_count = 0

        def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
            self.call_count += 1
            raise TimeoutError("timed out")

    provider = OfflineProvider()
    monkeypatch.setattr("services.group_report_pipeline.sleep", lambda _seconds: None)

    with pytest.raises(
        RuntimeError,
        match=r"材料短摘要失败：S001｜文章 S001；连续 3 次可恢复请求均失败",
    ):
        _summarize_one(group_source("S001", "原文"), "摘要提示词", provider)

    assert provider.call_count == 3


def test_single_source_summary_does_not_retry_http_400():
    class BadRequestError(Exception):
        status_code = 400

    class BadRequestProvider:
        name = "fake"
        model = "flash"

        def __init__(self):
            self.call_count = 0

        def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
            self.call_count += 1
            raise BadRequestError("request timeout field is invalid")

    provider = BadRequestProvider()

    with pytest.raises(RuntimeError, match=r"材料短摘要失败：S001｜文章 S001；请求不可重试"):
        _summarize_one(group_source("S001", "原文"), "摘要提示词", provider)

    assert provider.call_count == 1


def test_completed_summary_is_cached_even_when_a_sibling_fails_first(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        first_item = repository.create_content_item(
            source_provider="wechat",
            content_type="article",
            canonical_source_id="partial-summary-success",
            title="已成功文章",
        )
        second_item = repository.create_content_item(
            source_provider="wechat",
            content_type="article",
            canonical_source_id="partial-summary-failure",
            title="失败文章",
        )
        connection.commit()
    sources = [
        GroupReportSource(
            citation_id="S001",
            content_item_id=first_item.id,
            title="已成功文章",
            source_url="",
            published_at="",
            publisher="测试来源",
            source_kind="wechat",
            material="成功原文",
        ),
        GroupReportSource(
            citation_id="S002",
            content_item_id=second_item.id,
            title="失败文章",
            source_url="",
            published_at="",
            publisher="测试来源",
            source_kind="wechat",
            material="失败原文",
        ),
    ]
    failure_returned = Event()

    class PartialFailureProvider:
        name = "fake"
        model = "flash"

        def chat(self, messages, *, temperature=0.2, response_format=None, max_tokens=None):
            user_prompt = messages[-1].content
            if "来源编号：S001" in user_prompt:
                assert failure_returned.wait(timeout=2)
                return LLMResponse(content="已完成摘要", provider=self.name, model=self.model)
            failure_returned.set()
            raise ValueError("invalid request")

    prompt = "摘要提示词"

    with pytest.raises(RuntimeError, match=r"材料短摘要失败：S002｜失败文章；请求不可重试"):
        _summarize_sources(sources, prompt, PartialFailureProvider())

    assert _load_cached_summaries(
        [sources[0]],
        _sha256(prompt),
        "another-model",
    ) == {"S001": "已完成摘要"}


def test_group_pipeline_repairs_a_missing_caret_in_an_otherwise_valid_citation():
    provider = GroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001","S002"]}]}',
        "第一篇事实[^S001]；第二篇事实[S002]。",
        "## 本期概览\n\n两篇材料均已纳入。",
    ])

    result = generate_group_report(
        [group_source("S001", "第一篇原文"), group_source("S002", "第二篇原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "[S002]" not in result.markdown
    assert "[^S002]" in result.markdown
    assert result.cited_source_count == 2
    assert [item["status"] for item in result.source_coverage] == ["cited", "cited"]


def test_group_pipeline_removes_citations_without_a_matching_source():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001"]}]}',
        "正文事实[^S001]，模型误写引用[^S999]。",
        "## 本期概览\n\n一项动态。",
    ])

    result = generate_group_report(
        [group_source("S001", "原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    assert "S999" not in result.markdown
    assert result.cited_source_count == 1


def test_group_pipeline_enforces_system_owned_report_heading_hierarchy():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"校园动态","source_ids":["S001"]}]}',
        "## 校园动态\n\n# 模型误写的一级标题\n\n#### 越级子标题\n\n具体事实[^S001]。",
        "# 报告正文\n\n### 本期概览\n\n本期重点已整理。",
    ])

    result = generate_group_report(
        [group_source("S001", "完整原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert body.startswith("## 本期概览\n\n本期重点已整理。")
    assert "报告正文" not in body
    assert "## 校园动态\n\n### 模型误写的一级标题\n\n#### 越级子标题" in body
    assert body.count("校园动态") == 1
    assert not any(re.match(r"^#(?!#)", line) for line in body.splitlines())


def retired_group_pipeline_coalesces_repeated_same_source_citations_to_one_fact_block():
    provider = GroupPipelineProvider([
        "一篇摘要",
        '{"sections":[{"title":"同一来源","source_ids":["S001"]}]}',
        "第一项安排[^S001]。第二项安排[^S001]。\n- 第三项安排[^S001]。",
        "## 本期概览\n\n本期有一项安排。",
    ])

    result = generate_group_report(
        [group_source("S001", "完整原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    body = result.markdown.split("\n\n[^S001]:", 1)[0]
    assert body.count("[^S001]") == 1
    assert "第一项安排。第二项安排。\n- 第三项安排[^S001]。" in body


def test_group_pipeline_progress_carries_live_usage_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    provider = UsageGroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        '{"sections":[{"title":"同一主题","source_ids":["S001","S002"]}]}',
        "完整原文甲[^S001]；完整原文乙[^S002]。",
        "## 本期概览\n\n两条信息均已呈现。",
    ])
    events = []

    generate_group_report(
        [group_source("S001", "原文甲"), group_source("S002", "原文乙")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        progress_callback=events.append,
        tracking_task_id="report:progress-metrics",
    )

    overview_event = next(event for event in events if event["stage"] == "report_overview")
    summary_events = [event for event in events if event["stage"] == "report_source_summaries"]
    assert any("开始提炼短摘要" in event["message"] for event in summary_events)
    assert sum("短摘要 " in event["message"] for event in summary_events) == 2
    assert max(event["progress"] for event in summary_events) == 28
    assert overview_event["call_count"] == 5
    assert overview_event["prompt_tokens"] == 60
    assert overview_event["completion_tokens"] == 40
    assert overview_event["total_tokens"] == 100
    assert overview_event["model"] == "group-pipeline-model"
    assert overview_event["input_chars"] > 0
    assert overview_event["output_chars"] > 0
    assert overview_event["elapsed_seconds"] >= 0
    assert all(
        event["total_tokens"] == 100
        for event in events
        if event["stage"] == "report_overview"
    )


def test_group_pipeline_continues_with_a_warning_when_plan_omits_sources():
    provider = GroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        '{"sections":[{"title":"已规划内容","source_ids":["S001"]}]}',
        "甲[^S001]。",
        "## 本期概览\n\n已规划内容已经呈现。",
    ])
    events = []

    result = generate_group_report(
        [group_source("S001", "原文甲"), group_source("S002", "原文乙")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        progress_callback=events.append,
    )

    assert result.classification_retries == 0
    assert [item["status"] for item in result.source_coverage] == ["cited", "unplanned"]
    assert result.source_coverage[1]["reason"] == "栏目规划未纳入主栏目、辅助引用或排除清单；报告已继续生成"
    assert len(provider.calls) == 5
    warning = next(
        event
        for event in events
        if event["stage"] == "report_section_plan" and event["level"] == "warning"
    )
    assert "1 篇材料未进入主栏目、辅助引用或排除清单" in warning["message"]
    assert "未规划：S002" in warning["message"]


def test_group_pipeline_treats_supporting_only_duplicate_as_planned_coverage():
    provider = GroupPipelineProvider([
        "主来源摘要", "重复来源摘要",
        (
            '{"report_strategy":"合并重复来源并简洁呈现",'
            '"sections":[{"title":"同一事件","source_ids":["S001"],'
            '"supporting_sources":[{"source_id":"S002","use_scope":"补充同一事件的重复证据"}],'
            '"writing_brief":"合并为一条事实线"}]}'
        ),
        "同一事件已经发生[^S001][^S002]。",
        "## 本期概览\n\n本期一项事件已经形成。",
    ])
    events = []

    result = generate_group_report(
        [group_source("S001", "主来源原文"), group_source("S002", "重复来源原文")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        progress_callback=events.append,
    )

    assert all(item["status"] == "cited" for item in result.source_coverage)
    assert not any(
        event["stage"] == "report_section_plan" and event["level"] == "warning"
        for event in events
    )


def test_group_pipeline_normalizes_structural_defects_without_replanning():
    provider = GroupPipelineProvider([
        "第一篇摘要", "第二篇摘要",
        (
            '{"sections":[{"title":"栏目甲","source_ids":["S001","S999"],'
            '"supporting_sources":[{"source_id":"S001","use_scope":"重复"},'
            '{"source_id":"S999","use_scope":"无效"}]},'
            '{"title":"栏目乙","source_ids":["S001","S002"]}],'
            '"excluded_source_ids":["S002"]}'
        ),
        "甲[^S001]。",
        "甲的另一部分[^S001]；乙[^S002]。",
        "## 本期概览\n\n两条信息均已呈现。",
    ])
    events = []

    result = generate_group_report(
        [group_source("S001", "原文甲"), group_source("S002", "原文乙")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        progress_callback=events.append,
    )

    assert result.classification_retries == 0
    assert all(item["status"] == "cited" for item in result.source_coverage)
    assert len(provider.calls) == 6
    warning = next(
        event
        for event in events
        if event["stage"] == "report_section_plan" and event["level"] == "warning"
    )
    assert "移除 1 个无效主来源编号" in warning["message"]
    assert "移除 2 个无效、重复或冲突的辅助来源" in warning["message"]
    assert "取消 1 个与主栏目冲突的排除标记" in warning["message"]


def test_group_pipeline_uses_json_object_planning_once():
    provider = GroupPipelineProvider([
        "第一篇摘要",
        (
            '{"report_strategy":"突出行动信息","sections":[{"title":"校园安排",'
            '"source_ids":["S001"],"supporting_sources":[],'
            '"writing_brief":"简要呈现"}],"excluded_source_ids":[]}'
        ),
        "学校公布了安排[^S001]。",
        "## 本期概览\n\n本期安排已经整理。",
    ])

    result = generate_group_report(
        [group_source("S001", "原文甲")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
    )

    plan_call = provider.calls[1]
    assert plan_call[2] == "json_object"
    assert plan_call[3] is None
    assert "submit_report_plan" not in plan_call[0][1].content
    assert len(provider.calls) == 4
    assert result.classification_retries == 0


def test_group_pipeline_streams_and_preserves_complete_planner_trace(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    provider = StreamingPlanningProvider()
    events = []

    result = generate_group_report(
        [group_source("S001", "原文甲")],
        "按材料自然组织",
        flash_provider=provider,
        pro_provider=provider,
        progress_callback=events.append,
        tracking_task_id="report:streaming-plan",
    )

    assert len(provider.stream_calls) == 1
    assert provider.stream_calls[0][2] == "json_object"
    assert len(provider.chat_calls) == 3
    diagnostics = result.planner_diagnostics
    assert diagnostics is not None
    trace_path = Path(str(diagnostics["path"]))
    assert trace_path.exists()
    assert trace_path.stat().st_mode & 0o777 == 0o600
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["reasoning_content"] == (
        "先判断来源之间是否重复。再确定栏目与详略节奏。"
    )
    assert trace["content"].startswith('{"report_strategy":"突出行动信息"')
    assert trace["finish_reason"] == "stop"
    assert trace["usage"]["total_tokens"] == 200
    assert trace["timings"]["total_seconds"] >= 0
    with connect() as connection:
        tracked = connection.execute(
            """SELECT output_chars, completion_tokens, finish_reason
                 FROM ai_calls
                WHERE task_id=? AND call_type='group_report_section_plan'""",
            ("report:streaming-plan",),
        ).fetchone()
    assert tracked["output_chars"] == (
        len(trace["reasoning_content"]) + len(trace["content"])
    )
    assert tracked["completion_tokens"] == 80
    assert tracked["finish_reason"] == "stop"
    planning_messages = [
        event["message"]
        for event in events
        if event["stage"] == "report_section_plan"
    ]
    assert any("流式通读" in message for message in planning_messages)
    assert any("已开始返回思考内容" in message for message in planning_messages)
    assert any("思考阶段已结束" in message for message in planning_messages)
    assert any("完整记录保存在" in message for message in planning_messages)


def test_streamed_plan_recovers_only_unescaped_control_characters(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    provider = StreamingPlanningProvider()
    events = []
    invalid_json = (
        '{"report_strategy":"按行动时限组织","sections":['
        '{"title":"科研项目","source_ids":["S001"],'
        '"supporting_sources":[],"writing_brief":"分两类呈现：\n'
        '1）已截止项目\n2）仍可申报项目"}],"excluded_source_ids":[]}'
    )

    def stream_with_unescaped_newlines(*args, **kwargs):
        yield LLMStreamChunk(reasoning_content="先梳理项目状态。")
        yield LLMStreamChunk(content=invalid_json)
        yield LLMStreamChunk(finish_reason="stop")

    monkeypatch.setattr(provider, "chat_stream_events", stream_with_unescaped_newlines)

    parsed, diagnostics = _chat_json_stream(
        provider,
        system="只输出 JSON。",
        user="规划栏目。",
        temperature=0.0,
        error_label="栏目规划",
        progress_callback=events.append,
        progress_metrics=None,
    )

    assert parsed["sections"][0]["writing_brief"] == (
        "分两类呈现：\n1）已截止项目\n2）仍可申报项目"
    )
    assert diagnostics["json_recovery"] == "unescaped_control_characters"
    assert any(
        event["stage"] == "report_section_plan"
        and event["level"] == "warning"
        and "已通过本地代码安全恢复" in event["message"]
        and "未重新调用 Pro" in event["message"]
        for event in events
    )


def test_json_recovery_does_not_accept_other_structural_damage():
    missing_comma = (
        '{"report_strategy":"测试" '
        '"sections":[{"title":"栏目","source_ids":["S001"]}]}'
    )
    control_character_and_missing_comma = (
        '{"report_strategy":"第一行\n第二行" '
        '"sections":[{"title":"栏目","source_ids":["S001"]}]}'
    )
    truncated = '{"report_strategy":"测试","sections":['

    assert _parse_json(missing_comma) == {}
    assert not _is_json_payload(missing_comma)
    assert _parse_json(control_character_and_missing_comma) == {}
    assert not _is_json_payload(control_character_and_missing_comma)
    assert _parse_json(truncated) == {}
    assert not _is_json_payload(truncated)


def test_report_plan_converts_known_nested_legacy_shape_without_replanning():
    normalized, adjustments = _normalize_report_plan_shape({
        "report_strategy": "按读者路径组织",
        "columns": [{
            "heading": "校园服务",
            "content_groups": [
                {"primary_source_ids": ["S001", "S002"]},
                {"source_ids": ["S002", "S003"]},
            ],
            "writing_instruction": "合并重复通知",
        }],
        "excluded_source_ids": [],
    })

    strategy, sections = _parse_report_plan(normalized, {"S001", "S002", "S003"})

    assert strategy == "按读者路径组织"
    assert [section.title for section in sections] == ["校园服务"]
    assert sections[0].source_ids == ("S001", "S002", "S003")
    assert sections[0].writing_brief == "合并重复通知"
    assert adjustments == [
        "将旧字段 columns 转换为 sections",
        "兼容转换 3 个旧版栏目字段",
    ]


def test_group_pipeline_reports_invalid_plan_json_without_retrying():
    provider = GroupPipelineProvider([
        "第一篇摘要",
        "这不是 JSON，也没有任何对象结构",
    ])

    with pytest.raises(
        ValueError,
        match=r"原始返回保存在 .*未发起重复模型调用",
    ):
        generate_group_report(
            [group_source("S001", "原文甲")],
            "按材料自然组织",
            flash_provider=provider,
            pro_provider=provider,
        )

    assert len(provider.calls) == 2
    snapshots = list(
        (settings.data_dir / "diagnostics" / "group-report-plans").glob("*.invalid.json")
    )
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "这不是 JSON，也没有任何对象结构"


def test_group_pipeline_reports_unrecognized_plan_shape_without_retrying():
    provider = GroupPipelineProvider([
        "第一篇摘要",
        '{"facts":[{"text":"一条事实","source_ids":["S001"]}]}',
    ])

    with pytest.raises(
        ValueError,
        match=r"栏目规划 JSON 结构无法识别出可写栏目；顶层字段=facts；未找到栏目数组",
    ):
        generate_group_report(
            [group_source("S001", "原文甲")],
            "按材料自然组织",
            flash_provider=provider,
            pro_provider=provider,
        )

    assert len(provider.calls) == 2


def test_report_plan_normalization_supplies_fallbacks_and_drops_empty_sections():
    strategy, sections, excluded, adjustments = normalize_report_plan(
        "",
        [
            _Section(
                title="空栏目",
                source_ids=("S999",),
                writing_brief="",
            ),
            _Section(
                title="有效栏目",
                source_ids=("S001", "S001"),
                supporting_sources=(
                    _SupportingSource("S001", "本栏重复"),
                    _SupportingSource("S002", "补充背景"),
                ),
                writing_brief="",
            ),
        ],
        {"S002"},
        {"S001", "S002"},
    )

    assert strategy
    assert [section.title for section in sections] == ["有效栏目"]
    assert sections[0].source_ids == ("S001",)
    assert sections[0].supporting_sources == ()
    assert sections[0].writing_brief
    assert excluded == {"S002"}
    assert "补充通用报告策略" in adjustments
    assert "删除 1 个没有可用主来源的空栏目" in adjustments


def test_rule_generated_footnote_uses_only_first_title_line():
    provider = FakeProvider(["学校发布了通知。[^S01]"])
    multiline_source = source("S01", "正文内容", "第一行\n第二行")

    result = generate_cited_report(
        [multiline_source],
        "请生成日报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "[^S01]: [第一行]" in result.markdown
    assert "第一行\n第二行" not in result.markdown


def test_rule_generated_footnote_caps_abnormally_long_source_title():
    provider = FakeProvider(["学校发布了通知。[^S01]"])
    malformed_source = source("S01", "正文内容", "标题" * 100)

    result = generate_cited_report(
        [malformed_source],
        "请生成日报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "标题" * 60 not in result.markdown
    assert "…](<https://mp.weixin.qq.com/s/S01>)" in result.markdown


def test_large_report_uses_fact_cards_before_final_writing():
    provider = FakeProvider([
        FACT_JSON,
        FACT_JSON,
        "## 本周概览\n\n两篇文章都发布了校园通知。[^S01][^S02]",
    ])
    sources = [
        source("S01", "甲" * 26_000, "文章甲"),
        source("S02", "乙" * 26_000, "文章乙"),
    ]

    result = generate_cited_report(
        sources,
        "请生成周报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert result.mode == "hierarchical"
    assert result.cited_source_count == 2
    assert "[^S01]" in result.markdown
    assert "[^S02]" in result.markdown
    assert len(provider.calls) == 3


def test_coverage_audit_adds_uncited_independent_information_to_other_dynamics():
    provider = FakeProvider([
        "## 本期概览\n\n学校发布了通知。[^S01]",
        """{
          "decisions": [{
            "source_id": "S02",
            "status": "include_other",
            "reason": "包含正文尚未提及的报名截止时间",
            "summary": "另一项活动的报名截止时间为 7 月 20 日。"
          }]
        }""",
    ])

    result = generate_cited_report(
        [
            source("S01", "学校发布了通知", "通知"),
            source("S02", "活动报名截止时间为 7 月 20 日", "活动报名"),
        ],
        "请生成周报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert "## 其他动态" in result.markdown
    assert "另一项活动的报名截止时间为 7 月 20 日[^S02]。" in result.markdown
    assert result.cited_source_count == 2
    assert [item.status for item in result.source_coverage] == ["cited_main", "cited_other"]
    assert "[^S02]: [活动报名]" in result.markdown


def test_coverage_audit_records_why_a_source_was_not_cited():
    provider = FakeProvider([
        "## 本期概览\n\n学校发布了通知。[^S01]",
        """{
          "decisions": [{
            "source_id": "S02",
            "status": "exclude_duplicate",
            "reason": "内容与 S01 为同一通知且没有新增事实",
            "summary": ""
          }]
        }""",
    ])

    result = generate_cited_report(
        [
            source("S01", "学校发布了通知", "通知原文"),
            source("S02", "学校发布了同一份通知", "通知转载"),
        ],
        "请生成周报：\n{articles}",
        provider=provider,
        use_cache=False,
    )

    assert result.cited_source_count == 1
    assert "[^S02]:" not in result.markdown
    assert result.source_coverage[1].status == "exclude_duplicate"
    assert result.source_coverage[1].reason == "内容与 S01 为同一通知且没有新增事实"


def test_report_fails_instead_of_silently_saving_without_sources():
    provider = FakeProvider([
        "这是一份没有引用的报告。",
        "仍然没有引用。",
    ])

    try:
        generate_cited_report(
            [source("S01", "正文内容")],
            "请生成周报：\n{articles}",
            provider=provider,
            use_cache=False,
        )
    except ValueError as exc:
        assert "有效来源标注" in str(exc)
    else:
        raise AssertionError("缺少来源标注时不应保存报告")


def test_unchanged_article_fact_cards_are_reused_from_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        first_item = repository.create_content_item(source_provider="wechat", content_type="article", title="文章甲")
        second_item = repository.create_content_item(source_provider="wechat", content_type="article", title="文章乙")
        connection.commit()

    sources = [
        ReportSource("S01", first_item.id, "文章甲", "https://example.com/1", "2026-07-15", "公众号", "甲" * 26_000),
        ReportSource("S02", second_item.id, "文章乙", "https://example.com/2", "2026-07-15", "公众号", "乙" * 26_000),
    ]
    first_provider = FakeProvider([
        FACT_JSON,
        FACT_JSON,
        "第一次报告。[^S01][^S02]",
    ])
    generate_cited_report(sources, "{articles}", provider=first_provider)

    second_provider = FakeProvider(["第二次报告。[^S01][^S02]"])
    result = generate_cited_report(sources, "{articles}", provider=second_provider)

    assert result.mode == "hierarchical"
    assert len(second_provider.calls) == 1
    assert "第二次报告" in result.markdown
