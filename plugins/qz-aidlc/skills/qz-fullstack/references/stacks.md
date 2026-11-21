# Stack recipes

Read the section for the stack in front of you. Each gives the layout, the commands ship_check runs, the libraries
the team reaches for, and the mistakes that reach review most often. When a repository already does something
differently, the repository wins: match its conventions and say so if they are risky.

## TypeScript: Next.js (App Router) and Node

- **Layout**: `app/` routes and server components; `app/api/**/route.ts` route handlers or server actions next to the
  page; `lib/` domain code with no framework imports; `db/` schema and migrations; `tests/` or files beside the code.
- **Commands**: `npm ci` · `npm run lint` · `npx tsc --noEmit` · `npm test` (Vitest) · `npm run build` · `npx playwright test`.
- **Validation**: zod at every boundary: route handler and server action input, environment variables at start-up.
  Share the schema with the form so the browser and the server agree.
- **Data**: Prisma (`prisma migrate dev`, `prisma migrate deploy` in release) or Drizzle (`drizzle-kit generate`, then
  migrate). PostgreSQL by default; SQLite for proofs of concept.
- **Sign-in**: Auth.js with the organisation's OIDC provider (Entra ID, Okta). Read the session on the server in every
  route handler and server action; middleware alone is not authorisation.
- **Tests**: Vitest and Testing Library for components and hooks; route handlers called directly with a Request;
  MSW for outside HTTP; Playwright for one path per screen.
- **Observability**: OpenTelemetry (`@vercel/otel` or the Node SDK); pino for JSON logs.
- **Mistakes that reach review**: secrets in `NEXT_PUBLIC_*` (they ship to the browser); a server action without an
  authorisation check (it is a public endpoint); relying on default fetch caching instead of setting revalidation;
  importing server-only code into a client component (mark it with `import "server-only"`).

## React (Vite) and FastAPI

- **Layout**: `web/` (Vite, React, TypeScript); `api/app/` with `main.py`, `routers/`, `schemas/` (pydantic),
  `models/` (SQLAlchemy), `services/`; `api/alembic/`; `api/tests/`.
- **Commands**: web as above. API: `pip install -r requirements.txt` (or `uv sync`) · `ruff check .` · `mypy app` ·
  `pytest -q` · `alembic upgrade head`.
- **Validation**: pydantic v2 models for every request and response; set `response_model` so fields never leak.
- **Data**: SQLAlchemy 2.0 typed ORM; Alembic migrations (autogenerate, then read and fix what it wrote). Async engine
  with asyncpg only if the whole path is async.
- **Sign-in**: verify the IdP's JWT against its JWKS (PyJWT with a JWKS client); a `Depends(current_user)` dependency,
  plus a permission check in each route that reads or changes an object.
- **Tests**: pytest with httpx `AsyncClient` (or `TestClient`); the database through testcontainers or a session
  rolled back after each test; Vitest and Playwright for the web.
- **Observability**: `opentelemetry-instrumentation-fastapi`; structlog or JSON logging; a request-id middleware.
- **Mistakes**: blocking calls inside `async def` routes; `allow_origins=["*"]` with credentials; returning ORM objects
  without a response model; lazy loading in loops (N+1).

## .NET (ASP.NET Core) and React

- **Layout**: `src/Api` (minimal APIs or controllers), `src/Domain`, `src/Infrastructure` (EF Core), `tests/Api.Tests`
  (xUnit), `web/`.
- **Commands**: `dotnet restore` · `dotnet build -warnaserror` · `dotnet test` · `dotnet format --verify-no-changes` ·
  `dotnet ef migrations add <Name>`; deploy migrations as a bundle or script, not at app start in production.
- **Validation**: FluentValidation or data annotations with endpoint filters; `AddProblemDetails()` so every error is
  a problem response.
- **Data**: EF Core; `AsNoTracking()` for reads; project to DTOs, never bind request bodies to entities (over-posting).
- **Sign-in**: Microsoft.Identity.Web for Entra ID, or JwtBearer; named authorisation policies with
  `RequireAuthorization("policy")` on every endpoint group.
- **Tests**: xUnit with `WebApplicationFactory` for integration; Testcontainers for .NET for SQL Server or PostgreSQL.
- **Observability**: OpenTelemetry .NET (`AddOpenTelemetry().WithTracing(...).WithMetrics(...)`); structured logging;
  `AddHealthChecks()` with separate liveness and readiness.
- **Mistakes**: `.Result` or `.Wait()` on tasks (thread starvation); a DbContext kept beyond its scope; no
  `CancellationToken` passed through; secrets in `appsettings.json` instead of user secrets or a vault.

## Java: Spring Boot and React

- **Layout**: `controller/`, `service/`, `repository/`, `domain/` under the base package; Flyway scripts in
  `src/main/resources/db/migration`; tests in `src/test/java`.
- **Commands**: `./mvnw -B verify` (or `./gradlew build`); formatting with Spotless where the project uses it.
- **Validation**: Jakarta Bean Validation (`@Valid`, constraints on DTOs); a `@RestControllerAdvice` that returns
  `ProblemDetail`.
- **Data**: Spring Data JPA; Flyway or Liquibase; `@Transactional` on service methods; `spring.jpa.open-in-view=false`.
- **Sign-in**: Spring Security OAuth2 resource server (JWT); `@PreAuthorize` for object-level rules.
- **Tests**: JUnit 5; `@WebMvcTest` and `@DataJpaTest` slices; `@SpringBootTest` with Testcontainers and
  `@ServiceConnection`.
- **Observability**: Micrometer with the OpenTelemetry bridge; Actuator health and metrics, exposed only what is needed.
- **Mistakes**: entities returned from controllers; Actuator endpoints open to the internet; N+1 from lazy collections.

## Go

- **Layout**: `cmd/<app>/main.go`, `internal/` packages by domain, `migrations/`.
- **Commands**: `go vet ./...` · `go test ./...` (add `-race` in CI) · `staticcheck ./...` where installed.
- **Building blocks**: `net/http` routing with method patterns (Go 1.22 and later) or chi; pgx with sqlc for typed
  queries; golang-migrate; `httptest` for handlers.
- **Mistakes**: no timeouts on `http.Server` and outbound clients; a goroutine without cancellation; errors wrapped
  without `%w` (lost for `errors.Is`).

## A new project with no house style

Pick the client's standard stack when there is one. Otherwise: Next.js with PostgreSQL for a web app with a team of
TypeScript developers; React and FastAPI when the work leans on Python or AI libraries; .NET or Spring where the
organisation runs them. State the choice and the one-line reason in the pull request.
