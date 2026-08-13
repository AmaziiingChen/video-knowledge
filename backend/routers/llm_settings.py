from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from services.llm_settings import (
    available_text_model_options,
    delete_text_provider,
    discover_text_provider_models,
    llm_settings_status,
    reveal_campus_embedding_api_key,
    reveal_deepseek_api_key,
    reveal_text_provider_api_key,
    save_campus_embedding_settings,
    save_deepseek_settings,
    save_default_text_model,
    save_llm_settings,
    save_text_provider,
    set_campus_embedding_enabled,
    test_campus_embedding_connection,
    test_deepseek_connection,
    test_text_provider_connection,
    text_provider_profiles,
)
from services.text_model_secrets import TextModelSecretError

router = APIRouter()


class LlmSettingsRequest(BaseModel):
    deepseek_api_key: str = Field(default="", max_length=500)
    deepseek_base_url: str = Field(default="https://api.deepseek.com", max_length=500)
    campus_embedding_api_key: str = Field(default="", max_length=500)
    campus_embedding_api_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1", max_length=500
    )
    campus_embedding_api_model: str = Field(default="qwen3.7-text-embedding", max_length=160)


class DeepSeekSettingsRequest(BaseModel):
    deepseek_api_key: str | None = Field(default=None, max_length=500)
    deepseek_base_url: str = Field(default="https://api.deepseek.com", max_length=500)
    deepseek_pricing: dict[str, dict[str, float]] | None = None
    deepseek_peak_pricing_multiplier: float | None = Field(default=None, ge=0, le=100)


class DeepSeekConnectionTestRequest(BaseModel):
    deepseek_api_key: str | None = Field(default=None, max_length=500)
    deepseek_base_url: str | None = Field(default=None, max_length=500)


class CampusEmbeddingSettingsRequest(BaseModel):
    campus_embedding_api_key: str | None = Field(default=None, max_length=500)
    campus_embedding_api_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1", max_length=500
    )
    campus_embedding_api_model: str = Field(default="qwen3.7-text-embedding", max_length=160)


class CampusEmbeddingConnectionTestRequest(BaseModel):
    campus_embedding_api_key: str | None = Field(default=None, max_length=500)
    campus_embedding_api_base_url: str | None = Field(default=None, max_length=500)
    campus_embedding_api_model: str | None = Field(default=None, max_length=160)


class CampusEmbeddingToggleRequest(BaseModel):
    enabled: bool


class TextProviderRequest(BaseModel):
    type: Literal["deepseek", "qwen", "mimo", "custom"] = "custom"
    label: str = Field(..., min_length=1, max_length=80)
    base_url: str = Field(..., min_length=1, max_length=500)
    models: list[str] = Field(default_factory=list, max_length=40)
    thinking_parameter: Literal["thinking", "enable_thinking", "none"] = "none"
    send_temperature: bool | None = None
    stream_options: bool | None = None
    response_format: bool | None = None
    api_key: str | None = Field(default=None, max_length=500)


class TextProviderConnectionRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=160)


class TextProviderDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=500)


class DefaultTextModelRequest(BaseModel):
    selection: str = Field(..., min_length=1, max_length=220)


@router.get("/llm-settings")
async def get_llm_settings():
    return llm_settings_status()


@router.get("/llm-settings/text-providers")
async def get_text_providers():
    return {
        "providers": text_provider_profiles(),
        "model_options": available_text_model_options(),
    }


@router.put("/llm-settings/default-text-model")
async def put_default_text_model(req: DefaultTextModelRequest):
    try:
        return save_default_text_model(req.selection)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/llm-settings/text-providers/{provider_id}")
async def put_text_provider(provider_id: str, req: TextProviderRequest):
    try:
        return save_text_provider(
            provider_id=provider_id,
            provider_type=req.type,
            label=req.label,
            base_url=req.base_url,
            models=req.models,
            thinking_parameter=req.thinking_parameter,
            send_temperature=req.send_temperature,
            stream_options=req.stream_options,
            response_format=req.response_format,
            api_key=req.api_key,
        )
    except (TextModelSecretError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/llm-settings/text-providers/{provider_id}", status_code=204)
async def remove_text_provider(provider_id: str):
    try:
        delete_text_provider(provider_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TextModelSecretError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/llm-settings/text-providers/{provider_id}/test")
def post_text_provider_connection_test(provider_id: str, req: TextProviderConnectionRequest):
    try:
        return test_text_provider_connection(provider_id, api_key=req.api_key, model=req.model)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"文本模型连接失败：{exc}") from exc


@router.post("/llm-settings/text-providers/{provider_id}/models")
def post_text_provider_model_discovery(provider_id: str, req: TextProviderDiscoveryRequest):
    try:
        return discover_text_provider_models(provider_id, api_key=req.api_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm-settings/text-providers/{provider_id}/reveal")
async def post_reveal_text_provider_api_key(provider_id: str):
    try:
        return {"secret": reveal_text_provider_api_key(provider_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/llm-settings")
async def put_llm_settings(req: LlmSettingsRequest):
    try:
        return save_llm_settings(
            deepseek_api_key=req.deepseek_api_key,
            deepseek_base_url=req.deepseek_base_url,
            campus_embedding_api_key=req.campus_embedding_api_key,
            campus_embedding_api_base_url=req.campus_embedding_api_base_url,
            campus_embedding_api_model=req.campus_embedding_api_model,
        )
    except (TextModelSecretError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm-settings/campus-embedding/test")
def post_campus_embedding_connection_test(req: CampusEmbeddingConnectionTestRequest):
    try:
        return test_campus_embedding_connection(
            campus_embedding_api_key=req.campus_embedding_api_key,
            campus_embedding_api_base_url=req.campus_embedding_api_base_url,
            campus_embedding_api_model=req.campus_embedding_api_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Embedding 连接失败：{exc}") from exc


@router.put("/llm-settings/deepseek")
async def put_deepseek_settings(req: DeepSeekSettingsRequest):
    try:
        return save_deepseek_settings(
            deepseek_api_key=req.deepseek_api_key,
            deepseek_base_url=req.deepseek_base_url,
            deepseek_pricing=req.deepseek_pricing,
            deepseek_peak_pricing_multiplier=req.deepseek_peak_pricing_multiplier,
        )
    except (TextModelSecretError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm-settings/deepseek/test")
def post_deepseek_connection_test(req: DeepSeekConnectionTestRequest):
    try:
        return test_deepseek_connection(
            deepseek_api_key=req.deepseek_api_key,
            deepseek_base_url=req.deepseek_base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek 连接失败：{exc}") from exc


@router.post("/llm-settings/deepseek/reveal")
async def post_reveal_deepseek_api_key():
    return {"secret": reveal_deepseek_api_key()}


@router.put("/llm-settings/campus-embedding")
async def put_campus_embedding_settings(req: CampusEmbeddingSettingsRequest):
    return save_campus_embedding_settings(
        campus_embedding_api_key=req.campus_embedding_api_key,
        campus_embedding_api_base_url=req.campus_embedding_api_base_url,
        campus_embedding_api_model=req.campus_embedding_api_model,
    )


@router.post("/llm-settings/campus-embedding/reveal")
async def post_reveal_campus_embedding_api_key():
    return {"secret": reveal_campus_embedding_api_key()}


@router.put("/llm-settings/campus-embedding/enabled")
async def put_campus_embedding_enabled(req: CampusEmbeddingToggleRequest):
    return set_campus_embedding_enabled(req.enabled)
