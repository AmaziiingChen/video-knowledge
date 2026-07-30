from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

from services.database import connect, initialize_database, utc_now_iso
from services.repository import new_id


def list_filter_rules(subscription_id: str | None = None) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        query = "SELECT * FROM wechat_content_filter_rules"
        params: tuple[Any, ...] = ()
        if subscription_id:
            query += " WHERE subscription_id IS NULL OR subscription_id = ?"
            params = (subscription_id,)
        rows = connection.execute(query + " ORDER BY priority DESC, created_at ASC", params).fetchall()
    return [_rule_from_row(row) for row in rows]


def create_filter_rule(*, name: str, selectors: list[str], text_patterns: list[str], priority: int = 0, subscription_id: str | None = None, enabled: bool = True) -> dict[str, Any]:
    _validate_rule(selectors, text_patterns)
    initialize_database()
    rule_id, now = new_id(), utc_now_iso()
    with connect() as connection:
        if subscription_id and not connection.execute("SELECT 1 FROM wechat_subscriptions WHERE id = ?", (subscription_id,)).fetchone():
            raise LookupError("公众号订阅不存在")
        connection.execute("""INSERT INTO wechat_content_filter_rules (id, subscription_id, name, priority, enabled, selectors_json, text_patterns_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (rule_id, subscription_id, name.strip(), priority, int(enabled), json.dumps(selectors), json.dumps(text_patterns), now, now))
        connection.commit()
    return get_filter_rule(rule_id)


def get_filter_rule(rule_id: str) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT * FROM wechat_content_filter_rules WHERE id = ?", (rule_id,)).fetchone()
    if not row:
        raise LookupError("内容清洗规则不存在")
    return _rule_from_row(row)


def delete_filter_rule(rule_id: str) -> None:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM wechat_content_filter_rules WHERE id = ?", (rule_id,))
        connection.commit()
    if not cursor.rowcount:
        raise LookupError("内容清洗规则不存在")


def apply_filters(content: BeautifulSoup, source_url: str) -> None:
    """Apply global rules then rules of the subscription that discovered this URL."""
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT subscription_id FROM wechat_subscription_items WHERE source_url = ? ORDER BY discovered_at DESC LIMIT 1", (source_url,)).fetchone()
    subscription_id = str(row["subscription_id"]) if row else None
    for rule in list_filter_rules(subscription_id):
        if not rule["enabled"]:
            continue
        for selector in rule["selectors"]:
            for node in content.select(selector):
                node.decompose()
        for pattern in rule["text_patterns"]:
            compiled = re.compile(pattern)
            for text in list(content.find_all(string=compiled)):
                text.extract()


def _validate_rule(selectors: list[str], text_patterns: list[str]) -> None:
    if len(selectors) > 30 or len(text_patterns) > 30:
        raise ValueError("单条规则最多包含 30 个选择器和 30 个正则")
    probe = BeautifulSoup("<div></div>", "lxml")
    for selector in selectors:
        if not isinstance(selector, str) or not selector.strip() or len(selector) > 300:
            raise ValueError("CSS 选择器不能为空且不能超过 300 字符")
        try:
            probe.select(selector)
        except SelectorSyntaxError as exc:
            raise ValueError(f"无效的 CSS 选择器: {selector}") from exc
    for pattern in text_patterns:
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 300:
            raise ValueError("文本正则不能为空且不能超过 300 字符")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"无效的文本正则: {pattern}") from exc


def _rule_from_row(row: Any) -> dict[str, Any]:
    value = dict(row)
    value["enabled"] = bool(value["enabled"])
    value["selectors"] = json.loads(value.pop("selectors_json"))
    value["text_patterns"] = json.loads(value.pop("text_patterns_json"))
    return value
