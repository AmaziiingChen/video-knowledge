"""V2 knowledge-set question answering endpoints."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from services.knowledge_conversations import conversation_detail, finish_exchange, list_conversations, start_exchange
from services.knowledge_v2 import answer_from_evidence, evidence_preview, list_source_set_documents, list_source_sets, retrieve as retrieve_v2, rewrite_query, stream_answer_from_evidence, validate_source_document_ids


router = APIRouter()


class V2SourceScope(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)


class V2QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Keep the plural field name for wire compatibility with already-saved V2
    # conversations, while V1 deliberately supports one knowledge set per ask.
    sources: list[V2SourceScope] = Field(min_length=1, max_length=1)
    document_ids: list[str] | None = Field(default=None, max_length=500)
    excluded_document_ids: list[str] | None = Field(default=None, max_length=500)
    conversation_id: str | None = Field(default=None, max_length=100)
    answer_model: Literal['deepseek-v4-flash', 'deepseek-v4-pro'] = 'deepseek-v4-pro'


@router.get('/knowledge/v2/source-sets')
def v2_source_sets():
    return {'items': list_source_sets()}


@router.get('/knowledge/v2/source-documents')
def v2_source_documents(provider: str, name: str, limit: int = 200, offset: int = 0):
    try:
        return list_source_set_documents(provider, name, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/knowledge/conversations')
def conversations():
    return list_conversations()


@router.get('/knowledge/conversations/{conversation_id}')
def conversation(conversation_id: str):
    try:
        return conversation_detail(conversation_id)
    except LookupError as exc:
        raise HTTPException(404, '知识库对话不存在') from exc


@router.get('/knowledge/v2/evidence/{chunk_id}')
def v2_evidence(chunk_id: str):
    try:
        return evidence_preview(chunk_id)
    except LookupError as exc:
        raise HTTPException(404, '引用证据不存在或原文已删除') from exc


@router.post('/knowledge/v2/query')
def v2_query(req: V2QueryRequest):
    source = req.sources[0]
    specs = [(source.provider.strip(), source.name.strip())]
    try:
        document_ids = validate_source_document_ids(specs[0][0], specs[0][1], req.document_ids)
        excluded_document_ids = validate_source_document_ids(specs[0][0], specs[0][1], req.excluded_document_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if set(document_ids).intersection(excluded_document_ids):
        raise HTTPException(422, '文章不能同时被选中和排除')
    scope = {'version': 'v2', 'sources': [{'provider': provider, 'name': name} for provider, name in specs]}
    if document_ids:
        scope['document_ids'] = document_ids
    if excluded_document_ids:
        scope['excluded_document_ids'] = excluded_document_ids
    conversation_context: list[dict[str, object]] = []
    if req.conversation_id:
        try:
            existing = conversation_detail(req.conversation_id)
        except LookupError as exc:
            raise HTTPException(404, '知识库对话不存在') from exc
        if existing.get('scope') != scope:
            raise HTTPException(409, '知识集范围已变更，请开启新对话')
        messages = existing.get('messages')
        if isinstance(messages, list):
            conversation_context = [item for item in messages if isinstance(item, dict)]
    # The conversation ID is also the durable AI-call tracking key.  Create it
    # before query rewriting so every billable model stage belongs to this
    # conversation, including a query that later has no usable evidence.
    exchange = start_exchange(question=req.question, scope=scope, conversation_id=req.conversation_id)
    try:
        search_query = rewrite_query(
            req.question,
            conversation_context=conversation_context,
            task_id=str(exchange['id']),
        )
        results = retrieve_v2(
            search_query,
            source_specs=specs,
            content_item_ids=document_ids,
            excluded_content_item_ids=excluded_document_ids,
        )
    except ValueError as exc:
        finish_exchange(str(exchange['id']), answer='', citations=[], error=str(exc))
        raise HTTPException(409, str(exc)) from exc

    try:
        answer = answer_from_evidence(
            req.question,
            results,
            conversation_context=conversation_context,
            task_id=str(exchange['id']),
            model=req.answer_model,
        )
        completed = finish_exchange(str(exchange['id']), answer=answer.answer, citations=answer.citations)
        return {
            'conversation_id': exchange['id'],
            'answer': answer.answer,
            'citations': answer.citations,
            'insufficient_evidence': answer.insufficient_evidence,
            'search_query': search_query,
            'usage': completed.get('usage', {}),
        }
    except ValueError as exc:
        finish_exchange(str(exchange['id']), answer='', citations=[], error=str(exc))
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        finish_exchange(str(exchange['id']), answer='', citations=[], error=str(exc))
        raise HTTPException(502, f'知识库回答失败：{exc}') from exc


@router.post('/knowledge/v2/query/stream')
def v2_query_stream(req: V2QueryRequest):
    """Stream a grounded answer while retaining the same conversation contract."""
    source = req.sources[0]
    specs = [(source.provider.strip(), source.name.strip())]
    try:
        document_ids = validate_source_document_ids(specs[0][0], specs[0][1], req.document_ids)
        excluded_document_ids = validate_source_document_ids(specs[0][0], specs[0][1], req.excluded_document_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if set(document_ids).intersection(excluded_document_ids):
        raise HTTPException(422, '文章不能同时被选中和排除')
    scope = {'version': 'v2', 'sources': [{'provider': provider, 'name': name} for provider, name in specs]}
    if document_ids:
        scope['document_ids'] = document_ids
    if excluded_document_ids:
        scope['excluded_document_ids'] = excluded_document_ids
    conversation_context: list[dict[str, object]] = []
    if req.conversation_id:
        try:
            existing = conversation_detail(req.conversation_id)
        except LookupError as exc:
            raise HTTPException(404, '知识库对话不存在') from exc
        if existing.get('scope') != scope:
            raise HTTPException(409, '知识集范围已变更，请开启新对话')
        messages = existing.get('messages')
        if isinstance(messages, list):
            conversation_context = [item for item in messages if isinstance(item, dict)]
    exchange = start_exchange(question=req.question, scope=scope, conversation_id=req.conversation_id)
    try:
        search_query = rewrite_query(
            req.question,
            conversation_context=conversation_context,
            task_id=str(exchange['id']),
        )
        results = retrieve_v2(
            search_query,
            source_specs=specs,
            content_item_ids=document_ids,
            excluded_content_item_ids=excluded_document_ids,
        )
    except ValueError as exc:
        finish_exchange(str(exchange['id']), answer='', citations=[], error=str(exc))
        raise HTTPException(409, str(exc)) from exc

    def event_stream():
        try:
            for event, payload in stream_answer_from_evidence(
                req.question,
                results,
                conversation_context=conversation_context,
                task_id=str(exchange['id']),
                model=req.answer_model,
            ):
                if event == 'delta':
                    yield _sse('delta', {'text': payload})
                elif event == 'replace':
                    yield _sse('replace', {'text': payload})
                elif event == 'done':
                    answer = payload
                    completed = finish_exchange(str(exchange['id']), answer=answer.answer, citations=answer.citations)
                    yield _sse('done', {
                        'conversation_id': exchange['id'],
                        'answer': answer.answer,
                        'citations': answer.citations,
                        'insufficient_evidence': answer.insufficient_evidence,
                        'search_query': search_query,
                        'usage': completed.get('usage', {}),
                    })
        except Exception as exc:
            finish_exchange(str(exchange['id']), answer='', citations=[], error=str(exc))
            yield _sse('error', {'error': str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'},
    )


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
