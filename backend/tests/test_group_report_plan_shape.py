from services.group_report_plan_shape import (
    describe_report_plan_shape,
    normalize_report_plan_shape,
    parse_report_plan,
)


def test_legacy_planner_shape_normalizes_and_parses_without_pipeline_dependencies():
    normalized, adjustments = normalize_report_plan_shape(
        {
            "report_strategy": "按主题组织",
            "columns": [
                {
                    "heading": "教学安排",
                    "events": [{"primary_source_ids": ["S001", "S002"]}],
                    "brief": "合并相同安排",
                }
            ],
        }
    )

    strategy, sections = parse_report_plan(normalized, {"S001", "S002"})

    assert adjustments == ["将旧字段 columns 转换为 sections", "兼容转换 3 个旧版栏目字段"]
    assert strategy == "按主题组织"
    assert len(sections) == 1
    assert sections[0].title == "教学安排"
    assert sections[0].source_ids == ("S001", "S002")
    assert sections[0].writing_brief == "合并相同安排"


def test_plan_shape_diagnostics_remain_bounded_for_unusable_payloads():
    assert describe_report_plan_shape({"answer": "not a plan"}) == "顶层字段=answer；未找到栏目数组"
    assert describe_report_plan_shape([{"title": "栏目"}]) == "顶层类型=array，元素数=1"
