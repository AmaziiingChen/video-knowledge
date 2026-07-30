#!/usr/bin/env python3
"""Explicitly build the V2 structural index for selected knowledge sources."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.database import initialize_database
from services.knowledge_v2 import clean_source_markdown, estimate_tokens, index_stats, rebuild_documents, source_documents
from services.llm_settings import apply_saved_llm_settings


PILOT_SOURCES = (
    ("wechat", "LaTeX工作室"),
    ("wechat", "腾讯研究院"),
    ("rss", "宝玉的分享"),
)


def _parse_source(value: str) -> tuple[str, str]:
    provider, separator, source_name = value.partition(":")
    if not separator or not provider.strip() or not source_name.strip():
        raise argparse.ArgumentTypeError("来源格式为 provider:来源名称，例如 wechat:LaTeX工作室")
    return provider.strip(), source_name.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=_parse_source, default=[], help="限定一个来源；可重复传入")
    parser.add_argument("--pilot", action="store_true", help="使用已确认的三组试点来源")
    parser.add_argument("--embed", action="store_true", help="在结构化/FTS 构建后调用当前配置的云端 Embedding API")
    parser.add_argument(
        "--free-token-budget",
        type=int,
        help="本次可直接使用的免费 Embedding token 上限；超过会停止并等待人工确认",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        help="最多提交多少个 10 条的请求批次；用于安全地分段续跑长任务",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计将要处理的文档和估算 token，不写入数据库")
    args = parser.parse_args()
    sources = list(args.source)
    if args.pilot:
        sources.extend(PILOT_SOURCES)
    if not sources:
        parser.error("请至少给出一个 --source，或使用 --pilot")
    if args.free_token_budget is not None and not args.embed:
        parser.error("--free-token-budget 仅能和 --embed 一起使用")
    if args.free_token_budget is not None and args.free_token_budget < 0:
        parser.error("--free-token-budget 不能小于 0")
    if args.max_batches is not None and (not args.embed or args.max_batches < 1):
        parser.error("--max-batches 必须和 --embed 一起使用，且至少为 1")
    sources = list(dict.fromkeys(sources))

    # Desktop startup normally does this once. The maintenance CLI must load
    # the same saved, masked credential settings explicitly.
    apply_saved_llm_settings()
    initialize_database()
    documents = source_documents(source_specs=sources)
    preview = {
        "sources": [{"provider": provider, "name": name} for provider, name in sources],
        "document_count": len(documents),
        "source_characters": sum(len(clean_source_markdown(str(document["markdown"]))) for document in documents),
        "estimated_tokens": sum(estimate_tokens(clean_source_markdown(str(document["markdown"]))) for document in documents),
    }
    if args.dry_run:
        preview["dry_run"] = True
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    result = rebuild_documents(
        documents,
        embed=args.embed,
        embedding_token_budget=args.free_token_budget,
        embedding_max_batches=args.max_batches,
    )
    result["sources"] = preview["sources"]
    result["estimated_tokens"] = preview["estimated_tokens"]
    result["index_stats"] = index_stats(source_specs=sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
