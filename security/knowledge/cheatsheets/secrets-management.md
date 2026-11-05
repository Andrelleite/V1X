# Secrets Management

Trigger terms: hardcoded secret/key/credential, secret committed to repo,
API key in code, .env committed, secret in logs.

## Core principle

Secrets (API keys, DB credentials, signing keys, tokens) must never live in
source code or version control; they're injected at runtime from a secrets
manager, vault, or environment-specific config outside the repo.

## Do

- Move any discovered hardcoded secret to environment variables or a
  secrets manager (Vault, AWS/GCP/Azure secret manager, CI/CD secret store)
  and load it at runtime.
- **Treat the exposed secret as compromised**: the fix must include (or the
  MR must explicitly call out, since an agent usually can't rotate
  production credentials itself) rotating/revoking the leaked credential —
  removing it from the current file does not undo its exposure in git
  history.
- Add the specific pattern (filename, extension) to `.gitignore` to prevent
  recurrence, if a literal secrets file was committed.
- Scrub secrets from logs, error messages, and crash reports before they're
  written.

## Don't

- Don't just delete the secret from the latest commit and consider it
  fixed — it's still in git history/caches unless history is rewritten and
  the credential rotated; say this explicitly in the MR.
- Don't replace a hardcoded secret with a slightly-less-hardcoded one (e.g.
  moving it to a config file that's still committed).
- Don't log full request/response bodies on endpoints that handle
  credentials or tokens.

## Detection heuristics for the agent

- Grep for high-entropy strings assigned to variables named like `key`,
  `secret`, `token`, `password`, `api_key`, and common provider key prefixes
  (e.g. `AKIA`, `sk-`, `ghp_`).
- Check `.gitignore` for coverage of `.env`/credential files that exist in
  the working tree.

## False-positive patterns

- A placeholder/example value in a `.env.example`, README, or test fixture
  (clearly not a live credential — e.g. `sk-xxxx`, `changeme`) is not a real
  secret leak; don't flag or "fix" documentation examples.
- A key that's intentionally public by design (e.g. a frontend analytics
  site key meant to be embedded in client-side JS) is not a secret leak —
  confirm the provider's own threat model for that key type before treating
  it as a finding.
