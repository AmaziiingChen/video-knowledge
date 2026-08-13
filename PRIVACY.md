# Privacy and data handling

KnowledgeHub is local-first: the application database, imported files,
transcripts, Markdown, task logs and caches are kept under its private
application data directory. Source checkouts use `data/` by default; packaged
macOS builds use the current user's application-support directory. These
folders can contain sensitive material and are ignored by Git.

## What stays local

- Imported originals, OCR results, transcripts, summaries, reports and full
  text indexes.
- Task state, local logs and any screenshots created by the opt-in campus
  visual collector.
- Cookies and local service settings. Where macOS Keychain is available, the
  app uses it for supported sign-in credentials; never add keys, cookies,
  databases, screenshots or reports to a public issue, pull request or commit.
- New installations start with a fixed, de-identified diagnostic catalog
  enabled. Pending events use a separate local database. Disabling diagnostics
  deletes that database and random installation ID; a one-value local opt-out
  preference remains so updates do not silently re-enable it.

## Default-on, de-identified diagnostics

On first launch KnowledgeHub tells you that it sends a low-frequency batch to
the project’s Cloudflare Worker at
`knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev`. The collector
accepts only 17 predefined event names and fixed enumerated values such as a
feature result, processing stage, app version, macOS major
version and CPU architecture. It rejects additional fields. You can disable
this at any time in “Privacy & Diagnostics” without losing product features.

KnowledgeHub does **not** send imported content, OCR text, transcripts,
summaries, prompts, answers, search terms, clipboard contents, URLs, paths,
filenames, account identifiers, cookies, tokens, API keys, error messages,
stacks or logs. A locally generated random installation UUID is sent over TLS
to the Worker and used only in memory to derive purpose-separated monthly HMAC
identifiers for installation rate limiting and Analytics Engine sampling. The
raw UUID is not written to Analytics Engine. Cloudflare necessarily processes
source IP and other network metadata while delivering and protecting the
request; persistent Worker invocation logs are disabled.

Cloudflare Analytics Engine retains these de-identified diagnostic points for
up to three months. Disabling telemetry immediately stops future collection and
deletes pending local events and the local random installation ID. Previously
uploaded points expire under the service retention period; this first beta
collector does not provide per-point deletion. The free `workers.dev` endpoint
is not a critical application service, and telemetry failure never blocks
normal product features.

## Network requests that you initiate or configure

Some features necessarily send data to external services. Enable them only if
you accept the corresponding provider's terms and privacy policy.

- Adding or synchronising a link contacts that source platform and may use your
  configured account session.
- AI summaries, reports and questions send the selected source text and your
  prompt to the configured compatible AI provider. The default configuration
  points to DeepSeek only after you supply a key.
- Cloud PaddleOCR sends the image or PDF pages selected for OCR to the
  configured PaddleOCR service after you enable and configure it.
- Browser-based page previews load the original site's resources in an
  isolated Electron session. Links that you choose to open externally are
  handled by your browser.
- Publishing a report is an explicit action. Only the artifacts you select for
  publication should be uploaded to the destination you configure.
- De-identified diagnostics contact Cloudflare by default after startup. The
  application displays a non-modal notice and waits at least 60 seconds before
  its first upload check, so you can disable them immediately in “Privacy &
  Diagnostics”.

## Practical safeguards

1. Keep `backend/.env`, `data/`, `materials/`, downloaded media and exported
   reports out of version control.
2. Use a separate test account for platform integrations when practical, and
   revoke a provider key or sign-in session if it is exposed.
3. Review the source text and OCR image before sending it to an AI or OCR
   provider. Disable cloud features for material that must remain offline.
4. Before sharing logs, remove paths, URLs, cookies, tokens, report text and
   personal information.

This document describes the implementation in this repository and is not a
legal privacy notice for a hosted service.
