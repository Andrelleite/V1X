# Claude Fallback via Pro/Max Subscription (instead of a billed API key)

The Fixer tries Gemini first and falls back to Claude Code only if Gemini
is unavailable or fails (`orchestrator/runners.py`). Normally that fallback
needs an `ANTHROPIC_API_KEY` from `console.anthropic.com` — billed
separately from a Claude.ai Pro/Max subscription. If you don't want to pay
for Console API credits, Claude Code also supports authenticating with your
Claude.ai subscription session instead, and that's what this document sets up.

## What this actually is

`claude login` stores an OAuth session (access token + refresh token) for
your Claude.ai account:
- **macOS**: in the system Keychain, service name `Claude Code-credentials`.
- **Linux** (GitHub Actions runners): as a JSON file at
  `~/.claude/.credentials.json`.

To use it in CI, the Keychain-stored blob is copied out and stored as a
GitHub Actions secret (`CLAUDE_CODE_OAUTH_CREDS`), then restored to the
Linux file path on the runner before each job
(see the "Restore Claude Code subscription session" step in
`.github/workflows/ai-fix.yml` and `review-loop.yml`).

## Risk tradeoffs — read before relying on this

- **It's a full account session, not a scoped key.** The JSON blob's scopes
  include `user:inference`, `user:profile`, `user:sessions:claude_code` —
  broader than "just run Claude Code headlessly." If this GitHub secret
  leaks, whoever has it can act as your Claude.ai account until you revoke
  the session, and there's no way to scope it down the way an API key can
  be scoped to one purpose.
- **It can go stale.** The refresh token reportedly expires after ~30 days
  of disuse. A pipeline that only fires occasionally may need the secret
  re-captured and re-pasted periodically — this isn't "set and forget."
- **Check Anthropic's consumer terms yourself.** Whether automating a
  personal subscription session this way is within the Claude.ai Pro/Max
  terms of service wasn't something I could verify — confirm it before
  relying on this for anything beyond a personal trial.
- **Subscription-tier rate limits apply**, which are lower-throughput than
  the Console API and meant for individual interactive use, not heavy
  automated traffic.

## How to (re)generate the secret

**Never run the extraction command in a terminal tab connected to an AI
coding assistant session** — several of these forward terminal input/output
into the conversation automatically, which would leak the credential into
a chat transcript. Use a plain, disconnected terminal window.

```bash
# In a disconnected terminal window only:
security find-generic-password -s "Claude Code-credentials" -w
```

Copy that output directly into a new GitHub secret named
`CLAUDE_CODE_OAUTH_CREDS` at
`https://github.com/<owner>/<repo>/settings/secrets/actions` — paste from
the terminal straight into GitHub's field, never through a chat assistant.

If you ever suspect this credential has leaked (including just having typed
it somewhere you're not sure about), rotate it immediately:

```bash
claude logout
claude login
```

Then repeat the extraction and update the GitHub secret with the new value.
