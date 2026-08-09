from services.campus_document_rendering import (
    render_document_markdown_html,
    text_to_article_html,
)


def test_document_renderer_marks_math_and_promotes_table_headers():
    source = """# 采购清单

$ x_1 = 2 $

<table><tr><td>项目</td><td>数量</td></tr><tr><td>设备</td><td>1</td></tr></table>
"""

    rendered = render_document_markdown_html(source)

    assert rendered.startswith('<article class="procurement-pdf-content">')
    assert 'class="article-math"' in rendered
    assert 'data-latex="x_1 = 2"' in rendered
    assert '<th scope="col">项目</th>' in rendered
    assert text_to_article_html(source) == rendered
