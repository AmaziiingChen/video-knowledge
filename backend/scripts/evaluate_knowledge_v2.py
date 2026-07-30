#!/usr/bin/env python3
"""Developer-only retrieval evaluation for human-authored knowledge evidence sets.

Example fixture item:
{
  "id": "latex-001",
  "question": "...",
  "sources": [{"provider": "wechat", "name": "LaTeX工作室"}],
  "expected_content_item_ids": ["the human-verified source item id"]
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.database import initialize_database
from services.knowledge_v2 import retrieve
from services.llm_settings import apply_saved_llm_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="人工标注的 JSON 问题集")
    parser.add_argument("--output", type=Path, help="可选：写入完整评估结果 JSON")
    args = parser.parse_args()

    try:
        cases = json.loads(args.fixture.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"无法读取问题集：{exc}")
    if not isinstance(cases, list) or not cases:
        parser.error("问题集必须是非空 JSON 数组")

    apply_saved_llm_settings()
    initialize_database()
    results: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, dict):
            parser.error("每条问题必须是 JSON 对象")
        expected = {str(item) for item in case.get("expected_content_item_ids", []) if str(item)}
        sources = case.get("sources")
        if not isinstance(sources, list) or not expected:
            parser.error("每条问题都必须提供 sources 和 expected_content_item_ids")
        specs = [(str(item.get("provider") or ""), str(item.get("name") or "")) for item in sources if isinstance(item, dict)]
        try:
            retrieved = retrieve(str(case.get("question") or ""), source_specs=specs)
            actual = [item.content_item_id for item in retrieved]
            matched = expected.intersection(actual)
            allowed_sources = set(specs)
            results.append(
                {
                    "id": str(case.get("id") or ""),
                    "question": str(case.get("question") or ""),
                    "expected_content_item_ids": sorted(expected),
                    "retrieved_content_item_ids": actual,
                    "evidence_recall_at_10": len(matched) / len(expected),
                    "scope_valid": all((item.source_provider, item.source_name) in allowed_sources for item in retrieved),
                    "error": "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": str(case.get("id") or ""),
                    "question": str(case.get("question") or ""),
                    "expected_content_item_ids": sorted(expected),
                    "retrieved_content_item_ids": [],
                    "evidence_recall_at_10": 0.0,
                    "scope_valid": False,
                    "error": str(exc),
                }
            )
    successful = [item for item in results if not item["error"]]
    summary = {
        "case_count": len(results),
        "successful_case_count": len(successful),
        "evidence_recall_at_10": sum(float(item["evidence_recall_at_10"]) for item in results) / len(results),
        "scope_valid_rate": sum(bool(item["scope_valid"]) for item in results) / len(results),
        "results": results,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if len(successful) == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
