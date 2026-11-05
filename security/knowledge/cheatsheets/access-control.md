# Access Control / Authorization (incl. IDOR)

Trigger terms: IDOR, insecure direct object reference, broken access
control, privilege escalation, missing authorization check, forced
browsing, horizontal/vertical privilege escalation.

## Core principle

Authorization must be enforced **server-side, on every request, deny by
default**. Never infer that a request is authorized just because the client
only exposed a "safe" UI path to it, or because the user supplied the
"right" ID.

## Do

- Re-check authorization on the server for every state-changing or
  data-returning request — not just by hiding UI elements.
- For object access (the classic IDOR): verify the *authenticated user* owns
  or is permitted to access *this specific* object ID, not just that they're
  authenticated at all. Scope the database query itself by the user/tenant
  (e.g. `WHERE id = :id AND owner_id = :current_user`), don't fetch-then-check
  in application code if the fetch itself can leak existence via timing/errors.
- Prefer indirect references (opaque IDs, UUIDs scoped per user) over
  sequential IDs where feasible, as defense in depth — but this is not a
  substitute for the ownership check above.
- Enforce the same checks across every interface that reaches the same
  logic: REST, GraphQL resolvers, internal RPC, batch/export jobs, admin
  tooling.
- Default to deny: a new role/endpoint with no explicit rule should fail
  closed, not open.

## Don't

- Don't rely on "the frontend doesn't show that button" as a control.
- Don't check authorization once at the start of a multi-step flow and then
  trust it for later steps — recheck at each sensitive step.
- Don't conflate authentication ("is this a logged-in user") with
  authorization ("is this user allowed to do *this*").

## Detection heuristics for the agent

- Grep handlers that take an ID from the path/body/query and fetch a record
  by that ID directly — confirm there's a corresponding ownership/role check
  before the data is returned or mutated.
- Compare sibling endpoints (e.g. `GET /orders/:id` vs `PATCH /orders/:id`) —
  a missing check on one but present on the other is a strong signal.
- Admin/internal endpoints reachable without a role check because they were
  assumed to be "not linked from the UI."

## False-positive patterns

- An ID-based endpoint where the object is genuinely public (e.g. a public
  blog post by slug) has no ownership check to make — confirm the data's
  actual sensitivity/visibility model before flagging missing authorization.
- A check performed by middleware/framework-level policy (e.g. a resource
  guard, policy object, or API gateway rule) that doesn't appear inline in
  the handler is not necessarily missing — trace the full request path
  before concluding the check is absent.
