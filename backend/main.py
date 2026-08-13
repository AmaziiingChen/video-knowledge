import hmac
import importlib.util
import os
import re
from contextlib import asynccontextmanager

from config import settings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from router_registry import register_api_routers
from services.application_lifecycle import start_application, stop_application
from services.llm_provider import deepseek_model_option_value
from services.llm_settings import (
    available_text_model_options,
    default_text_model_selection,
    text_model_configured,
)
from services.mcp_bridge_security import (
    MCP_TOKEN_ENV,
    MCP_TOKEN_HEADER,
    is_mcp_api_request_allowed,
    mcp_bridge_lease_is_valid,
)
from services.pipeline_runner import ASR_MODEL_STRATEGIES, WHISPER_MODELS
from services.runtime_components import supported_asr_backends
from services.task_manager import TaskPersistenceError


@asynccontextmanager
async def application_lifespan(_app: FastAPI):
    await start_application()
    try:
        yield
    finally:
        await stop_application()


app = FastAPI(title="KnowledgeHub Pipeline", version="0.1.4", lifespan=application_lifespan)


@app.exception_handler(TaskPersistenceError)
async def task_persistence_error_handler(_request, _exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "本地任务队列暂时不可写，请稍后重试"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_allowed_local_origin(request: Request) -> bool:
    """Accept only the desktop shell or loopback source UI as browser callers."""
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        # Non-browser callers still need the private instance token below.
        return True
    allowed_origins = {value.rstrip("/") for value in settings.allowed_origins}
    return origin in allowed_origins or bool(re.fullmatch(settings.allowed_origin_regex, origin))


def _allows_unauthenticated_test_api() -> bool:
    return os.environ.get("KNOWLEDGEHUB_ALLOW_UNAUTHENTICATED_LOCAL_API", "").strip().lower() in {"1", "true", "yes"}


@app.middleware("http")
async def require_desktop_instance_token(request: Request, call_next):
    """Bind private local API access to the launching desktop or source-session token."""
    expected_token = os.environ.get("KNOWLEDGEHUB_INSTANCE_TOKEN", "").strip()
    is_health_check = request.url.path == "/api/health"
    is_preflight = request.method.upper() == "OPTIONS"
    if request.url.path.startswith("/api/") and not is_health_check and not is_preflight:
        received_mcp_token = request.headers.get(MCP_TOKEN_HEADER, "")
        if received_mcp_token:
            expected_mcp_token = os.environ.get(MCP_TOKEN_ENV, "").strip()
            if request.headers.get("origin", ""):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "MCP capability 不接受浏览器来源请求"},
                )
            if not expected_mcp_token or not hmac.compare_digest(received_mcp_token, expected_mcp_token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "KnowledgeHub MCP 请求未获授权"},
                )
            if not is_mcp_api_request_allowed(request.method, request.url.path):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "KnowledgeHub MCP capability 不允许访问此 API"},
                )
            if not mcp_bridge_lease_is_valid():
                return JSONResponse(
                    status_code=403,
                    content={"detail": "KnowledgeHub MCP 会话已失效，请重新启动应用"},
                )
            return await call_next(request)
        if not _is_allowed_local_origin(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "本机 API 仅接受 KnowledgeHub 页面发起的请求"},
            )
        if not expected_token and not _allows_unauthenticated_test_api():
            return JSONResponse(
                status_code=503,
                content={"detail": "本机 API 尚未配置实例访问令牌"},
            )
        received_token = request.headers.get("x-knowledgehub-token", "")
        if expected_token and not hmac.compare_digest(received_token, expected_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "本机 API 请求未获桌面应用授权"},
            )
    return await call_next(request)

register_api_routers(app)

@app.get("/api/health")
async def health(request: Request):
    expected_token = os.environ.get("KNOWLEDGEHUB_INSTANCE_TOKEN", "").strip()
    supplied_token = request.headers.get("x-knowledgehub-token", "")
    # Do not disclose the launch capability to an arbitrary loopback client.
    # The Electron parent already owns it and supplies it when checking that
    # port 8000 belongs to this exact backend process.
    instance_token = (
        expected_token
        if expected_token and hmac.compare_digest(supplied_token, expected_token)
        else ""
    )
    return {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": settings.app_version,
        "instance_token": instance_token,
    }

@app.get("/api/config")
async def get_config():
    return {
        "deepseek_configured": bool(settings.deepseek_api_key),
        "deepseek_model": settings.deepseek_model,
        "deepseek_model_option": deepseek_model_option_value(settings.deepseek_model),
        "text_model_configured": text_model_configured(),
        "default_ai_model": default_text_model_selection(),
        "available_ai_models": available_text_model_options(),
        "whisper_model": settings.whisper_model,
        "available_whisper_models": sorted(WHISPER_MODELS),
        "asr_backend": settings.asr_backend,
        "asr_model_strategy": settings.asr_model_strategy,
        "asr_short_video_model": settings.asr_short_video_model,
        "asr_long_video_model": settings.asr_long_video_model,
        "asr_beam_size": settings.asr_beam_size,
        "asr_vad_filter": settings.asr_vad_filter,
        "asr_fallback_enabled": settings.asr_fallback_enabled,
        "available_asr_backends": supported_asr_backends(),
        "available_asr_model_strategies": sorted(ASR_MODEL_STRATEGIES),
        "mlx_whisper_available": importlib.util.find_spec("mlx_whisper") is not None,
        "miniprogram_forum_capture_enabled": settings.miniprogram_forum_capture_enabled,
    }
