# Input Validation

Trigger terms: missing input validation, no length/type/range check,
unvalidated request body, mass assignment.

## Core principle

Validate structure and type/range on the server as early as possible
("fail fast"), as a complement to — never a substitute for — the
sink-specific defenses in [injection.md](injection.md) and [xss.md](xss.md).
Validation reduces attack surface; it doesn't replace parameterization or
output encoding.

## Do

- Prefer allowlist validation (what *is* valid: type, length, range, format/
  regex, enum membership) over denylist (blocking known-bad patterns).
- Validate on the server regardless of any client-side validation (client-
  side is a UX nicety, not a security control).
- Use schema validation (JSON Schema, a DTO/struct with typed fields, a
  validation library) at the API boundary rather than ad-hoc field-by-field
  checks scattered through handler code.
- Guard against mass assignment: explicitly allowlist which fields a client
  can set on create/update, rather than binding the entire request body
  directly onto a model/entity.
- Validate file-related input (names, paths, MIME types) per
  [file-upload.md](file-upload.md) rather than generic string rules.

## Don't

- Don't consider validation sufficient protection against injection/XSS on
  its own — still parameterize queries and encode output.
- Don't validate only at one layer (e.g. the frontend) and assume it holds
  for every other caller of the API (mobile app, partner integration,
  direct API calls).
- Don't use validation regexes that are themselves vulnerable to
  catastrophic backtracking (ReDoS) on attacker-controlled input length.

## Detection heuristics for the agent

- Grep for handlers that bind/deserialize the full request body directly
  into a persisted model without an explicit field allowlist (mass
  assignment risk).
- Grep for endpoints with no schema/validator decorator or call before using
  request data.

## False-positive patterns

- A field that's already constrained by the database schema/column type
  (e.g. a strict enum column) doesn't need duplicate application-level
  validation to be "safe" from a security standpoint, though it's often
  still good practice for clearer errors — don't block a fix on it.
- Internal, trusted service-to-service calls behind the same auth boundary
  may reasonably skip some validation strictness applied to public-facing
  endpoints — confirm the trust boundary before requiring identical
  validation everywhere.
