from __future__ import annotations

from datetime import date, datetime, timezone
import json
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
import services.campus_digest_generation as campus_digest
from services.campus_digest_generation import (
    CampusEventEmbedder,
    CampusDigestSource,
    _audit_and_repair,
    _hard_conflict,
    _parse_fact_card,
    _prepare_event_briefs,
    _prepare_sections,
    _rule_pair_decision,
    _write_category_section,
    generate_campus_digest,
)
from services.campus_digest_editorial import write_overview
from services.campus_digest_scheduler import latest_daily_window, latest_weekly_window
from services.database import connect, initialize_database
from services.llm_provider import LLMResponse
from services.repository import ContentRepository
from services.wechat_reports import _report_title
from services.wechat_reports import (
    DEFAULT_REPORT_PROMPT_VERSION,
    _campus_report_prompts,
    _default_report_prompt,
    _editorial_prompt_type,
    _ensure_default_prompts,
)


class FakeProvider:
    name = "fake"

    def __init__(self, model: str, responses: list[str]) -> None:
        self.model = model
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, *, temperature=0.2, response_format=None):
        self.calls.append((messages, temperature, response_format))
        if not self.responses:
            raise AssertionError(f"{self.model} 缺少预设响应")
        return LLMResponse(
            content=self.responses.pop(0),
            provider=self.name,
            model=self.model,
        )


def _fact(*, source: str, summary: str, date: str = "", location: str = "") -> str:
    return json.dumps(
        {
            "summary": summary,
            "content_decision": "include",
            "decision_reason": "包含可核验的校园活动信息",
            "category": "校园活动与文体",
            "document_type": "activity",
            "event_stage": "announcement",
            "event_or_subject": "校园文化节",
            "issuers": [],
            "organizers": ["校团委"],
            "actors": [],
            "actions": ["举办校园文化节"],
            "objects": ["校园文化节"],
            "audiences": ["在校学生"],
            "time_points": [date] if date else [],
            "locations": [location] if location else [],
            "terms_or_batches": [],
            "identifiers": [],
            "links": [],
            "attachments": [],
            "topics": ["校园文化"],
            "atomic_facts": [
                {
                    "text": summary,
                    "evidence": source,
                    "origin": "image_ocr" if "海报" in source else "html",
                    "locator": "image_1" if "海报" in source else "正文",
                    "ocr_only": "海报" in source,
                }
            ],
            "ad_segments": [],
            "uncertainties": [],
        },
        ensure_ascii=False,
    )


def _source(citation_id: str, content_id: str, title: str, material: str) -> CampusDigestSource:
    return CampusDigestSource(
        citation_id=citation_id,
        content_item_id=content_id,
        title=title,
        source_url=f"https://mp.weixin.qq.com/s/{content_id}",
        published_at="2026-07-16T10:00:00+08:00",
        publisher="校园公众号",
        source_channel="wechat",
        source_section="校园活动",
        material=material,
    )


def test_fact_card_allows_missing_identity_fields_and_keeps_ocr_provenance():
    card = _parse_fact_card(_fact(source="海报写明活动安排", summary="学校将举办校园文化节"))

    assert card["time_points"] == []
    assert card["locations"] == []
    assert card["atomic_facts"][0]["origin"] == "image_ocr"
    assert card["atomic_facts"][0]["ocr_only"] is True


def test_embedding_feature_is_disabled_before_local_or_remote_model_loading(monkeypatch):
    calls = []

    class MissingLocalModel:
        def __init__(self, model_name, **kwargs):
            calls.append((model_name, kwargs))
            raise OSError("model is not cached")

    monkeypatch.setattr(settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=MissingLocalModel),
    )
    events = []

    vectors, model = CampusEventEmbedder().encode(
        ["校园文化节"],
        progress_callback=events.append,
    )

    assert calls == []
    assert model == "hash-char-ngram-v1"
    assert len(vectors) == 1
    assert any(event["level"] == "warn" and "目前暂停" in event["message"] for event in events)


