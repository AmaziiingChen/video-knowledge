---
name: paddleocr-async-integration
description: Integrate Baidu PaddleOCR's asynchronous API into an application that ingests images, screenshots, scanned documents, PDFs, web articles, or knowledge-base content. Use this skill whenever a user asks to add PaddleOCR, OCR article images, extract table or document screenshot text, send image text into an LLM/RAG/summarization pipeline, or preserve OCR output order in a multi-image workflow—even if they only mention screenshots, image tables, or scanned content rather than PaddleOCR by name.
compatibility: Requires an HTTP client such as Python requests and a user-provided PaddleOCR access token; use official Baidu documentation for any API or model change.
---

# PaddleOCR asynchronous integration

Use this skill to make OCR part of the application's source-of-truth content
pipeline, rather than a decorative preview. The desired result is that text
inside tables, notices, screenshots, and scanned documents can be searched,
summarized, and cited with the surrounding text in the correct order.

The bundled client is at `scripts/paddle_ocr_async.py`. Read
`references/baidu-async-api.md` before selecting a model or changing the API
contract.

## First establish the integration boundary

Identify all of the following before changing code:

1. The canonical source-text path: the single text representation used by
   summaries, Q&A, search indexing, exports, and reports.
2. The ingest point where HTML, images, a PDF, or a web article is still
   available in document order.
3. The local settings mechanism for a secret token. Reuse the application's
   existing credential storage rather than adding an environment-independent
   plaintext file.
4. The cache boundary. Existing captures need a deliberate refresh/backfill
   path after OCR is enabled.

Ask a focused question only if one of these is genuinely unavailable. For a
typical article ingestion pipeline, make the reasonable default: OCR belongs
between HTML cleanup and source-text persistence, before any LLM call.

## Select the service and model

For mixed Chinese/English documents, screenshots, tables, charts, and
document-style images, use `PaddleOCR-VL-1.5` through Baidu's asynchronous
job API unless the current official documentation says otherwise. It produces
a Markdown artifact, which preserves table structure more usefully than a
flat text-only response.

Before a production implementation, verify the current official endpoint,
model list, request field names, and result schema. Do not hard-code a token
or copy a token into source, tests, logs, exports, or an issue comment.

## Implement the data flow

Use this order:

```text
source HTML/PDF
  -> remove non-content/video nodes
  -> collect meaningful images in DOM order
  -> download bytes locally with the source page as Referer when needed
  -> submit asynchronous OCR jobs concurrently
  -> poll jobs and download Markdown results
  -> map results back to original positions
  -> persist enriched canonical source text
  -> send enriched text to LLM, search, exports, daily/weekly reports
```

### 1. Choose meaningful images conservatively

Only send content images. Skip video nodes and posters, emoji, QR code or UI
assets, tracking pixels, very small decorative images, and non-HTTP URLs.
Do not delete ordinary content images merely because their text may be sparse:
tables and scanned PDF pages are exactly why OCR is present.

Treat image URLs extracted from remote HTML as untrusted. Permit only public
HTTP(S) addresses, reject localhost/private IP literals, enforce a byte limit,
and avoid sending application credentials to a result URL.

### 2. Preserve order while gaining concurrency

Use a small bounded pool; `5` concurrent images is a safe default. Deduplicate
network OCR by URL if appropriate, but retain a mapping for each original DOM
position. `executor.map` is useful because it returns in input order even when
jobs complete out of order.

Insert successful OCR immediately after the matching image, using a stable,
machine-readable delimiter such as:

```text
[图片文字 3]
| 日期 | 事项 |
| --- | --- |
| 7 月 20 日 | 报到 |
[/图片文字 3]
```

The delimiter makes source provenance clear to the LLM and allows future UI
renderers to style or hide OCR annotations without losing the information.

### 3. Degrade safely

An OCR failure is per-image, not per-article. Keep the original image and
continue the article, recording only a bounded safe error category in metadata.
Never log request headers, multipart payloads, or tokens. Time out polling
jobs; do not leave a worker indefinitely blocked.

If no token is configured, keep existing capture behavior and store metadata
that lets the application know it should backfill when OCR is later enabled.

### 4. Cache and backfill deliberately

Persist both the enriched text and non-secret OCR metadata:

```json
{
  "attempted": true,
  "model": "PaddleOCR-VL-1.5",
  "image_count": 6,
  "recognized_count": 4,
  "failed_count": 1
}
```

When OCR becomes configured, refresh only cached items that contain images and
have never attempted OCR. Do not repeatedly re-fetch an article after a valid
attempt merely because one image failed.

### 5. Carry the complete source downstream

Pass the enriched canonical text to:

- the initial LLM summary and any later Q&A;
- search or RAG indexing;
- Markdown/knowledge-base export;
- scheduled, daily, or weekly reports.

Do not accidentally replace the original body with a summary, or truncate the
body to an arbitrary short excerpt before report generation. If an LLM context
limit requires trimming, make that a documented, configurable total-context
budget and preserve image annotations at their original locations.

## Configure secrets safely

Expose a single password input in the existing Settings or Credentials UI:

- label it `PaddleOCR Access Token` or an equally recognizable local label;
- show only a boolean configured state and fixed model name;
- save locally with owner-only permissions where the platform permits;
- clear the form value after saving and never return it from a GET endpoint.

Do not add an endpoint selector, arbitrary model field, or concurrency slider
unless the product genuinely needs those controls. The default should remain
one token and one tested model.

## Use the bundled client

`scripts/paddle_ocr_async.py` provides a framework-neutral implementation for
local bytes or files. Copy it into the target service or import it in a Python
project, then keep website-specific image downloading and HTML insertion in
the application layer.

```python
from paddle_ocr_async import PaddleOcrAsyncClient

client = PaddleOcrAsyncClient(access_token=token)
result = client.recognize_path("notice.png")
if result.ok:
    markdown_from_image = result.markdown
```

Use `recognize_many_ordered` for bounded parallel batches. It returns a result
for every supplied image in the same order as the input list.

## Validate before handoff

Cover these checks with tests or a deterministic local mock:

1. Two or more images complete out of order but annotations appear in original
   document order.
2. A table-shaped Markdown result is retained in canonical source text and is
   visible to the summary/report input.
3. A failed OCR job does not fail the article.
4. A settings GET response and logs never expose the token.
5. Cached articles captured before configuration are refreshed once after OCR
   is enabled, then stop refreshing on subsequent reads.

Report the selected model, concurrency, cache/backfill behavior, and test
results succinctly. Link the official Baidu documentation rather than claiming
the endpoint or model contract from memory.
