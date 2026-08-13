from services.creator_capture_status import (
    begin_creator_browser_capture,
    creator_capture_status,
    finish_creator_browser_capture,
    record_creator_list_check,
    set_creator_capture_stage,
    wait_for_creator_browser,
)


def test_creator_capture_status_tracks_browser_lifecycle_without_leaking_mutable_state():
    finish_creator_browser_capture()
    wait_for_creator_browser("douyin")
    assert creator_capture_status()["stage"] == "等待内置浏览器"

    begin_creator_browser_capture("douyin")
    set_creator_capture_stage("读取创作者页面")
    record_creator_list_check("douyin", state="valid", detail="x" * 400)
    snapshot = creator_capture_status()
    snapshot["last_list_checks"]["douyin"]["detail"] = "mutated"

    assert creator_capture_status()["last_list_checks"]["douyin"]["detail"] == "x" * 300
    finish_creator_browser_capture()
    assert creator_capture_status()["stage"] == "空闲"