def test_embedding_feature_does_not_call_the_api_while_disabled(monkeypatch):
    created = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            created.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[3.0, 4.0]),
                    SimpleNamespace(index=1, embedding=[0.0, 2.0]),
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr(settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setattr(settings, "campus_embedding_api_model", "text-embedding-v4")
    monkeypatch.setattr(settings, "campus_embedding_api_dimensions", 1024)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    vectors, model = CampusEventEmbedder().encode(["甲", "乙"])

    assert model == "hash-char-ngram-v1"
    assert created == []
    assert len(vectors) == 2


def test_different_explicit_editions_are_a_hard_conflict():
    left = _parse_fact_card(_fact(source="正文", summary="第六届比赛开始报名"))
    right = _parse_fact_card(_fact(source="正文", summary="第七届比赛开始报名"))
    left["terms_or_batches"] = ["第六届"]
    right["terms_or_batches"] = ["第七届"]

    assert _hard_conflict(left, right) is True


def test_targeted_audit_repair_can_replace_a_wrong_citation():
    auditor = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "section": "校园活动与文体",
                            "problem": "wrong_citation",
                            "sentence": "活动地点为图书馆[^S001]。",
                            "reason": "地点只由 S002 支持",
                            "source_ids": ["S002"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ],
    )
    repair = FakeProvider("deepseek-v4-pro", ["### 校园活动\n\n活动地点为图书馆[^S002]。"])
    briefs = [
        {
            "title": "校园活动",
            "category": "校园活动与文体",
            "summary": "校园活动地点信息",
            "stages": [],
            "conflicts": [],
            "source_ids": ["S001", "S002"],
        }
    ]

    result = _audit_and_repair(
        overview="本期包含校园活动[^S001]。",
        sections={"校园活动与文体": "### 校园活动\n\n活动地点为图书馆[^S001]。"},
        briefs=briefs,
        fact_cards=[],
        provider=auditor,
        repair_provider=repair,
    )

    assert result["校园活动与文体"] == "### 校园活动\n\n活动地点为图书馆[^S002]。"


def test_overview_audit_repair_returns_markdown_body_instead_of_generation_json():
    auditor = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "section": "本期概览",
                            "problem": "wrong_citation",
                            "sentence": "校园服务进入暑期安排[^S001]。",
                            "reason": "应由S002支持",
                            "source_ids": ["S002"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ],
    )
    repair = FakeProvider(
        "deepseek-v4-pro",
        ["校园服务逐步转入暑期安排[^S002]。\n\n正文按校园事务类型整理，可以从相应栏目继续阅读。"],
    )
    briefs = [
        {
            "title": "暑期服务安排",
            "category": "校园生活与服务",
            "summary": "校园服务采用暑期安排",
            "stages": [],
            "conflicts": [],
            "source_ids": ["S001", "S002"],
        }
    ]

    result = _audit_and_repair(
        overview="校园服务进入暑期安排[^S001]。",
        sections={"校园生活与服务": "### 暑期服务安排\n\n服务安排已公布[^S002]。"},
        briefs=briefs,
        fact_cards=[],
        provider=auditor,
        repair_provider=repair,
    )

    assert result["本期概览"].startswith("校园服务逐步转入暑期安排")
    repair_system = repair.calls[0][0][0].content
    assert "仅输出修订后的概览正文" in repair_system
    assert "不输出 JSON" in repair_system


def test_audit_repair_cannot_drop_or_merge_event_headings():
    auditor = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "section": "校园活动与文体",
                            "problem": "wrong_citation",
                            "sentence": "活动地点待核对[^S001]。",
                            "reason": "引用不足",
                            "source_ids": ["S001"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ],
    )
    repair = FakeProvider("deepseek-v4-pro", ["活动地点已经核对[^S001]。"])
    current = "### 活动甲\n\n活动地点待核对[^S001]。\n\n### 活动乙\n\n活动照常举行[^S002]。"
    briefs = [
        {
            "title": "活动甲",
            "category": "校园活动与文体",
            "summary": "活动地点待核对",
            "stages": [],
            "conflicts": [],
            "source_ids": ["S001", "S002"],
        }
    ]

    result = _audit_and_repair(
        overview="本期包含两项活动[^S001]。",
        sections={"校园活动与文体": current},
        briefs=briefs,
        fact_cards=[],
        provider=auditor,
        repair_provider=repair,
    )

    assert result["校园活动与文体"] == current


