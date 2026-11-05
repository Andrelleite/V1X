# Cryptographic Failures (Storage, Transport, Password Hashing)

Trigger terms: cleartext, weak cipher, MD5/SHA1 for passwords/signatures,
hardcoded key, no TLS, weak TLS config, ECB mode, predictable IV/nonce.

## Core principle

Use well-vetted, modern, high-level crypto APIs with safe defaults; never
invent a cryptographic scheme; classify data sensitivity before deciding what
needs protecting and how.

## Do

- Passwords: Argon2id (preferred) / bcrypt / scrypt via a maintained library
  — never a general-purpose hash function alone.
- Data at rest: AES-GCM (authenticated encryption) via a vetted library;
  never ECB mode; never a static/hardcoded key — pull keys from a secrets
  manager or KMS (see [secrets-management.md](secrets-management.md)).
- Data in transit: TLS 1.2+ (prefer 1.3), with certificate validation
  actually enabled (never disable verification to "fix" a connection error).
- Nonces/IVs: generate fresh, random (or per the algorithm's specific
  requirement, e.g. GCM's uniqueness-per-key requirement) for every
  encryption operation — never reuse.
- Key management: rotate-able, stored outside source control, access
  restricted by least privilege; separate keys by purpose/environment.
- Use the platform's standard library crypto module or a well-known vetted
  package — don't implement AES/hashing/padding by hand.

## Don't

- Don't use MD5/SHA-1 for anything security-sensitive (passwords,
  signatures, tokens) — they remain fine for non-security checksums only
  (e.g. cache-busting a static asset), don't "fix" those.
- Don't hardcode keys/secrets in source, config committed to the repo, or
  client-side code.
- Don't disable TLS certificate/hostname verification, even "temporarily."
- Don't use ECB mode or a fixed IV for any block cipher mode that requires
  uniqueness.

## Detection heuristics for the agent

- Grep for `md5(`, `sha1(` applied to passwords/tokens/signatures.
- Grep for `verify=False`, `InsecureSkipVerify`, `rejectUnauthorized: false`,
  or equivalent TLS-verification bypass flags.
- Grep for string-literal keys/secrets passed to crypto functions.
- Check cipher mode constants for `ECB`, and IV/nonce generation for
  constants or counters reused across calls incorrectly.

## False-positive patterns

- MD5/SHA-1 used purely as a non-cryptographic checksum (file dedup, cache
  key, ETag) is not a security finding — don't "upgrade" it to Argon2id,
  that's the wrong tool and adds unnecessary cost/complexity; just confirm
  it's genuinely not security-sensitive.
- TLS verification disabled only inside a test/CI fixture that never runs
  against production endpoints may be acceptable — confirm the code path is
  actually test-only (and ideally still flag it as worth isolating more
  clearly) before treating it the same as a production bypass.
