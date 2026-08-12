import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from main import app
from services.ai_call_logger import (
    ai_call_usage_detail_for_task,
    ai_call_usage_for_task,
    estimate_cost,
    tracked_llm_provider,
)
from services.campus_digest_generation import CampusEventEmbedder
from services.database import connect
from services.llm_provider import LLMMessage, LLMResponse, LLMUsage


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def chat(self, messages, *, temperature=0.2, response_format=None):
        return LLMResponse(
            content="完成",
            provider=self.name,
            model=self.model,
            usage=LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
            finish_reason="stop",
        )


def test_tracked_provider_records_report_usage_and_daily_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    observed_records = []
    provider = tracked_llm_provider(
        FakeProvider(),
        call_type="campus_report",
        task_id="report:test",
        callback=observed_records.append,
    )

    response = provider.chat([LLMMessage(role="user", content="生成报告")])

    assert response.content == "完成"
    assert len(observed_records) == 1
    assert observed_records[0].provider == "fake"
    assert observed_records[0].model == "fake-model"
    assert observed_records[0].input_chars == len("生成报告")
    assert observed_records[0].output_chars == len("完成")
    assert observed_records[0].finish_reason == "stop"
    with connect() as connection:
        stored = connection.execute(
            "SELECT finish_reason FROM ai_calls WHERE task_id=?",
            ("report:test",),
        ).fetchone()
    assert stored["finish_reason"] == "stop"
    assert ai_call_usage_for_task("report:test") == {
        "call_count": 1,
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "unreported_count": 0,
    }
    assert ai_call_usage_detail_for_task("report:test") == {
        "call_count": 1,
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "estimated_cost": 0.0,
        "unreported_count": 0,
    }
    summary_response = TestClient(app).get("/api/ai-calls/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["call_count"] == 1
    assert summary["prompt_tokens"] == 12
    assert summary["completion_tokens"] == 8
    assert summary["total_tokens"] == 20
    assert summary["by_type"] == [{
        "call_type": "campus_report",
        "call_count": 1,
        "total_tokens": 20,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "unreported_count": 0,
    }]
    assert summary["by_model"] == [{
        "provider": "fake",
        "model": "fake-model",
        "call_count": 1,
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "estimated_cost": 0,
        "unreported_count": 0,
    }]


def test_deepseek_peak_multiplier_defaults_to_base_price_until_enabled(monkeypatch):
    monkeypatch.setattr(
        settings,
        "deepseek_pricing",
        {"deepseek-v4-flash": {"input_cache_hit": 0.02, "input_cache_miss": 1, "output": 2}},
    )
    peak_billed_at = "2026-07-24T07:47:11+00:00"  # 15:47 Beijing time

    monkeypatch.setattr(settings, "deepseek_peak_pricing_multiplier", 1.0)
    assert estimate_cost(
        1_000_000,
        1_000_000,
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_cache_miss_tokens=1_000_000,
        billed_at=peak_billed_at,
    ) == 3.0

    monkeypatch.setattr(settings, "deepseek_peak_pricing_multiplier", 2.0)
    assert estimate_cost(
        1_000_000,
        1_000_000,
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_cache_miss_tokens=1_000_000,
        billed_at=peak_billed_at,
    ) == 6.0


def test_non_deepseek_provider_never_uses_deepseek_price_card(monkeypatch):
    monkeypatch.setattr(
        settings,
        "deepseek_pricing",
        {"shared-model": {"input_cache_hit": 1, "input_cache_miss": 2, "output": 3}},
    )
    monkeypatch.setattr(settings, "llm_input_cost_per_million_tokens", 0.0)
    monkeypatch.setattr(settings, "llm_output_cost_per_million_tokens", 0.0)
    assert estimate_cost(
        1_000_000,
        1_000_000,
        provider="qwen",
        model="shared-model",
    ) is None


def test_campus_embedding_api_is_not_called_while_the_feature_is_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setattr(settings, "campus_embedding_api_model", "text-embedding-v4")

    vectors, model = CampusEventEmbedder().encode(
        ["校园报告材料"],
        tracking_task_id="report:embedding",
    )

    assert model == "hash-char-ngram-v1"
    assert len(vectors) == 1
    assert ai_call_usage_for_task("report:embedding") == {
        "call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "unreported_count": 0,
    }