def test_empty_urls_and_same_title_without_core_evidence_do_not_auto_merge():
    left = _source("S001", "content-1", "关于开展校园活动的通知", "甲活动安排")
    right = _source("S002", "content-2", "关于开展校园活动的通知", "乙活动安排")
    left = CampusDigestSource(**{**left.__dict__, "source_url": ""})
    right = CampusDigestSource(**{**right.__dict__, "source_url": ""})
    left_card = _parse_fact_card(_fact(source="甲活动安排", summary="甲活动"))
    right_card = _parse_fact_card(_fact(source="乙活动安排", summary="乙活动"))
    for card in (left_card, right_card):
        card["organizers"] = []
        card["objects"] = []
        card["audiences"] = []

    decision = _rule_pair_decision(left, left_card, right, right_card, 0.8)

    assert decision is None


def test_clustered_digest_analyzes_each_article_and_lists_every_non_ad_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "campus_embedding_enabled", False)
    initialize_database()
    sources = [
        _source("S001", "content-1", "校园文化节活动通知", "正文发布校园文化节安排"),
        _source("S002", "content-2", "校园文化节活动通知", "正文发布校园文化节安排"),
    ]
    with connect() as connection:
        repository = ContentRepository(connection)
        for index, source in enumerate(sources, start=1):
            item = repository.create_content_item(
                source_provider="wechat",
                content_type="article",
                source_url=source.source_url,
                canonical_source_id=f"test-{index}",
                title=source.title,
            )
            connection.execute("UPDATE content_items SET id=? WHERE id=?", (source.content_item_id, item.id))
        connection.commit()
    flash = FakeProvider(
        "deepseek-v4-flash",
        [
            _fact(source="正文发布校园文化节安排", summary="学校将举办校园文化节", date="7月20日"),
            json.dumps(
                {
                    "events": [{
                        "event_id": "E01",
                        "title": "校园文化节",
                        "paragraphs": ["校园文化节将于7月20日举行[^S001]。"],
                        "details": [],
                    }],
                },
                ensure_ascii=False,
            ),
        ],
    )
    pro = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "period_portrait": ["校园文化节的举办安排已经公布[^S001]。"],
                    "reading_guide": "正文按校园事务类型整理。",
                },
                ensure_ascii=False,
            )
        ],
    )
    auditor = FakeProvider(
        "deepseek-v4-pro",
        [json.dumps({"passed": True, "issues": []}, ensure_ascii=False)],
    )

    progress_events = []
    result = generate_campus_digest(
        sources,
        sources,
        report_type="daily",
        flash_provider=flash,
        pro_provider=pro,
        audit_provider=auditor,
        use_cache=False,
        progress_callback=progress_events.append,
    )

    assert result.cluster_count == 1
    assert result.included_source_count == 2
    assert "## 本期概览" in result.markdown
    assert "## 校园活动与文体" in result.markdown
    assert "### 校园文化节" in result.markdown
    assert "## 来源文章" in result.markdown
    assert "content-1" in result.markdown
    assert "content-2" in result.markdown
    assert len(flash.calls) == 2
    stages = {event["stage"] for event in progress_events}
    assert {
        "report_facts",
        "report_embeddings",
        "report_clustering",
        "report_briefs",
        "report_sections",
        "report_overview",
        "report_audit",
    } <= stages
    assert any(event["level"] == "warn" and "离线字符向量" in event["message"] for event in progress_events)
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM campus_event_clusters").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM campus_event_members").fetchone()[0] == 2


