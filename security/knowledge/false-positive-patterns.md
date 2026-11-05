# Cross-Cutting False-Positive Patterns

Used during the "defend the patch" step of the CodeRabbit iteration loop
(see root [`CLAUDE.md`](../../CLAUDE.md), Phase 2). Each cheat sheet file
also has its own category-specific false positives — this file is the
patterns that recur across categories.

**Before invoking any of these to write a `FALSE POSITIVE DEFENSE:`, the
agent must point to concrete evidence in *this* codebase** (a specific file/
line/control), not merely cite that "this pattern is sometimes a false
positive" in the abstract. A defense with no cited evidence should be
treated as weak and escalated to a human rather than asserted confidently.

## Recurring patterns

1. **Already mitigated upstream.** The flagged code is reachable only after
   passing through a validation/authorization/encoding layer the reviewer
   didn't see (middleware, decorator, framework default). Evidence required:
   name the specific middleware/decorator and show it's actually applied to
   this route/call path.
2. **Not attacker-reachable.** The input to the "vulnerable" sink is not
   externally controllable — it's a hardcoded literal, a server-generated
   value, or gated behind an internal-only trust boundary. Evidence
   required: trace the actual call path showing no external input reaches
   it.
3. **Context mismatch.** A control that's correct for one sink/category is
   being demanded for a context where it doesn't apply (e.g. demanding a
   CSRF token on a bearer-token API, or Argon2id for a non-password
   checksum). Evidence required: identify the actual sink/use and why the
   demanded control doesn't fit it.
4. **Test/fixture/example code.** The flagged pattern lives in test code,
   fixtures, or documentation examples that never execute against real data
   or ship to production. Evidence required: show the file is excluded from
   the production build/deploy path.
5. **Already-bounded scope.** A finding assumes worst-case exposure (e.g.
   "any user" or "public internet") but the actual code path is restricted
   to a narrower, already-authorized audience (admin-only, internal
   network, feature-flagged off). Evidence required: cite the actual guard.
6. **Severity mismatch, not a false positive.** Sometimes CodeRabbit is
   technically correct but the severity is overstated for this context. In
   that case, do **not** file a false-positive defense — instead, fix it
   (small, low-cost fixes should just be made) or explicitly accept and
   document the residual risk in the MR's confidence/blast-radius note. Do
   not use the false-positive path to avoid doing a cheap fix.

## When genuinely uncertain

If the agent cannot find concrete in-repo evidence for a false-positive
claim within reasonable effort, prefer fixing the flagged issue (even if it
later proves unnecessary) over asserting a false positive without proof —
an unnecessary small fix is cheap; an incorrect false-positive claim that
ships a real vulnerability is not. Reflect this uncertainty in the
confidence score at final sign-off rather than hiding it.
