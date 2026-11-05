# Injection (SQL, OS Command, LDAP, XPath, NoSQL, Template)

Trigger terms: SQLi, SQL injection, OS command injection, shell injection,
LDAP injection, XPath injection, NoSQL injection, SSTI / template injection,
"string concatenation into query/command".

## Core principle

**Never let untrusted input change the *structure* of a command sent to an
interpreter.** Separate code from data using the interpreter's own safe API;
don't try to sanitize your way around concatenation.

## Do

- SQL: parameterized queries / prepared statements / the ORM's bound-parameter
  API. Never build SQL via string formatting, even for "safe-looking" values
  like IDs or sort columns.
- Dynamic identifiers (table/column names that can't be bound as params):
  validate against an explicit allowlist of known-good identifiers, then
  interpolate only the allowlisted value.
- OS commands: avoid invoking a shell at all — call the target binary/API
  directly with an argument array (e.g. `subprocess.run([...], shell=False)`,
  not a shell string). If a shell is unavoidable, use the language's proper
  quoting/escaping primitive, not manual string replacement.
- LDAP/XPath: use the library's parameterized/escaping API for that dialect;
  each has different special characters than SQL.
- NoSQL (Mongo etc.): reject/strip operator-shaped input (keys starting with
  `$`, dots in keys) before it reaches a query object; don't pass raw parsed
  JSON straight into a query.
- Template engines (SSTI): never render a template string built from user
  input; only pass user input as *data* into a fixed template.

## Don't

- Don't rely on blocklisting characters/keywords (`'`, `--`, `DROP`, etc.) —
  it's bypassable and is a smell CodeRabbit/reviewers will correctly flag.
- Don't consider "we escape quotes" sufficient for SQL — use bound params.
- Don't shell out when a language-native API exists (e.g. use a library to
  resize an image instead of shelling out to `convert`).

## Detection heuristics for the agent

- Grep for string concatenation/formatting (`+`, f-strings, `.format`,
  template literals) feeding into a query-execution or shell-execution call.
- Any `shell=True` (Python), `exec()`/`Runtime.exec` with a single
  concatenated string (Java), `os/exec.Command("sh", "-c", ...)` (Go),
  `child_process.exec` with built strings (Node) is a strong signal.
- Confirm the fix compiles/runs the same query logically — parameterizing
  must not change which rows are returned.

## False-positive patterns

- A query built entirely from hardcoded, literal SQL with no variable
  interpolation is not injectable, even if a static scanner flags the
  construction pattern.
- Values already constrained to a safe type by the language/ORM before
  reaching the query (e.g. an `int` parameter, an enum, a value validated via
  `isinstance`/schema before use) are not injectable through that parameter,
  but still parameterize — type constraints can be bypassed in dynamically
  typed languages.
