# Server-Side Request Forgery (SSRF)

Trigger terms: SSRF, server fetches user-supplied URL, webhook/callback URL,
"fetch image/PDF from URL", internal metadata endpoint reached.

## Core principle

If the server makes an outbound request whose destination is influenced
(directly or indirectly, including via redirects) by user input, an attacker
can use the server as a proxy into networks it can reach but the attacker
can't — internal services, cloud metadata endpoints (e.g. `169.254.169.254`),
localhost.

## Do

- Prefer an allowlist of permitted destination hosts/domains over a
  denylist; validate against the allowlist *after* DNS resolution, not just
  the literal string (DNS rebinding / redirect bypass).
- Disable automatic redirect-following on the outbound HTTP client, or
  re-validate the destination after each redirect hop.
- Block requests to private/link-local/loopback IP ranges
  (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `169.254.0.0/16`, IPv6 equivalents) at the network layer if possible
  (egress firewall rules), in addition to app-layer checks — defense in
  depth matters a lot here.
- If the feature only needs to fetch specific known resource types (e.g.
  images), validate content-type/size after fetch too, not just the URL.
- Isolate the fetching logic in a network segment with no route to internal
  services, if the architecture allows it.

## Don't

- Don't rely solely on blocking by hostname string match (`localhost`,
  `169.254.169.254`) — attackers use decimal/octal/hex IP encodings, DNS
  rebinding, and open redirects to bypass string-based checks.
- Don't validate the URL once at input time and then let the fetch logic
  follow redirects unchecked.

## Detection heuristics for the agent

- Grep for HTTP client calls (`requests.get`, `fetch`, `http.Get`,
  `axios.get`, etc.) whose URL argument is built from request
  params/body/stored user data, especially in webhook, "import from URL",
  thumbnail/preview, or callback features.
- Check whether the client config follows redirects by default and whether
  there's any post-fetch destination re-validation.

## False-positive patterns

- A fetch whose URL is constructed entirely from a server-side, non-user-
  controlled allowlist (e.g. fixed list of 3rd-party API endpoints) is not
  SSRF even if the URL is technically built from a variable.
- A feature that already validates against a strict allowlist of fully
  qualified external domains (no wildcard, no path to internal ranges) and
  disables redirects is adequately mitigated — don't demand network-level
  egress filtering as well unless the ticket specifically requires
  defense-in-depth for a high-sensitivity target.
