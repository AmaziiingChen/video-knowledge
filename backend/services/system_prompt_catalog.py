"""Read-only catalog for code-owned system prompts and their fallbacks."""

from __future__ import annotations


def list_fixed_system_prompts() -> list[dict[str, str]]:
    # Lazy imports keep the normal application startup path free of report
    # pipeline imports until the user opens the prompt workspace.
    from services.group_report_pipeline import (
        CITATION_REPAIR_FALLBACK,
        OVERVIEW_FALLBACK,
        SECTION_PLAN_FALLBACK,
        SECTION_WRITER_FALLBACK,
        SOURCE_SUMMARY_FALLBACK,
    )
    from services.prompt_templates import DEFAULT_PROMPT_TEMPLATES
    from services.source_context import SOURCE_CONTEXT_CORE_GUARDRAIL
    from services.wechat_report_generation import (
        COVERAGE_AUDIT_SYSTEM_PROMPT,
        FACT_EXTRACTION_SYSTEM_PROMPT,
        REPORT_SYSTEM_PROMPT,
    )

    generic_fallbacks = [
        {
            "id": f"fallback:template:{item['task_type']}:{item['version']}:{item['name']}",
            "category": "系统兜底 · 通用任务管线",
            "name": str(item["name"]),
            "description": "仅当当前启用提示词无法读取时使用的内置默认 system prompt。",
            "template": str(item["template"]),
        }
        for item in DEFAULT_PROMPT_TEMPLATES
        # 快捷命令以 user 消息追加到侧栏对话，不属于 system prompt。
        if str(item["task_type"]) != "qa_shortcut"
    ]
    group_fallbacks = [
        {
            "id": "fallback:group-report:source-summary",
            "category": "系统兜底 · 分组报告管线",
            "name": "单篇短摘要",
            "description": "仅当当前启用的单篇短摘要提示词无法读取时使用。",
            "template": SOURCE_SUMMARY_FALLBACK,
        },
        {
            "id": "fallback:group-report:section-plan",
            "category": "系统兜底 · 分组报告管线",
            "name": "栏目规划",
            "description": "仅当当前启用的栏目规划提示词无法读取时使用。",
            "template": SECTION_PLAN_FALLBACK,
        },
        {
            "id": "fallback:group-report:section-writer",
            "category": "系统兜底 · 分组报告管线",
            "name": "栏目写作",
            "description": "仅当当前启用的栏目写作提示词无法读取时使用。",
            "template": SECTION_WRITER_FALLBACK,
        },
        {
            "id": "fallback:group-report:overview",
            "category": "系统兜底 · 分组报告管线",
            "name": "概览写作",
            "description": "仅当当前启用的概览提示词无法读取时使用。",
            "template": OVERVIEW_FALLBACK,
        },
        {
            "id": "fallback:group-report:citation-repair",
            "category": "系统兜底 · 分组报告管线",
            "name": "引用局部校对",
            "description": "仅当当前启用的引用局部校对提示词无法读取时使用。",
            "template": CITATION_REPAIR_FALLBACK,
        },
    ]
    fixed_prompts = [
        {
            "id": "source-context:core-guardrail",
            "category": "固定系统规则 · 平台互动材料",
            "name": "评论输入安全边界",
            "description": "与可编辑的“互动评论分析规则”组合使用，防止平台评论改变模型任务或输出约束。",
            "template": SOURCE_CONTEXT_CORE_GUARDRAIL,
        },
        {
            "id": "wechat-report:writer",
            "category": "固定系统规则 · 公众号报告兼容管线",
            "name": "报告正文写作",
            "description": "旧版公众号日报/周报兼容管线实际使用的固定 system prompt。",
            "template": REPORT_SYSTEM_PROMPT,
        },
        {
            "id": "wechat-report:fact-extraction",
            "category": "固定系统规则 · 公众号报告兼容管线",
            "name": "来源事实卡提取",
            "description": "旧版公众号日报/周报兼容管线实际使用的固定 system prompt。",
            "template": FACT_EXTRACTION_SYSTEM_PROMPT,
        },
        {
            "id": "wechat-report:coverage-audit",
            "category": "固定系统规则 · 公众号报告兼容管线",
            "name": "来源覆盖审校",
            "description": "旧版公众号日报/周报兼容管线实际使用的固定 system prompt。",
            "template": COVERAGE_AUDIT_SYSTEM_PROMPT,
        },
    ]
    return [*generic_fallbacks, *group_fallbacks, *fixed_prompts]
