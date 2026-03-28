# Codebase Exploration: Thought Process Examples

These examples show the **internal reasoning** an expert coding agent uses when approaching
different tasks. Study the thought process, not the specific technology.

---

## Example 1: "Add a Feature to an Existing Codebase"

**User request**: "Add an AI-powered blog generation button to the create blog page."

### Expert Thought Process

```
STEP 1: What do I NOT know?
├── Where is the "create blog" page?
├── What editor does it use?
├── What does the existing blog creation flow look like?
├── Is there already any AI integration code?
├── What is the backend framework?
├── What database/ORM is used?
└── Are there existing patterns for service-to-service calls?

STEP 2: Explore wide → narrow
├── list_dir / → identify project structure (monorepo? separate)?
├── Read package.json/requirements.txt → identify tech stack
├── Read App.tsx/routes → identify the page routing
├── Read the "create blog" page → understand the current UI
├── Read the editor component → understand how content is managed
├── Read the backend routes → understand API surface area
├── Read the database schema → understand the data model
├── Search for "ai" or "generate" → find existing AI code
└── Read the config → find env vars and feature flags

STEP 3: Map the blast radius
├── Frontend: Publish page, new AI pages, hooks, types
├── Backend: New routes, services, client, types
├── Database: Schema migration for new models
├── Config: New environment variables
└── Tests: Existing test suite must still pass

STEP 4: Find patterns to follow
├── How are other mutation hooks structured? (useCreateBlog → follow that shape)
├── How are other pages structured? (Publish.tsx → follow that layout)
├── How does the backend validate requests? (Zod schemas → use same approach)
├── How does the backend handle errors? (handleError middleware → use same pattern)
└── How are routes mounted? (mainRouter.route() → follow same pattern)

STEP 5: Identify clarifying questions
├── Where will the AI service be deployed? (affects URL config)
├── Should the button disable when budget is exhausted? (UX decision)
├── Should content transfer via sessionStorage or API fetch? (architecture decision)
└── Do we need mock mode for development? (DX decision)

STEP 6: Only NOW plan the implementation
└── Group changes by component, ordered by dependency
```

### Anti-Pattern: What a Naive Agent Does

```
STEP 1: User said "add AI generation"
STEP 2: I know how AI APIs work, let me write code
STEP 3: Create a new file with my preferred patterns
STEP 4: Hope it works with the existing codebase
```

**Why this fails**: The agent doesn't know the project uses Hono, not Express. Uses `class` 
syntax when the codebase uses factory functions. Creates new types when compatible types 
already exist. Adds routes without knowing how routing is structured.

---

## Example 2: "Fix This Bug"

**User request**: "The budget calculation is showing wrong values."

### Expert Thought Process

```
STEP 1: Understand the symptom precisely
├── What values are shown?
├── What values are expected?
├── Is it always wrong, or only in certain conditions?
└── When did it start breaking? (recent change?)

STEP 2: Trace the data path
├── Where does the frontend display the budget? (find the component)
├── What API endpoint does it call? (find the hook/fetch)
├── What backend handler responds? (find the route → controller → service)
├── How is the value calculated? (find the repository query)
└── What data is in the database? (check the actual records)

STEP 3: Form hypotheses (ranked by likelihood)
├── H1: The query doesn't account for RELEASE entries (most likely — accounting bug)
├── H2: The frontend is displaying stale cached data
├── H3: Timezone mismatch in the "daily" calculation window
└── H4: Concurrent writes causing race conditions

STEP 4: Test hypotheses (cheapest test first)
├── Read the repository query → check if it handles all entry types
├── Check the query filter → is the date window correct?
├── Check the frontend cache invalidation → does it refetch after mutations?
└── Check for concurrent access patterns

STEP 5: Fix with minimal blast radius
├── Fix the specific line causing the issue
├── Verify the fix doesn't break the related code paths
├── Check if the same bug pattern exists elsewhere
└── Add a test case for this specific scenario
```

---

## Example 3: "Review This Code / Audit"

**User request**: "Is this backend production-ready?"

### Expert Thought Process

```
STEP 1: Define the audit dimensions
├── Security: auth, authz, input validation, secrets
├── Reliability: error handling, timeouts, retries, health checks
├── Observability: logging, metrics, tracing
├── Deployment: Docker, CI/CD, env config
└── Data: migrations, backup, consistency

STEP 2: For each dimension, check systematically
├── Security:
│   ├── Read auth middleware → check all routes are protected
│   ├── Read route handlers → check authorization (user A can't access user B's data)
│   ├── Read input handlers → check validation (Zod/Joi? raw body parsing?)
│   ├── Check for hardcoded secrets → grep for API keys, passwords
│   ├── Check CORS config → is it `*` or specific origins?
│   └── Check rate limiting → does it exist? per-user or global?
│
├── Reliability:
│   ├── Read error handlers → do they catch all exceptions?
│   ├── Read HTTP clients → do they have timeouts?
│   ├── Read database connections → is there pooling?
│   ├── Check shutdown handling → graceful or hard kill?
│   └── Check health endpoint → does it verify downstream dependencies?
│
└── [continue for each dimension...]

STEP 3: Categorize findings
├── CRITICAL: Security vulnerabilities, data loss risks
├── HIGH: Reliability gaps, missing error handling
├── MEDIUM: Observability gaps, deployment issues
└── LOW: Code quality, documentation

STEP 4: Present findings with actionable fixes
├── Each finding: what's wrong, why it matters, how to fix it
├── Group by dimension, ordered by severity
└── Give a clear "is it ready?" verdict with conditions
```

---

## Example 4: "Write Documentation"

### Expert Thought Process

```
STEP 1: Who is the audience?
├── Other developers on the team? → Technical, show code
├── New contributors? → Include setup steps, architecture overview  
├── API consumers? → Focus on endpoints, auth, examples
├── Hiring managers reading your GitHub? → Focus on design decisions

STEP 2: What's the minimum they need to know?
├── NOT how every function works
├── YES: architecture overview, how to run it, key design decisions
├── YES: what problems you solved and how
└── YES: what tradeoffs you made and why

STEP 3: Structure for scanning, not reading
├── Use tables for comparisons
├── Use code blocks for concrete examples
├── Use headers for navigation
├── Use diagrams for architecture
└── Keep paragraphs under 3 sentences
```
