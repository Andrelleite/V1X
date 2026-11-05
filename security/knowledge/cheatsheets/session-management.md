# Session Management

Trigger terms: session fixation, predictable session token, session doesn't
expire, session not invalidated on logout, cookie missing flags.

## Core principle

Session identifiers must be unpredictable, scoped correctly, rotated on
privilege change, and actually invalidated server-side when a session ends
— not just forgotten client-side.

## Do

- Generate session IDs with a CSPRNG, sufficient length/entropy (OWASP
  guidance: effectively unguessable, e.g. ≥128 bits of entropy).
- Set cookies with `HttpOnly`, `Secure`, and an appropriate `SameSite`
  (`Lax` or `Strict`); scope `Path`/`Domain` as narrowly as the app allows.
- Regenerate the session ID on login and on any privilege change (e.g.
  user → admin) — this prevents session fixation.
- Invalidate the session **server-side** on logout, not just by clearing the
  client cookie; also invalidate on password change.
- Set both an idle timeout and an absolute maximum session lifetime.

## Don't

- Don't put sensitive data or anything resembling a session identifier in a
  URL (it leaks via browser history, logs, Referer headers).
- Don't accept a session ID the client invented (always generate
  server-side) — this is session fixation.
- Don't treat "cleared the cookie on the client" as equivalent to
  invalidating the session.

## Detection heuristics for the agent

- Grep session-creation code for the source of the session ID: is it from a
  CSPRNG/session-framework default, or hand-rolled (timestamp, counter,
  user ID hash)?
- Check the logout handler actually calls the session store's
  destroy/invalidate function, not just a client-side redirect/cookie clear.
- Check cookie-setting code for missing `HttpOnly`/`Secure`/`SameSite`.

## False-positive patterns

- Frameworks that manage sessions via a signed, server-validated cookie
  (e.g. properly configured signed cookie sessions) may not need a separate
  server-side session store to be "invalidated" — rotation of the signing
  key or a server-side deny-list/version check for logout can be an
  equivalent, valid control; verify before demanding a different mechanism
  wholesale.
- `Secure` flag omission on a cookie scoped to a purely local-dev host
  (`localhost`) is not exploitable there, but must still be present in the
  production configuration path — don't "fix" a dev-only code path and call
  it done.