def test_section_editor_renders_every_event_with_stable_markdown_hierarchy():
    briefs = [
        {
            "title": "电影放映",
            "category": "校园活动与文体",
            "summary": "图书馆安排电影放映",
            "stages": [],
            "conflicts": [],
            "source_ids": ["S001"],
        },
        {
            "title": "食堂假期安排",
            "category": "校园活动与文体",
            "summary": "食堂公布假期供餐安排",
            "stages": [],
            "conflicts": [],
            "source_ids": ["S002"],
        },
    ]
    provider = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "events": [
                        {
                            "event_id": "E01",
                            "title": "图书馆电影放映",
                            "paragraphs": ["图书馆将在周五晚放映电影[^S001]。"],
                            "details": ["**地点：**106光影厅[^S001]。"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ],
    )

    section = _write_category_section(
        "校园活动与文体",
        briefs,
        report_type="daily",
        editorial_guidance="务实亲和；每个事件使用清晰标题。\n\n{articles}",
        provider=provider,
    )

    assert section.count("### ") == 2
    assert "### 图书馆电影放映" in section
    assert "- **地点：**106光影厅[^S001]。" in section
    assert "### 食堂假期安排" in section
    assert "食堂公布假期供餐安排[^S002]。" in section
    user_prompt = provider.calls[0][0][1].content
    assert "编辑规范同时控制口吻、信息取舍和呈现方式" in user_prompt
    assert "不设统一字数目标" in user_prompt
    assert "活动、新闻和人物内容保持必要的来龙去脉" in user_prompt
    assert "课程、招生、科研项目或公示" in user_prompt
    assert "120至350" not in user_prompt
    assert "仅用于口吻参考" not in user_prompt


def test_overview_prompt_builds_period_portrait_and_reading_guide_without_relisting_sections():
    sections = {
        "校园生活与服务": "### 暑期开放安排\n\n图书馆公布暑期开放时段[^S001]。",
        "招生、升学与就业": "### 录取进程\n\n学校公布首批录取查询信息[^S002]。",
    }
    provider = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "period_portrait": [
                        "校园信息逐渐转入暑期节奏，校内服务开始采用假期安排，招生录取也进入查询阶段[^S001][^S002]。"
                    ],
                    "reading_guide": "正文按校园事务类型整理，想了解假期办事安排或招生进展，可以从相应栏目继续阅读。",
                },
                ensure_ascii=False,
            )
        ],
    )

    overview = write_overview(
        sections,
        report_type="daily",
        editorial_guidance="客观呈现，语气亲和务实。",
        provider=provider,
    )

    assert "逐渐转入暑期节奏" in overview
    assert "可以从相应栏目继续阅读" in overview
    assert overview.count("\n\n") == 1
    system_prompt = provider.calls[0][0][0].content
    user_prompt = provider.calls[0][0][1].content
    assert "时期校园里主要发生了什么" in system_prompt
    assert "阅读引导" in system_prompt
    assert "不逐篇复述" in system_prompt
    assert "不要为每个栏目各写一句" in user_prompt
    assert "period_portrait" in user_prompt
    assert "reading_guide" in user_prompt
    assert provider.calls[0][2] == "json_object"


def test_overview_renderer_limits_portrait_and_supplies_missing_reading_guide():
    sections = {
        "教务与学业": "### 教务安排\n\n学校公布暑期教学安排[^S001]。",
        "校园生活与服务": "### 服务安排\n\n校内服务转入暑期时段[^S002]。",
    }
    provider = FakeProvider(
        "deepseek-v4-pro",
        [
            json.dumps(
                {
                    "period_portrait": [
                        "教学工作进入暑期阶段[^S001]。",
                        "校内服务也采用假期安排[^S002]。",
                        "这一段不应被渲染[^S001]。",
                    ]
                },
                ensure_ascii=False,
            )
        ],
    )

    overview = write_overview(
        sections,
        report_type="daily",
        editorial_guidance="客观呈现。",
        provider=provider,
    )

    paragraphs = overview.split("\n\n")
    assert len(paragraphs) == 3
    assert "这一段不应被渲染" not in overview
    assert paragraphs[-1] == "正文按校园事务类型整理，可以根据需要从“教务与学业”、“校园生活与服务”栏目继续阅读。"


