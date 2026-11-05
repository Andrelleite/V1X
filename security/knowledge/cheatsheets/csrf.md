# Cross-Site Request Forgery (CSRF)

Trigger terms: CSRF, cross-site request forgery, "state-changing GET
request", missing CSRF token.

Note: dropped from the OWASP Top 10 in 2021 because modern frameworks
mitigate it by default — but still a valid, common finding when a specific
endpoint bypasses the framework's default protection.

## Core principle

A state-changing request must prove it originated from the app's own
frontend, not just that it carries a valid session cookie (cookies are sent
automatically by the browser regardless of origin).

## Do

- Use the framework's built-in CSRF protection (synchronizer token pattern,
  or double-submit cookie) — don't disable it, and don't build a custom one.
- Ensure `SameSite=Lax` or `Strict` is set on session cookies as
  defense-in-depth (see [session-management.md](session-management.md)).
- Any state-changing action (create/update/delete) must use a method other
  than plain `GET` (`GET` requests should never mutate state — browsers,
  proxies, and link previews can trigger them without user intent).
- For APIs consumed only by JS clients (not browser forms), a custom header
  the browser won't auto-attach cross-origin (checked server-side) is an
  accepted alternative to a token.

## Don't

- Don't exempt an endpoint from CSRF protection just because it's
  "internal" or "called via AJAX" without confirming the header-based
  mitigation is actually in place.
- Don't treat a `Referer`/`Origin` header check alone as sufficient — it's a
  reasonable additional signal, not a replacement for a token/header
  control, since these headers can be absent or stripped in some contexts.

## Detection heuristics for the agent

- Grep for routes marked to skip/exempt the framework's CSRF middleware.
- Grep for state-changing handlers bound to `GET`.
- Check that cookie-based session auth endpoints doing mutations require a
  CSRF token or an equivalent custom-header check.

## False-positive patterns

- An endpoint authenticated via a bearer token in an `Authorization` header
  (not a cookie) generally isn't CSRF-vulnerable, because the browser won't
  auto-attach that header cross-origin — don't demand a CSRF token there.
- A `GET` request that is read-only (no state change) doesn't need CSRF
  protection regardless of what data it returns.
