# Authentication Failures

Trigger terms: weak password policy, credential stuffing, brute force, no
MFA, insecure password reset / "forgot password", predictable credentials,
JWT/OAuth misconfiguration.

## Core principle

Authentication must resist automated guessing and credential-stuffing, never
leak whether a specific identifier (username/email) exists, and never trust
a client-supplied claim of identity without verification.

## Do

- Rate-limit and lock out (or exponentially back off) authentication
  attempts per account and per source IP/fingerprint.
- Use a generic error ("invalid username or password") for both "no such
  user" and "wrong password" — don't let the app reveal account existence.
- Password reset: single-use, time-limited, high-entropy token sent to the
  verified channel; invalidate the token (and ideally all sessions) after
  use; never email/return the new password or a predictable reset link.
- Store passwords with a slow, salted hash: Argon2id (preferred), scrypt, or
  bcrypt with an appropriate work factor — never a fast general-purpose hash
  (MD5, SHA-1, SHA-256 alone) for passwords. See
  [cryptography.md](cryptography.md).
- MFA: support TOTP/WebAuthn; if adding MFA is out of scope for the ticket,
  at minimum flag the gap rather than silently skipping it.
- JWTs: verify signature with a fixed, server-side-known algorithm and key;
  never accept `alg: none`; never trust unverified claims to make
  authorization decisions.
- OAuth: validate `redirect_uri` against an exact allowlist, and the `state`
  parameter to prevent CSRF on the auth flow.

## Don't

- Don't roll a custom password hashing or token generation scheme.
- Don't use predictable tokens (incrementing IDs, timestamps, `Math.random`)
  for anything security-sensitive — use a CSPRNG.
- Don't allow unlimited login attempts "because there's a CAPTCHA" unless the
  CAPTCHA is actually verified server-side on every attempt.
- Don't let JWT `alg` be attacker-controlled (classic `alg: none` /
  RS256→HS256 confusion bug).

## Detection heuristics for the agent

- Grep for login/reset endpoints with no rate-limiting middleware/decorator.
- Password hashing calls using `md5`, `sha1`, `sha256` directly on a
  password string (not via a dedicated password-hashing library).
- JWT verification code that reads `alg` from the token itself to pick the
  verification method, instead of pinning the expected algorithm.

## False-positive patterns

- An internal, non-authentication token (e.g. a CSRF token, a cache key)
  flagged as a "weak credential" is a false positive if it never serves as
  a login or session credential.
- Rate limiting implemented at the infrastructure layer (API gateway, WAF,
  reverse proxy) may satisfy the control even though it's invisible in the
  application code the reviewer sees — confirm with the ticket/architecture
  docs before re-implementing it at the app layer.
