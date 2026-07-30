# Baidu PaddleOCR asynchronous API reference

Re-check this reference against the official documentation before a production
change: <https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5>

## Current integration contract (verified 2026-07)

- Submit a job with `POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`.
- Authenticate with `Authorization: Bearer <access token>`.
- Submit a local file as multipart field `file`; use `model` for the selected
  model. Passing local bytes avoids a website's anti-hotlink or session-cookie
  restrictions.
- `PaddleOCR-VL-1.5` is the preferred general-purpose high-quality option for
  images that may contain document layout, tables, or charts.
- Poll `GET https://paddleocr.aistudio-app.com/api/v2/ocr/jobs/{jobId}`.
- On completion, read `data.resultUrl.markdownUrl`. Download the signed result
  URL without forwarding the access token.

## Operational defaults

- Start with at most five concurrent images per article or document batch.
- Use a finite poll deadline (for example 120 seconds per image).
- Enforce a local image-size limit before upload.
- Consider API quotas and an application's total LLM context budget separately:
  OCR concurrency is not LLM concurrency.

## Security notes

- Tokens are secrets. Do not write them into a repository, test fixture, UI
  response, command output, telemetry, or Markdown export.
- A remote image URL is untrusted input. Only fetch public HTTP(S) resources,
  reject private/loopback literal IPs, and do not forward tokens to it.
- A result URL may be short-lived. Persist its Markdown content, not the URL.
