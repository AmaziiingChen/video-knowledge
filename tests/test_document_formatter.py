import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.document_formatter import format_document_markdown
from services.llm_provider import LLMResponse
from services.prompt_templates import (
    DEFAULT_DOCUMENT_FORMATTING_PROMPT,
    PromptTemplateRepository,
    _LEGACY_DEFAULT_DOCUMENT_FORMATTING_PROMPT,
    seed_default_prompt_templates,
)
from services.database import connect, initialize_database


class EchoProvider:
    name = "test"
    model = "test-flash"

    def chat(self, messages, *, temperature=0.2, response_format=None):
        source = messages[-1].content.split("<document_markdown>\n", 1)[1].rsplit("\n</document_markdown>", 1)[0]
        return LLMResponse(content=f"```markdown\n{source}\n```", provider=self.name, model=self.model)


def test_document_formatter_seeds_prompt_and_keeps_html_tables(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        template = PromptTemplateRepository(connection).get_active_template("document_formatting")

    assert template is not None
    assert "LaTeX" in template.template
    original = """# 采购公告

## 项目概况

预算金额：1,210,000 元。

<table><tr><td rowspan=\"2\">项目编号</td><td>SZDL2026001206</td></tr><tr><td>2026-07-19</td></tr></table>
"""
    formatted, response = format_document_markdown(
        original,
        title="采购公告",
        template=template,
        provider=EchoProvider(),
    )

    assert response.model == "test-flash"
    assert formatted == original.strip()
    assert 'rowspan="2"' in formatted
    assert "SZDL2026001206" in formatted


def test_document_formatter_rejects_summary_like_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        template = PromptTemplateRepository(connection).get_active_template("document_formatting")

    class SummaryProvider(EchoProvider):
        def chat(self, messages, *, temperature=0.2, response_format=None):
            return LLMResponse(content="这是一份采购公告。", provider=self.name, model=self.model)

    try:
        format_document_markdown(
            "# 采购公告\n\n预算金额 1,210,000 元，项目编号 SZDL2026001206，投标截止时间 2026-07-19。\n" * 5,
            title="采购公告",
            template=template,
            provider=SummaryProvider(),
        )
    except ValueError as exc:
        assert "概括" in str(exc) or "数字" in str(exc)
    else:
        raise AssertionError("summary-like output must not replace OCR source")


def test_unmodified_document_formatting_prompt_receives_math_upgrade(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        template = PromptTemplateRepository(connection).get_active_template("document_formatting")
        connection.execute(
            "UPDATE prompt_templates SET template=? WHERE id=?",
            (_LEGACY_DEFAULT_DOCUMENT_FORMATTING_PROMPT.rstrip(), template.id),
        )
        connection.commit()

    with connect() as connection:
        seed_default_prompt_templates(connection)
        connection.commit()
    with connect() as connection:
        upgraded = PromptTemplateRepository(connection).get_active_template("document_formatting")

    assert upgraded.template == DEFAULT_DOCUMENT_FORMATTING_PROMPT
