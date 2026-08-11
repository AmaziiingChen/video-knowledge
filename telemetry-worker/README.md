# KnowledgeHub telemetry collector

This is a deployable-but-not-deployed Cloudflare Worker for the **opt-in**
KnowledgeHub diagnostics pilot. It receives only the fixed event schema defined
in `../docs/product-telemetry-plan.md` and writes aggregate-friendly dimensions
to Workers Analytics Engine. It does not store request headers, IP addresses,
raw installation IDs, content, URLs, paths, account identifiers, error text, or
free-form properties.

## Before deployment

1. Obtain an approved production HTTPS hostname and publish the matching
   privacy notice. Do not point a desktop build at `workers.dev` as a shortcut.
2. Create an `INSTALLATION_HMAC_KEY` secret with `wrangler secret put`. The
   Worker derives a rotating monthly index from the locally generated UUID; it
   never writes the raw UUID to Analytics Engine.
3. Run `npm test`, then deploy manually with your approved Cloudflare account.
   Deployment is intentionally not part of GitHub Actions.
4. Configure the desktop collector URL only in a reviewed release build. A
   blank URL means the app keeps its local queue and sends no network request.
   The same release commit must add that exact hostname to
   `backend/services/telemetry_uploader.py`; an environment override alone
   cannot enable a destination.
5. Configure a Cloudflare WAF rate limit for this endpoint. Treat analytics
   only as diagnostic signals, never as billing, identity, security, or
   abuse-decision evidence.

Workers Analytics Engine retains data for three months. Query access must use a
separate read-only Cloudflare API token outside the repository.