def test_event_briefs_and_sections_use_bounded_parallelism_and_keep_display_order(monkeypatch):
    lock = threading.Lock()
    brief_active = 0
    brief_peak = 0
    section_active = 0
    section_peak = 0

    def fake_event_brief(cluster_id, indexes, sources, cards, *, provider, use_cache):
        nonlocal brief_active, brief_peak
        with lock:
            brief_active += 1
            brief_peak = max(brief_peak, brief_active)
        time.sleep(0.04)
        with lock:
            brief_active -= 1
        index = indexes[0]
        return {
            "title": f"事件 {index}",
            "category": campus_digest.CAMPUS_CATEGORIES[index],
            "summary": f"摘要 {index}",
            "stages": [],
            "conflicts": [],
            "source_ids": [sources[index].citation_id],
        }

    def fake_write_section(category, briefs, *, report_type, editorial_guidance, provider):
        nonlocal section_active, section_peak
        with lock:
            section_active += 1
            section_peak = max(section_peak, section_active)
        time.sleep(0.04)
        with lock:
            section_active -= 1
        return f"### {briefs[0]['title']}\n\n{briefs[0]['summary']}[^{briefs[0]['source_ids'][0]}]。"

    monkeypatch.setattr(campus_digest, "_event_brief", fake_event_brief)
    monkeypatch.setattr(campus_digest, "_write_category_section", fake_write_section)
    sources = [
        _source(f"S00{index + 1}", f"content-{index}", f"文章 {index}", f"材料 {index}")
        for index in range(4)
    ]
    clusters = [
        campus_digest.EventCluster(id=f"cluster-{index}", member_indexes=[index])
        for index in range(4)
    ]
    monkeypatch.setattr(
        campus_digest,
        "default_llm_provider",
        lambda _profile: SimpleNamespace(model="test-model"),
    )
    events = []

    briefs = _prepare_event_briefs(
        clusters,
        sources,
        [{"unused": True} for _ in sources],
        included_ids={source.content_item_id for source in sources},
        provider=None,
        use_cache=False,
        progress_callback=events.append,
    )
    sections = _prepare_sections(
        briefs,
        report_type="daily",
        editorial_guidance="客观呈现",
        provider=None,
        progress_callback=events.append,
    )

    assert brief_peak == 4
    assert section_peak == 3
    assert [brief["title"] for brief in briefs] == [f"事件 {index}" for index in range(4)]
    assert list(sections) == list(campus_digest.CAMPUS_CATEGORIES[:4])
    assert all("elapsed_seconds" in event for event in events)
    assert all(event["model"] == "test-model" for event in events)


def test_group_report_prompts_create_context_and_all_stage_adapters(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group_id = "legacy-group"
    now = "2026-07-17T00:00:00+00:00"
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id,name,description,include_campus_sources,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (group_id, "校园生活", "", 1, now, now),
        )
        _ensure_default_prompts(connection, group_id)
        connection.commit()
        prompts = connection.execute(
            """SELECT report_type, template, template_version, display_name
               FROM wechat_report_prompts WHERE group_id=? ORDER BY report_type""",
            (group_id,),
        ).fetchall()

    assert len(prompts) == 4
    by_type = {str(prompt["report_type"]): prompt for prompt in prompts}
    assert set(by_type) == {
        "group_context", "group_report_section_plan",
        "group_report_section_writer", "group_report_overview",
    }
    assert "分组主题：校园生活" in by_type["group_context"]["template"]
    assert by_type["group_context"]["template_version"] == DEFAULT_REPORT_PROMPT_VERSION
    assert by_type["group_context"]["display_name"] == "组别说明"


