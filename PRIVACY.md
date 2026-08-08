# Privacy and data handling

KnowledgeHub is local-first: the application database, imported files,
transcripts, Markdown, task logs, caches and optional local telemetry are kept
under its private application data directory. Source checkouts use `data/` by
default; packaged macOS builds use the current user's application-support
directory. These folders can contain sensitive material and are ignored by
Git.

## What stays local

- Imported originals, OCR results, transcripts, summaries, reports and full
  text indexes.
- Task state, local logs and any screenshots created by the opt-in campus
  visual collector.
- Cookies and local service settings. Where macOS Keychain is available, the
  app uses it for supported sign-in credentials; never add keys, cookies,
  databases, screenshots or reports to a public issue, pull request or commit.
- Diagnostic telemetry is opt-in and currently stored locally. This source tree
  contains no active telemetry upload endpoint.

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
