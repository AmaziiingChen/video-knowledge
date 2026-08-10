from services import pipeline_runner


def test_pipeline_ocr_refresh_rejects_non_mapping_legacy_payloads():
    assert pipeline_runner._wechat_article_needs_ocr_refresh(None) is False
    assert pipeline_runner._wechat_article_needs_ocr_refresh([]) is False


def test_pipeline_ocr_refresh_delegates_mapping_payloads_to_the_canonical_policy(monkeypatch):
    payload = {"images": ["https://example.test/image.jpg"]}
    seen = []
    monkeypatch.setattr(
        pipeline_runner,
        "_content_source_text_needs_ocr_refresh",
        lambda value: seen.append(value) or True,
    )

    assert pipeline_runner._wechat_article_needs_ocr_refresh(payload) is True
    assert seen == [payload]
