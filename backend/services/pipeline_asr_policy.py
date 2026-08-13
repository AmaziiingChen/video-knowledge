"""Configuration policy for automatic speech recognition in the pipeline."""

from __future__ import annotations

from config import settings

WHISPER_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
ASR_MODEL_STRATEGIES = {"smart", "manual"}
SMART_SHORT_VIDEO_SECONDS = 180


def valid_whisper_model(model_name: str | None) -> bool:
    return bool(model_name and model_name in WHISPER_MODELS)


def validate_asr_configuration(
    options: dict,
    *,
    selected_model: str,
    supported_backends: set[str],
) -> str | None:
    backend = options["backend"]
    if backend not in supported_backends:
        return f"不支持的语音识别后端: {backend}"
    strategy = options["strategy"]
    if strategy not in ASR_MODEL_STRATEGIES:
        return f"不支持的模型策略: {strategy}"
    models = {
        options["initial_model"],
        options["short_model"],
        options["long_model"],
        selected_model,
    }
    invalid_model = next((model for model in models if model and not valid_whisper_model(model)), None)
    return f"不支持的 Whisper 模型: {invalid_model}" if invalid_model else None


def duration_from_info(video_info: dict | None) -> float | None:
    if not video_info:
        return None
    value = video_info.get("duration") or video_info.get("duration_seconds")
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def resolve_asr_model(
    *,
    whisper_model: str | None,
    strategy: str,
    short_model: str,
    long_model: str,
    duration_seconds: float | None,
) -> str:
    if strategy == "manual":
        return whisper_model or settings.whisper_model
    if duration_seconds is not None and duration_seconds <= SMART_SHORT_VIDEO_SECONDS:
        return short_model
    return long_model


def normalize_asr_options(
    *,
    whisper_model: str | None,
    asr_backend: str | None,
    asr_model_strategy: str | None,
    asr_short_video_model: str | None,
    asr_long_video_model: str | None,
    asr_beam_size: int | None,
    asr_vad_filter: bool | None,
    asr_fallback_enabled: bool | None,
) -> dict:
    backend = (asr_backend or settings.asr_backend or "auto").strip()
    if asr_model_strategy:
        strategy = asr_model_strategy.strip()
    elif whisper_model and not (asr_short_video_model or asr_long_video_model):
        strategy = "manual"
    else:
        strategy = (settings.asr_model_strategy or "smart").strip()
    short_model = asr_short_video_model or settings.asr_short_video_model or "base"
    long_model = asr_long_video_model or settings.asr_long_video_model or "small"
    beam_size = max(1, min(8, int(asr_beam_size or settings.asr_beam_size or 1)))
    return {
        "backend": backend,
        "strategy": strategy,
        "short_model": short_model,
        "long_model": long_model,
        "beam_size": beam_size,
        "vad_filter": settings.asr_vad_filter
        if asr_vad_filter is None
        else bool(asr_vad_filter),
        "fallback_enabled": settings.asr_fallback_enabled
        if asr_fallback_enabled is None
        else bool(asr_fallback_enabled),
        "initial_model": whisper_model or settings.whisper_model,
    }
