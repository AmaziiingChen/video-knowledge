"""Fact-card extraction, retrying, chunking, and cache coordination for campus digests."""
from __future__ import annotations

import json
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Protocol

from services.ai_call_logger import tracked_llm_provider
from services.campus_digest_fact_cache import load_cached_facts, save_fact_cards
from services.campus_digest_identity import source_hash
from services.campus_digest_payloads import parse_fact_card as parse_fact_card_payload
from services.campus_digest_payloads import split_text_in_order
from services.campus_digest_progress import DigestProgressCallback, emit_progress
from services.llm_provider import LLMProvider, default_llm_provider


class FactCardSource(Protocol):
    content_item_id: str
    title: str
    source_url: str
    published_at: str
    publisher: str
    source_channel: str
    source_section: str
    material: str


class ChatJson(Protocol):
    def __call__(
        self,
        provider: LLMProvider,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float,
    ) -> str: ...


@dataclass(frozen=True)
class FactCardSettings:
    prompt_version: str
    source_chunk_chars: int
    workers: int
    schema: str
    system_prompt: Callable[[], str]
    categories: Collection[str]
    content_decisions: Collection[str]
    document_types: Collection[str]
    event_stages: Collection[str]
    include_decisions: Collection[str]


def parse_fact_card(raw: str | dict[str, Any], *, settings: FactCardSettings) -> dict[str, Any]:
    return parse_fact_card_payload(
        raw,
        categories=settings.categories,
        content_decisions=settings.content_decisions,
        document_types=settings.document_types,
        event_stages=settings.event_stages,
        include_decisions=settings.include_decisions,
    )


def prepare_fact_cards(
    sources: list[FactCardSource],
    *,
    provider: LLMProvider | None,
    use_cache: bool,
    progress_callback: DigestProgressCallback | None,
    tracking_task_id: str | None,
    settings: FactCardSettings,
    chat_json: ChatJson,
) -> list[dict[str, Any]]:
    hashes = {source.content_item_id: source_hash(source.material) for source in sources}
    model_name = provider.model if provider is not None else "deepseek-v4-flash"
    cached = (
        load_cached_facts(
            sources,
            hashes,
            model_name,
            prompt_version=settings.prompt_version,
            parse_card=lambda raw: parse_fact_card(raw, settings=settings),
        )
        if use_cache
        else {}
    )
    cards = dict(cached)
    missing = [source for source in sources if source.content_item_id not in cards]
    emit_progress(
        progress_callback,
        "report_facts",
        f"事实卡缓存命中 {len(cached)} 篇，待分析 {len(missing)} 篇",
        8,
    )

    def extract(source: FactCardSource) -> tuple[FactCardSource, dict[str, Any], str]:
        last_error: Exception | None = None
        for attempt in range(2):
            base_worker = provider or default_llm_provider("deepseek-v4-flash:enabled")
            worker = tracked_llm_provider(
                base_worker,
                call_type="campus_report",
                task_id=tracking_task_id,
            ) if tracking_task_id else base_worker
            try:
                return source, _extract_fact_card(source, provider=worker, settings=settings, chat_json=chat_json), worker.model
            # Providers expose heterogeneous transport and response exceptions; both attempts share one retry path.
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == 0:
                    emit_progress(
                        progress_callback,
                        "report_facts",
                        f"《{source.title}》事实提取失败，正在重试：{exc}",
                        8,
                        level="warn",
                    )
        assert last_error is not None
        raise last_error

    failures: list[tuple[str, str]] = []
    completed: list[tuple[FactCardSource, dict[str, Any], str]] = []
    if missing:
        max_workers = 1 if provider is not None else min(settings.workers, len(missing))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="campus-fact-card") as executor:
            futures = {executor.submit(extract, source): source for source in missing}
            for completed_count, future in enumerate(as_completed(futures), start=1):
                source = futures[future]
                try:
                    completed_source, card, used_model = future.result()
                    cards[completed_source.content_item_id] = card
                    completed.append((completed_source, card, used_model))
                    if completed_count == len(missing) or completed_count % 10 == 0:
                        emit_progress(
                            progress_callback,
                            "report_facts",
                            f"事实卡已完成 {len(cached) + completed_count}/{len(sources)}",
                            8 + 27 * completed_count / max(1, len(missing)),
                        )
                # Surface every provider failure as a per-source failure without abandoning other sources.
                except Exception as exc:  # noqa: BLE001
                    failures.append((source.title, str(exc)))
                    emit_progress(
                        progress_callback,
                        "report_facts",
                        f"《{source.title}》事实提取最终失败：{exc}",
                        8 + 27 * completed_count / max(1, len(missing)),
                        level="error",
                    )
    if completed and use_cache:
        save_fact_cards(completed, hashes, prompt_version=settings.prompt_version)
    if failures:
        preview = "、".join(title for title, _ in failures[:3])
        suffix = "等" if len(failures) > 3 else ""
        raise ValueError(f"有 {len(failures)} 篇文章未能完成校园事实提取：{preview}{suffix}")
    return [cards[source.content_item_id] for source in sources]


def _extract_fact_card(
    source: FactCardSource,
    *,
    provider: LLMProvider,
    settings: FactCardSettings,
    chat_json: ChatJson,
) -> dict[str, Any]:
    material = source.material.strip()
    if len(material) <= settings.source_chunk_chars:
        return _extract_fact_card_once(source, material, provider=provider, settings=settings, chat_json=chat_json)
    partial = [
        _extract_fact_card_once(source, chunk, provider=provider, settings=settings, chat_json=chat_json)
        for chunk in split_text_in_order(material, settings.source_chunk_chars)
    ]
    prompt = (
        "将同一篇文章的分段事实卡合并。去重但保留互不重复的正文、OCR和附件事实；"
        "广告决定取最严格结果：全篇广告才 exclude_ad，事实与广告并存则 mixed。不得新增事实。\n\n"
        f"JSON结构：\n{settings.schema}\n\n"
        f"分段事实卡：\n{json.dumps(partial, ensure_ascii=False)}"
    )
    return parse_fact_card(
        chat_json(provider, settings.system_prompt(), prompt, temperature=0.0),
        settings=settings,
    )


def _extract_fact_card_once(
    source: FactCardSource,
    material: str,
    *,
    provider: LLMProvider,
    settings: FactCardSettings,
    chat_json: ChatJson,
) -> dict[str, Any]:
    prompt = (
        "<source_metadata>\n"
        f"标题：{source.title}\n发布来源：{source.publisher}\n来源渠道：{source.source_channel}\n"
        f"来源栏目：{source.source_section}\n发布日期：{source.published_at}\n原文链接：{source.source_url}\n"
        "</source_metadata>\n\n"
        f"<article_material>\n{material}\n</article_material>"
    )
    return parse_fact_card(
        chat_json(provider, settings.system_prompt(), prompt, temperature=0.05),
        settings=settings,
    )
