from services.content_preview_models import ArticlePreviewResponse


def test_article_preview_response_owns_independent_collection_defaults():
    first = ArticlePreviewResponse(content_item_id="one", title="标题", html="<p>正文</p>")
    second = ArticlePreviewResponse(content_item_id="two", title="标题", html="<p>正文</p>")
    first.tags.append("校园")

    assert first.formatting_status == "not_applicable"
    assert second.tags == []
