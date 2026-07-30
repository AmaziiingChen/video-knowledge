from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.llm_settings import (
    llm_settings_status,
    reveal_campus_embedding_api_key,
    reveal_deepseek_api_key,
    set_campus_embedding_enabled,
    save_campus_embedding_settings,
    save_deepseek_settings,
    test_campus_embedding_connection,
    save_llm_settings,
    test_deepseek_connection,
)


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


@router.get("/llm-settings")
async def get_llm_settings():
    return llm_settings_status()


@router.put("/llm-settings")
async def put_llm_settings(req: LlmSettingsRequest):
    return save_llm_settings(
        deepseek_api_key=req.deepseek_api_key,
        deepseek_base_url=req.deepseek_base_url,
        campus_embedding_api_key=req.campus_embedding_api_key,
        campus_embedding_api_base_url=req.campus_embedding_api_base_url,
        campus_embedding_api_model=req.campus_embedding_api_model,
    )


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
    return save_deepseek_settings(
        deepseek_api_key=req.deepseek_api_key,
        deepseek_base_url=req.deepseek_base_url,
        deepseek_pricing=req.deepseek_pricing,
        deepseek_peak_pricing_multiplier=req.deepseek_peak_pricing_multiplier,
    )


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
