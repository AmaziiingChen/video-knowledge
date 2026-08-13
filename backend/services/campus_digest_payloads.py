"""Pure validation for untrusted campus-digest model JSON payloads."""
from __future__ import annotations

import json
import re
from typing import Any, Collection


def parse_fact_card(
    raw: str | dict[str, Any],
    *,
    categories: Collection[str],
    content_decisions: Collection[str],
    document_types: Collection[str],
    event_stages: Collection[str],
    include_decisions: Collection[str],
) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else parse_json_object(raw)
    summary = one_line(data.get("summary"))
    if not summary:
        raise ValueError("事实卡缺少 summary")
    decision = str(data.get("content_decision") or "include").strip()
    if decision not in content_decisions:
        decision = "include"
    category = str(data.get("category") or "其他动态").strip()
    if category not in categories:
        category = "其他动态"
    document_type = str(data.get("document_type") or "other").strip()
    if document_type not in document_types:
        document_type = "other"
    stage = str(data.get("event_stage") or "unknown").strip()
    if stage not in event_stages:
        stage = "unknown"
    normalized: dict[str, Any] = {
        "summary": summary[:600],
        "content_decision": decision,
        "decision_reason": one_line(data.get("decision_reason"))[:300],
        "category": category,
        "document_type": document_type,
        "event_stage": stage,
        "event_or_subject": one_line(data.get("event_or_subject"))[:500],
    }
    list_fields = (
        "issuers",
        "organizers",
        "actors",
        "actions",
        "objects",
        "audiences",
        "time_points",
        "locations",
        "terms_or_batches",
        "identifiers",
        "links",
        "attachments",
        "topics",
        "ad_segments",
        "uncertainties",
    )
    for field_name in list_fields:
        normalized[field_name] = string_list(data.get(field_name), maximum=40)
    facts: list[dict[str, Any]] = []
    raw_facts = data.get("atomic_facts")
    if isinstance(raw_facts, list):
        for raw_fact in raw_facts[:80]:
            if not isinstance(raw_fact, dict):
                continue
            text = one_line(raw_fact.get("text"))
            evidence = one_line(raw_fact.get("evidence"))
            if not text or not evidence:
                continue
            origin = str(raw_fact.get("origin") or "html").strip()
            if origin not in {"html", "image_ocr", "attachment", "metadata"}:
                origin = "html"
            facts.append(
                {
                    "text": text[:800],
                    "evidence": evidence[:800],
                    "origin": origin,
                    "locator": one_line(raw_fact.get("locator"))[:160],
                    "ocr_only": bool(raw_fact.get("ocr_only", origin == "image_ocr")),
                }
            )
    normalized["atomic_facts"] = facts
    if not normalized["decision_reason"]:
        normalized["decision_reason"] = "保留可核验的校园事实" if decision in include_decisions else "没有可用于报告的可靠校园事实"
    return normalized


def parse_event_brief(
    raw: str | dict[str, Any],
    *,
    categories: Collection[str],
) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else parse_json_object(raw)
    title = one_line(data.get("title"))
    summary = one_line(data.get("summary"))
    if not title or not summary:
        raise ValueError("事件摘要缺少标题或摘要")
    category = str(data.get("category") or "其他动态")
    if category not in categories:
        category = "其他动态"
    source_ids = string_list(data.get("source_ids"), maximum=80)
    stages: list[dict[str, Any]] = []
    for stage in data.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        facts: list[dict[str, Any]] = []
        for fact in stage.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            text = one_line(fact.get("text"))
            ids = [value for value in string_list(fact.get("source_ids"), maximum=30) if value in source_ids]
            if text and ids:
                facts.append({"text": text[:800], "source_ids": ids})
        if facts:
            stages.append({"stage": one_line(stage.get("stage")) or "unknown", "facts": facts})
    conflicts: list[dict[str, Any]] = []
    for conflict in data.get("conflicts") or []:
        if isinstance(conflict, str):
            conflicts.append({"text": one_line(conflict), "source_ids": source_ids})
        elif isinstance(conflict, dict):
            text = one_line(conflict.get("text"))
            ids = [value for value in string_list(conflict.get("source_ids"), maximum=30) if value in source_ids]
            if text:
                conflicts.append({"text": text[:800], "source_ids": ids or source_ids})
    return {
        "title": title[:500],
        "category": category,
        "summary": summary[:1000],
        "stages": stages,
        "conflicts": conflicts,
        "source_ids": source_ids,
    }


def parse_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型 JSON 无法解析：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("模型 JSON 顶层必须是对象")
    return data


def string_list(value: Any, *, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(one_line(item)[:800] for item in value if one_line(item)))[:maximum]


def one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_text_in_order(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in str(text or "").splitlines(keepends=True):
        remaining = line
        while remaining:
            space = limit - len(current)
            if space <= 0:
                chunks.append(current.strip())
                current = ""
                space = limit
            current += remaining[:space]
            remaining = remaining[space:]
    if current.strip():
        chunks.append(current.strip())
    return chunks