def test_campus_report_prompts_enforce_general_editorial_balance():
    plan_prompt = _campus_report_prompts("group_report_section_plan")
    writer_prompt = _campus_report_prompts("group_report_section_writer")
    overview_prompt = _campus_report_prompts("group_report_overview")

    assert "不得为了减少栏目数牺牲栏目内聚性" in plan_prompt
    assert "发布频率和原文总长度不能决定栏目位置或篇幅" in plan_prompt
    assert "检查删除该节点是否会改变事件结论" in writer_prompt
    assert "事件或信息块—全部支撑来源" in writer_prompt
    assert "不同列表项或表格行实际代表不同事件" in writer_prompt
    assert "不从“这份报告收集、整理、涵盖了什么”起笔" in overview_prompt
    assert "不得统计栏目数或主题数" in overview_prompt
    assert "不同脉络没有事实联系时可以并列陈述" in overview_prompt
    assert "赛车" not in plan_prompt + writer_prompt + overview_prompt


def test_daily_weekly_and_custom_windows_share_the_interval_prompt():
    assert _editorial_prompt_type("daily", None, None) == "group_context"
    assert _editorial_prompt_type("weekly", None, None) == "group_context"
    assert _editorial_prompt_type(
        "range",
        datetime.fromisoformat("2026-07-17T09:00:00+08:00"),
        datetime.fromisoformat("2026-07-17T18:00:00+08:00"),
    ) == "group_context"


def test_scheduler_uses_agreed_local_cutoffs(monkeypatch):
    monkeypatch.setattr(settings, "campus_digest_daily_cutoff", "21:15")
    monkeypatch.setattr(settings, "campus_digest_daily_generate_at", "21:30")
    monkeypatch.setattr(settings, "campus_digest_weekly_cutoff", "19:30")
    monkeypatch.setattr(settings, "campus_digest_weekly_generate_at", "20:00")
    now = datetime.fromisoformat("2026-07-19T22:00:00+08:00")  # Sunday

    daily = latest_daily_window(now)
    weekly = latest_weekly_window(now)

    assert daily.window_end.isoformat() == "2026-07-19T21:15:00+08:00"
    assert daily.generate_at.isoformat() == "2026-07-19T21:30:00+08:00"
    assert weekly.window_end.isoformat() == "2026-07-19T19:30:00+08:00"
    assert weekly.generate_at.isoformat() == "2026-07-19T20:00:00+08:00"


def test_scheduled_daily_title_uses_window_end_date():
    assert _report_title(
        "daily",
        start=date(2026, 7, 15),
        end=date(2026, 7, 16),
        group_name="校园生活",
    ) == "2026-07-16日报｜校园生活"


def test_custom_range_title_includes_cross_day_selected_times():
    assert _report_title(
        "range",
        start=date(2026, 7, 16),
        end=date(2026, 7, 18),
        group_name="校园生活",
        title_window=(
            datetime.fromisoformat("2026-07-16T09:00:00+08:00"),
            datetime.fromisoformat("2026-07-18T11:30:00+08:00"),
        ),
    ) == "2026-07-16 09时00分至2026-07-18 11时30分区间汇总｜校园生活"


def test_sunday_windows_do_not_open_before_generation_time(monkeypatch):
    monkeypatch.setattr(settings, "campus_digest_daily_cutoff", "21:15")
    monkeypatch.setattr(settings, "campus_digest_daily_generate_at", "21:30")
    monkeypatch.setattr(settings, "campus_digest_weekly_cutoff", "19:30")
    monkeypatch.setattr(settings, "campus_digest_weekly_generate_at", "20:00")
    sunday_before_weekly = datetime.fromisoformat("2026-07-19T19:45:00+08:00")
    sunday_before_daily = datetime.fromisoformat("2026-07-19T21:20:00+08:00")

    weekly = latest_weekly_window(sunday_before_weekly)
    daily = latest_daily_window(sunday_before_daily)

    assert weekly.window_end.date() == date(2026, 7, 12)
    assert daily.window_end.date() == date(2026, 7, 18)
