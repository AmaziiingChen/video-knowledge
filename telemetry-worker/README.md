# KnowledgeHub telemetry collector

This Cloudflare Worker is the KnowledgeHub beta diagnostics
collector. Its free public endpoint is:

`https://knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev/v1/events`

New desktop installations enable the fixed diagnostic catalog by default and
display a non-modal notice under `2026-08-telemetry-v3`; users can disable it
at any time. During the transition the Worker accepts exact, internally
consistent v2 and v3 envelopes so an older pre-release client does not enter a
permanent retry loop.

Deployment status: version 4 of this dual v2/v3 transition collector was
manually deployed on 2026-08-13 with 100% traffic. Remote configuration readback
confirmed the existing HMAC secret, Analytics Engine binding and both rate-limit
namespaces were preserved; preview URLs and persistent invocation logs remain
disabled. Remote HTTP smoke tests passed for 404, strict-schema 400, oversized
413, v2 202 and v3 202. A fresh Analytics Engine row readback for both accepted
synthetic events remains required before releasing the desktop v3 client.

## Data boundary

The Worker accepts only the exact event schema and 17-event catalog defined in
`../docs/product-telemetry-plan.md`. Batch and event objects reject missing or
extra fields; properties must exactly match fixed enumerations. Requests are
limited to 256 KiB and 100 events.

Analytics Engine receives 15 fixed string slots, three numeric slots and one
monthly HMAC sampling index. The Worker uses the raw installation UUID only in
memory to derive purpose-separated monthly identifiers for installation rate
limiting and Analytics Engine sampling; v3 also separates them by notice
version. The raw UUID, properties JSON, content, search terms, URLs, paths,
account identifiers, error text, credentials and logs are not written to
Analytics Engine. Persistent Worker invocation logs are explicitly disabled
because Cloudflare otherwise records request and response metadata. Analytics
Engine retains points for up to three months.

The endpoint is public and accepts no trustworthy client credential: an
open-source desktop app cannot safely embed one. Strict validation and two
IP-free Workers Rate Limiting bindings reduce accidental and abusive traffic:
one uses a shared route key and one uses the monthly HMAC installation key.
Cloudflare rate limits are per PoP and eventually consistent. Treat the dataset
as fallible beta diagnostics, never as identity, billing, security or
individual-level evidence.

## Deployment and redeployment

Deployment is manual and must not be added to GitHub Actions.

1. Run `npm test`.
2. Validate `wrangler.toml`. It deliberately enables `workers_dev`, disables
   preview URLs and disables persistent observability logs.
3. On the first deployment, create `INSTALLATION_HMAC_KEY` as a Cloudflare
   secret with at least 32 random bytes. Preserve that existing secret during
   ordinary redeployments: rotating it breaks monthly Analytics index and
   installation-rate continuity. Rotate only as an explicit security operation
   that accepts and documents that discontinuity. Never commit, print or
   package it.
4. Deploy `src/collector.js` with the `knowledgehub_telemetry` Analytics Engine
   binding and both rate-limit bindings from `wrangler.toml`.
5. Read the deployed settings back and verify preview URLs and invocation logs
   remain disabled. Smoke-test 404, invalid-schema, oversized, valid v2 and
   valid v3 requests; then read both synthetic points back from Analytics Engine
   and verify their notice versions and separated indexes before releasing the
   desktop v3 client.

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
