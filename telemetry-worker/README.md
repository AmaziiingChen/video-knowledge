# KnowledgeHub telemetry collector

This Cloudflare Worker is the **opt-in** KnowledgeHub beta diagnostics
collector. Its free public endpoint is:

`https://knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev/v1/events`

The desktop client is offline by default. It contacts this endpoint only after
the user accepts privacy notice `2026-08-telemetry-v2`.

Deployment status: manually deployed on 2026-08-13 to the endpoint above. The
deployed version has the Analytics Engine, two rate-limit and HMAC secret
bindings; preview URLs and persistent Worker logs are disabled. Remote smoke
tests confirmed 404/400/413/202 boundaries and read back the accepted test point
from `knowledgehub_telemetry`.

## Data boundary

The Worker accepts only the exact event schema and 17-event catalog defined in
`../docs/product-telemetry-plan.md`. Batch and event objects reject missing or
extra fields; properties must exactly match fixed enumerations. Requests are
limited to 256 KiB and 100 events.

Analytics Engine receives 15 fixed string slots, three numeric slots and one
monthly HMAC index. It does not receive the raw installation UUID, properties
JSON, content, search terms, URLs, paths, account identifiers, error text,
credentials or logs. Persistent Worker invocation logs are explicitly disabled
because Cloudflare otherwise records request and response metadata. Analytics
Engine retains points for up to three months.

The endpoint is public and accepts no trustworthy client credential: an
open-source desktop app cannot safely embed one. Strict validation and two
HMAC/IP-free Workers Rate Limiting bindings reduce accidental and abusive
traffic, but Cloudflare rate limits are per PoP and eventually consistent.
Treat the dataset as fallible beta diagnostics, never as identity, billing,
security or individual-level evidence.

## Deployment and redeployment

Deployment is manual and must not be added to GitHub Actions.

1. Run `npm test`.
2. Validate `wrangler.toml`. It deliberately enables `workers_dev`, disables
   preview URLs and disables persistent observability logs.
3. Set `INSTALLATION_HMAC_KEY` as a Cloudflare secret with at least 32 random
   bytes. Never commit, print or package it.
4. Deploy `src/collector.js` with the `knowledgehub_telemetry` Analytics Engine
   binding and both rate-limit bindings from `wrangler.toml`.
5. Read the deployed settings back and verify preview URLs and invocation logs
   remain disabled. Smoke-test valid, invalid-schema and oversized requests.

The public collector URL is safe to keep in reviewed source. The HMAC secret
and read-only Analytics query token are not. Query access must remain outside
the repository and use the minimum Cloudflare account permissions.

## Analytics Engine slots

`blob1..15` are, in order: event ID, event name, app version, notice version,
platform, architecture, action, export kind, input kind, processing mode,
result, result-count bucket, stage, state and view.
Missing properties use an empty string. `double1..3` are schema version, macOS
major version and event occurrence time in Unix seconds. `index1` is
`YYYY-MM:<96-bit monthly HMAC>`.

Analytics Engine is at-least-once and has no transactional idempotency store in
this first slice. Analyses must deduplicate on `blob1` (`event_id`) where
appropriate and sum `_sample_interval` for sampled counts.
