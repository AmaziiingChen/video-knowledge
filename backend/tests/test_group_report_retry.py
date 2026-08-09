from services.group_report_retry import is_retryable_summary_error


class HttpError(RuntimeError):
    def __init__(self, status_code):
        self.status_code = status_code


def test_summary_retry_policy_accepts_only_transient_transport_and_http_failures():
    assert is_retryable_summary_error(ConnectionError("offline"))
    assert is_retryable_summary_error(HttpError(429))
    assert is_retryable_summary_error(HttpError("503"))
    assert not is_retryable_summary_error(HttpError(400))
    assert not is_retryable_summary_error(HttpError("invalid"))


def test_summary_retry_policy_keeps_known_provider_and_message_fallbacks():
    api_timeout = type("APITimeoutError", (RuntimeError,), {})
    assert is_retryable_summary_error(api_timeout())
    assert is_retryable_summary_error(RuntimeError("connection reset by peer"))
    assert not is_retryable_summary_error(RuntimeError("invalid API key"))
