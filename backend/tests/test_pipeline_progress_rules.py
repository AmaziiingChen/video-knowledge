from services.pipeline_progress_rules import clamp_percent, level_from_message


def test_pipeline_progress_rules_bound_progress_and_classify_messages():
    assert clamp_percent(-1) == 0.0
    assert clamp_percent(12.36) == 12.4
    assert clamp_percent(101) == 100.0
    assert level_from_message("下载失败") == "error"
    assert level_from_message("注意网络状态") == "warn"
    assert level_from_message("任务完成") == "success"
    assert level_from_message("开始下载") == "info"
