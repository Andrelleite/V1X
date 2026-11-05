# Cross-Site Scripting (XSS)

Trigger terms: XSS, reflected/stored/DOM-based XSS, "unescaped output",
"innerHTML", "dangerouslySetInnerHTML", "v-html".

## Core principle

**Encode output for the specific sink it's written into**, and keep user
data out of sinks that execute as code (HTML parser, JS context, URL,
CSS) unless it's been encoded for exactly that context.

## Do

- Let the framework's default templating auto-escape (Jinja2, ERB, JSX text
  children, Vue mustache `{{ }}`) do the work — don't bypass it.
- If raw HTML truly must be rendered (rich text), sanitize with an
  allowlist-based HTML sanitizer (e.g. DOMPurify) immediately before
  rendering, not at input time only (defense must hold at the point of use).
- Context-specific encoding: HTML-entity encode for HTML body, JS-string
  escape for inline `<script>` data, URL-encode for URL params, attribute
  encode for HTML attributes — these are not interchangeable.
- Set `Content-Type` correctly and add a `Content-Security-Policy` header as
  defense-in-depth where the app already has header infrastructure (don't
  introduce a whole CSP rollout as a side effect of a single XSS ticket).
- For DOM-based XSS: avoid `innerHTML`, `document.write`,
  `dangerouslySetInnerHTML`, `v-html` with any data derived from
  URL/location/postMessage/user input; use `textContent` or the framework's
  safe binding instead.

## Don't

- Don't sanitize only on input/storage and assume it's safe to render
  unescaped later — the same string can be safe in one sink and dangerous in
  another.
- Don't hand-roll a regex-based HTML sanitizer.
- Don't trust `Referer`/`postMessage` origin checks alone as an XSS control.

## Detection heuristics for the agent

- Grep for `innerHTML =`, `dangerouslySetInnerHTML`, `v-html`,
  `document.write`, template engines invoked with `|safe`/`autoescape=False`/
  `Markup()`/`raw()` wrapping user-controlled data.
- Reflected request params/headers echoed into HTML responses without the
  template's auto-escaping (e.g. manually built HTML strings).

## False-positive patterns

- Output going through a templating engine's default auto-escaping context
  is already safe; a scanner flagging the *source* of untrusted data without
  checking the *sink's* escaping is a common false positive — verify the
  actual rendered context before "fixing" an already-escaped value.
- A value that is template/compile-time constant (not user-controlled) using
  `|safe`/`dangerouslySetInnerHTML` for static markup is not exploitable.
