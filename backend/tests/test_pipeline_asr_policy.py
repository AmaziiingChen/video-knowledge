from services.pipeline_asr_policy import (
    duration_from_info,
    resolve_asr_model,
    valid_whisper_model,
)


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
