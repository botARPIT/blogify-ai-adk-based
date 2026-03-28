# Codebase Exploration Checklist

Use this checklist when approaching ANY codebase for the first time. Complete it
before writing any code. Each item reveals critical context that prevents mistakes.

---

## 1. Project Structure (2 minutes)

- [ ] List the root directory → monorepo or single project?
- [ ] Identify `backend/` vs `frontend/` vs shared code
- [ ] Check for `docs/`, `scripts/`, `tests/`, `.github/` directories
- [ ] Look for config files: `docker-compose.yml`, `Dockerfile`, CI config

## 2. Tech Stack (3 minutes)

- [ ] Read `package.json` / `requirements.txt` / `go.mod` / `Cargo.toml`
- [ ] Identify the framework (Express, Hono, FastAPI, Django, Gin, etc.)
- [ ] Identify the ORM (Prisma, SQLAlchemy, GORM, TypeORM, etc.)
- [ ] Identify the test framework (Jest, Vitest, Pytest, etc.)
- [ ] Identify key libraries (auth, validation, HTTP client, etc.)

## 3. Entry Points (3 minutes)

- [ ] Find and read the main application file (where the app bootstraps)
- [ ] Find and read the route registration (how routes are mounted)
- [ ] Find and read the middleware stack (what runs on every request)
- [ ] For frontend: read `App.tsx` or equivalent (routing, providers, layout)

## 4. Configuration (2 minutes)

- [ ] Read `.env.example` or equivalent → what env vars exist?
- [ ] Read the config loader → how are env vars validated and typed?
- [ ] Check `wrangler.toml/jsonc` / `vercel.json` / platform-specific config
- [ ] Note which values have defaults vs which are required

## 5. Data Layer (3 minutes)

- [ ] Read the database schema (`schema.prisma`, migrations, models)
- [ ] Identify the key entities and their relationships
- [ ] Check for indexes, constraints, and cascade behavior
- [ ] Note any enums or custom types

## 6. Authentication & Authorization (2 minutes)

- [ ] How does auth work? (JWT cookies, Bearer tokens, API keys, OAuth)
- [ ] What middleware enforces auth?
- [ ] How is the user identity attached to the request?
- [ ] Are there role-based or resource-based permissions?

## 7. Existing Patterns (3 minutes)

- [ ] Pick 2-3 existing features and trace their full stack:
      Route → Controller → Service → Repository → Database
- [ ] Note naming conventions (camelCase vs snake_case, file naming)
- [ ] Note code organization (classes vs functions, factories, dependency injection)
- [ ] Note error handling patterns (middleware vs try/catch, error types)

## 8. Test Structure (2 minutes)

- [ ] Where do tests live? Same directory or separate tree?
- [ ] What testing patterns are used? (mocks, fixtures, factories)
- [ ] What's the test runner command? (`npm test`, `pytest`, etc.)
- [ ] Are there different levels? (unit, integration, e2e)

## 9. Deployment (2 minutes)

- [ ] How is this deployed? (Docker, serverless, PaaS, etc.)
- [ ] Is there a CI/CD pipeline? Read `.github/workflows/` or equivalent
- [ ] Are there deployment scripts?
- [ ] What environment differences exist (dev vs staging vs prod)?

## 10. Existing TODOs / Known Issues (1 minute)

- [ ] `grep -r "TODO\|FIXME\|HACK\|XXX" src/` → what's known-broken?
- [ ] Check `README.md` for known limitations
- [ ] Check issues tracker / PR descriptions for context

---

## Total Time: ~23 minutes of reading

This investment saves **hours** of rework. A model that skips this step will write code
that technically works but doesn't fit the codebase — requiring a rewrite that takes
longer than the exploration would have.
