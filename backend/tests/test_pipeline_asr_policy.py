import pytest
from services.pipeline_asr_policy import (
    duration_from_info,
    resolve_asr_model,
    valid_whisper_model,
    validate_asr_configuration,
)

BASE_OPTIONS = {
    "backend": "auto",
    "strategy": "smart",
    "initial_model": "base",
    "short_model": "base",
    "long_model": "small",
}


def test_asr_policy_handles_duration_and_model_selection():
    assert valid_whisper_model("base")
    assert not valid_whisper_model("unknown")
    assert duration_from_info({"duration": "12.5"}) == 12.5
    assert duration_from_info({"duration": 0}) is None
    assert (
        resolve_asr_model(
            whisper_model=None,
            strategy="smart",
            short_model="base",
            long_model="small",
            duration_seconds=180,
        )
        == "base"
    )
    assert (
        resolve_asr_model(
            whisper_model=None,
            strategy="smart",
            short_model="base",
            long_model="small",
            duration_seconds=181,
        )
        == "small"
    )


@pytest.mark.parametrize(
    ("updates", "expected_error"),
    [
        ({"backend": "unknown"}, "不支持的语音识别后端: unknown"),
        ({"strategy": "random"}, "不支持的模型策略: random"),
        ({"long_model": "huge"}, "不支持的 Whisper 模型: huge"),
    ],
)
def test_validate_asr_configuration_reports_existing_config_errors(updates, expected_error):
    assert (
        validate_asr_configuration(
            {**BASE_OPTIONS, **updates},
            selected_model="small",
            supported_backends={"auto", "mlx", "faster_whisper"},
        )
        == expected_error
    )


def test_validate_asr_configuration_accepts_supported_configuration():
    assert (
        validate_asr_configuration(
            BASE_OPTIONS,
            selected_model="small",
            supported_backends={"auto", "mlx", "faster_whisper"},
        )
        is None
    )
