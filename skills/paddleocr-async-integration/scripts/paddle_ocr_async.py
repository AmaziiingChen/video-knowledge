"""Small, framework-neutral client for Baidu PaddleOCR asynchronous jobs.

The module intentionally accepts local bytes/files. Website-specific fetching,
HTML parsing, cache storage, and credential UI belong to the caller.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import time
from typing import Any, Iterable

import requests


DEFAULT_MODEL = "PaddleOCR-VL-1.5"
JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"


@dataclass(frozen=True)
class OcrResult:
    label: str
    markdown: str = ""
    status: str = "failed"
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "succeeded" and bool(self.markdown)


class PaddleOcrAsyncClient:
    def __init__(
        self,
        *,
        access_token: str,
        model: str = DEFAULT_MODEL,
        poll_timeout_seconds: float = 120,
        poll_interval_seconds: float = 1,
    ) -> None:
        self._token = access_token.strip()
        if not self._token:
            raise ValueError("PaddleOCR access token is required")
        self.model = model
        self.poll_timeout_seconds = poll_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def recognize_path(self, path: str | Path, *, label: str | None = None) -> OcrResult:
        source = Path(path)
        if not source.is_file():
            return OcrResult(label=label or source.name, error="file_not_found")
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return self.recognize_bytes(source.read_bytes(), filename=source.name, content_type=content_type, label=label or source.name)

    def recognize_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str,
        label: str | None = None,
    ) -> OcrResult:
        result_label = label or filename
        if not content:
            return OcrResult(label=result_label, error="empty_file")
        try:
            job_id = self._submit(content, filename=filename, content_type=content_type)
            result_url = self._wait_for_markdown(job_id)
            markdown = _compact_markdown(self._download_markdown(result_url))
            return OcrResult(
                label=result_label,
                markdown=markdown,
                status="succeeded" if markdown else "empty",
            )
        except requests.Timeout:
            return OcrResult(label=result_label, error="timeout")
        except requests.RequestException:
            return OcrResult(label=result_label, error="network_error")
        except ValueError as exc:
            return OcrResult(label=result_label, error=str(exc)[:120])

    def _submit(self, content: bytes, *, filename: str, content_type: str) -> str:
        response = requests.post(
            JOB_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            data={
                "model": self.model,
                "optionalPayload": json.dumps(
                    {
                        "useDocOrientationClassify": True,
                        "useDocUnwarping": True,
                        "useChartRecognition": True,
                    }
                ),
            },
            files={"file": (filename, content, content_type)},
            timeout=45,
        )
        response.raise_for_status()
        data = _response_data(response)
        job_id = str(data.get("jobId") or data.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("missing_job_id")
        return job_id

    def _wait_for_markdown(self, job_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout_seconds
        while time.monotonic() < deadline:
            response = requests.get(
                f"{JOB_URL}/{job_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=20,
            )
            response.raise_for_status()
            data = _response_data(response)
            result_urls = data.get("resultUrl") or data.get("result_url") or {}
            if isinstance(result_urls, dict):
                markdown_url = str(result_urls.get("markdownUrl") or result_urls.get("markdown_url") or "").strip()
                if markdown_url:
                    return markdown_url
            state = str(data.get("state") or data.get("status") or "").lower()
            if state in {"failed", "failure", "cancelled", "canceled", "error"}:
                raise ValueError("job_failed")
            time.sleep(self.poll_interval_seconds)
        raise ValueError("poll_timeout")

    @staticmethod
    def _download_markdown(url: str) -> str:
        # Result URLs are normally signed. Do not forward the access token to a
        # separately hosted URL.
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text


def recognize_many_ordered(
    client: PaddleOcrAsyncClient,
    items: Iterable[tuple[str, bytes, str, str]],
    *,
    max_workers: int = 5,
) -> list[OcrResult]:
    """Return one result per input item, in exactly the supplied order.

    Each item is `(label, bytes, filename, content_type)`.
    """
    batch = list(items)
    if not batch:
        return []
    workers = max(1, min(max_workers, len(batch)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paddleocr") as executor:
        return list(
            executor.map(
                lambda item: client.recognize_bytes(
                    item[1], filename=item[2], content_type=item[3], label=item[0]
                ),
                batch,
            )
        )


def _response_data(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("invalid_response") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_response")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _compact_markdown(value: str) -> str:
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    gap = False
    for line in lines:
        if not line.strip():
            gap = bool(compact)
            continue
        if gap:
            compact.append("")
            gap = False
        compact.append(line)
    return "\n".join(compact).strip()
