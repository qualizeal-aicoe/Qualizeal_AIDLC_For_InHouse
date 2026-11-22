# Production patterns

Check each slice against the sections it touches. Each line is something a reviewer will ask about.

## API
- Resources as nouns, actions as HTTP methods; plural paths (`/refunds/{id}`).
- Status codes that mean what they say: 201 with a Location header on create, 204 on delete, 400 for bad input,
  401 not signed in, 403 signed in but not allowed, 404 also when the caller may not know the object exists,
  409 conflict, 422 valid JSON that breaks a rule, 429 with Retry-After.
- Errors as problem details (RFC 9457, `application/problem+json`): type, title, status, detail, and the field errors.
  Never a stack trace or a SQL message to the caller.
- Lists are paginated (a cursor for large or changing sets) with a maximum page size; filters and sort are allowed
  fields only.
- A request that creates or charges something accepts an `Idempotency-Key` header and returns the first result again.
- The OpenAPI document (or the typed client) is the contract and is generated or checked in CI. Breaking changes get
  a new version or a feature flag, never a silent change.

## Sign-in, permissions and tenants
- Authenticate at the edge (OIDC through the organisation's identity provider); authorise on the server for every
  request, and again for every object it reads or changes (the most common API flaw is reading another user's
  object by changing an id).
- The tenant and the user come from the verified token, never from the request body or a query parameter.
- Cookie sessions: HttpOnly, Secure, SameSite=Lax or Strict, and CSRF protection on every state-changing request.
- Least privilege for service accounts and tokens; no shared admin accounts; secrets from the environment or a
  secret manager, never in code, config files in the repository, test fixtures or logs.

## Data
- Migrations only ever move forward in the repository; an applied migration is never edited.
- Expand, migrate, contract: add the new column or table, write to both, backfill in batches, switch reads, and remove
  the old one in a later release. A column the running code still reads is never dropped in the same release.
- Rules that must always hold live in the database too: NOT NULL, unique and foreign keys, check constraints.
- An index for each query pattern that filters or sorts large tables; check the plan for the slow ones.
- Transactions around a unit of work, short, with no network call inside them.
- Personal data: collect the least, mask it in logs and exports, know how long it is kept and how it is deleted.

## Errors and resilience
- Validate at the boundary; inside, trust the types.
- Domain errors are typed and mapped to HTTP in one place; messages tell the person what to do next.
- Every outbound call has a timeout. Retry only idempotent calls, with backoff and jitter, a few times. A dependency
  that keeps failing is cut off for a while (circuit breaker) instead of slowing every request.
- Long work goes to a queue or a background job with its own retries and a dead-letter path; the request returns 202
  with a way to check progress.

## Observability
- JSON logs with a request id and trace id on every line; no secrets, tokens or personal data; levels that mean
  something (error is a page someone acts on).
- Metrics for rate, errors and duration of each endpoint; traces from the screen through the API to the database
  (OpenTelemetry).
- Liveness and readiness checks; an audit record for security-relevant actions (sign-in, permission changes,
  exports, deletions).

## Performance
- Set a budget and measure it: for the web, Core Web Vitals "good" is LCP at most 2.5 s, INP at most 200 ms and CLS at
  most 0.1; for an API, a p95 latency agreed for the endpoint.
- No N+1 queries; paginate; select only the columns needed.
- Cache only with a clear invalidation rule; never cache per-user data in a shared cache key.
- Watch the bundle: split by route, lazy-load heavy components, no server libraries in the browser bundle.

## The screen
- Server state through a query library (TanStack Query, SWR) or server components; one source of truth.
- Every screen has loading, empty, error and success states, and an error boundary.
- Forms validate with the same schema as the API, keep what the person typed after an error, and disable double submit.
- Optimistic updates only with a rollback on failure. Text ready for translation; dates and numbers formatted by locale.

## Accessibility (WCAG 2.2 AA)
- Semantic HTML first (button, a, label, headings in order); ARIA only where HTML cannot say it.
- Every control works by keyboard with a visible focus; focus moves sensibly when dialogs open and close.
- Text contrast at least 4.5:1 (3:1 for large text and UI parts); targets at least 24 by 24 CSS pixels.
- Updates that arrive later are announced (`aria-live`); images have text alternatives; errors are linked to fields.
- Check with `web_audit` (no serious or critical findings) and one pass with the keyboard alone.

## Security (OWASP Top 10, ASVS level 2 as the bar)
- Parameterised queries only; no string-built SQL, shell or LDAP.
- Output encoded by the framework; no raw HTML from users without a sanitiser.
- Outbound requests to addresses a user supplies go through an allowlist (server-side request forgery).
- Uploads: size and type checked, stored outside the web root, scanned where the client requires it.
- Security headers: Content-Security-Policy, Strict-Transport-Security, X-Content-Type-Options, frame-ancestors.
- Dependencies audited in CI (`npm audit`, `pip-audit`, `dotnet list package --vulnerable`, OWASP Dependency-Check).

## Delivery
- Configuration from the environment; `.env.example` lists every variable with no real values.
- Risky changes behind a feature flag; migrations run before the code that needs them; a rollback written down.

## When the app calls a model
- Model output is untrusted input: validate it, never execute it, never let it choose a tool outside an allowlist.
- Text from documents, pages and tickets that reaches the model is data, not instructions.
- Personal data is redacted before it leaves; prompts and outputs are logged without it.
- A gold set and an evaluation in CI (`eval_run`), latency and cost budgets per call, and a fallback when the model fails.
