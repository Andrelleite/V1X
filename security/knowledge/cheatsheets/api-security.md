# API Security, Headers, CORS, Misconfiguration

Trigger terms: missing security headers, permissive CORS, debug mode
enabled, verbose error/stack trace, directory listing, default credentials,
rate limiting missing on API.

## Core principle

The same authn/authz/validation rules apply to every interface (REST,
GraphQL, gRPC, webhooks) — "it's an API, not a webpage" is not an exemption.
Configuration defaults should be the secure option; anything permissive must
be an explicit, justified choice.

## Do

- CORS: set `Access-Control-Allow-Origin` to an explicit allowlist of known
  origins; never `*` combined with `Access-Control-Allow-Credentials: true`
  (that combination exposes authenticated data to any origin).
- Security headers where the app already serves HTML/handles browser
  clients: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options`/frame-ancestors via CSP, `Strict-Transport-Security`.
- Disable debug/verbose error pages and stack traces in production
  configuration; return a generic error to the client, log the detail
  server-side only.
- Rate-limit APIs the same way as web login forms where abuse is possible
  (see [authentication.md](authentication.md)).
- GraphQL specifically: disable introspection in production if the schema
  is sensitive, and bound query depth/complexity to prevent resource-
  exhaustion via nested queries.
- Rotate/remove default credentials on any component that ships with them
  (admin panels, DB images, message brokers) before it's reachable.

## Don't

- Don't reflect the request's `Origin` header back as
  `Access-Control-Allow-Origin` as a shortcut to "support any caller" — that
  defeats the allowlist's purpose.
- Don't leave a framework's debug/dev mode enabled by default in the
  production config path.
- Don't expose directory listing on static file servers.

## Detection heuristics for the agent

- Grep CORS middleware config for `*` or an echoed `Origin` combined with
  credentialed requests.
- Grep framework config/env defaults for `debug = true` / `DEBUG=True` in a
  production-targeted config file (vs. a local-dev-only one).
- Check for exposed admin/management endpoints with no auth or still using
  a documented default credential.

## False-positive patterns

- `Access-Control-Allow-Origin: *` on a genuinely public, unauthenticated,
  read-only API (no cookies/credentials involved) is often an intentional
  and acceptable choice — the risk is specifically the combination with
  credentialed requests, not wildcard CORS in isolation.
- Verbose errors enabled in a local-only dev config file that is never
  deployed (confirm via the deployment/CI config, not just the file's
  existence) is lower priority than the same setting in a prod config.
