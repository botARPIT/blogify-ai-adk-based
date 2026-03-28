# Critical Anti-Patterns

These are the patterns that produce the worst output quality. A model following these 
anti-patterns will produce code that looks correct but breaks in production, doesn't 
integrate with the codebase, or solves the wrong problem.

---

## 1. The Tutorial Transplant

**What it looks like**: Taking a pattern from a tutorial or training data and dropping it 
into the codebase without adapting it to the existing conventions.

```
Codebase uses: factory functions, Hono, Zod
Agent writes:  Express-style middleware classes, Joi validation

Codebase uses: snake_case API fields
Agent writes:  camelCase fields

Codebase uses: repository pattern
Agent writes:  raw SQL in the route handler
```

**Why it's catastrophic**: The code works in isolation but clashes with everything around 
it. Other developers will think it was written by someone who didn't read the codebase.

**Fix**: ALWAYS find an existing similar pattern FIRST. Copy its structure. Adapt it.

---

## 2. The Over-Eager Refactor

**What it looks like**: The user asks to add a button. The agent restructures 3 files, 
renames 2 functions, and "improves" the code style of adjacent lines.

```
User asked:  "Add a loading spinner to the submit button"
Agent did:   Refactored the form component, extracted a custom hook, 
             renamed 4 variables, and also added the spinner
```

**Why it's damaging**: The diff becomes unreadable. The PR review is 10x harder. 
Regressions hide in the unnecessary changes.

**Fix**: Change ONLY what the task requires. If you see something worth refactoring, 
note it but don't do it unless asked.

---

## 3. The Assumption Cascade

**What it looks like**: The agent encounters an ambiguous requirement, makes an assumption, 
then builds 5 more decisions on top of that assumption — creating a tower of guesses.

```
User: "Add caching"
Agent assumes: Redis (not Cloudflare KV, not in-memory)
Agent assumes: 1 hour TTL (not configurable)
Agent assumes: Cache everything (not selective)
Agent assumes: No invalidation strategy needed
Result: 200 lines of code built on 4 wrong assumptions
```

**Why it's wasteful**: When the first assumption is wrong, everything downstream is wasted 
work. And the user has to untangle which parts to keep.

**Fix**: Ask clarifying questions BEFORE writing code. Batch all questions into one ask.

---

## 4. The Happy Path Hero

**What it looks like**: The code handles the success case beautifully but crashes on 
any error, null value, or edge case.

```typescript
// Agent writes:
const user = await getUser(id);
return user.name;  // What if user is null?

// Agent writes:
const response = await fetch(url);
const data = await response.json();  // What if response is not ok?
return data.result;  // What if data.result is undefined?
```

**Why it's dangerous**: This code passes unit tests with mock data but fails in production 
with real users, network errors, and race conditions.

**Fix**: For EVERY external call or data access, handle: null, error, timeout, unexpected shape.

---

## 5. The Config Hardcoder

**What it looks like**: URLs, API keys, timeouts, and environment-specific values embedded 
directly in the code.

```typescript
// Agent writes:
const AI_URL = "http://localhost:8000";  // Hardcoded
const TIMEOUT = 30000;                   // Magic number
const API_KEY = "sk-abc123...";          // Secret in code

// Should write:
const AI_URL = config.BLOGIFY_AI_URL;
const TIMEOUT = config.AI_REQUEST_TIMEOUT;
// API key from environment variable
```

**Why it fails**: Works in development, breaks in staging, leaks secrets in production.

**Fix**: Every value that differs between environments goes into configuration. Add it to 
`.env.example` with a description.

---

## 6. The Silent Failure

**What it looks like**: Errors are caught but nothing meaningful happens.

```typescript
// Agent writes:
try {
  await saveToDatabase(data);
} catch (error) {
  console.log(error);  // Logged and... ignored
}
// Code continues as if save succeeded

// Should write:
try {
  await saveToDatabase(data);
} catch (error) {
  logger.error("Failed to save data", { error, data_id: data.id });
  throw new InternalServerError("Save failed", { cause: error });
}
```

**Why it's dangerous**: The system appears to work but data is silently lost. Users see 
success messages for operations that failed.

**Fix**: Every catch block must either: (a) handle the error meaningfully, (b) rethrow, 
or (c) return an explicit error response. Never swallow errors.

---

## 7. The Schema Ignorer

**What it looks like**: Making database queries or API calls without checking the actual 
schema of the data being queried.

```
Agent needs to query users with their blogs.
Agent writes: SELECT * FROM users JOIN blogs ON users.id = blogs.user_id
Actual schema: blogs.authorId (not user_id), UUID type (not integer)
Result: Query fails silently or returns empty results.
```

**Why it breaks**: The agent assumed column names, types, or relationships instead of 
reading the schema.

**Fix**: ALWAYS read `schema.prisma`, migration files, or ORM models BEFORE writing 
any database-related code.

---

## 8. The Context Amnesiac

**What it looks like**: The agent reads 10 files, understands the codebase, then writes 
code that contradicts what it just read.

```
Agent reads: AuthMiddleware uses cookie-based JWT auth
Agent writes: A new endpoint with Bearer token auth (different pattern)

Agent reads: The codebase has a NotificationService
Agent writes: A new inline notification system from scratch
```

**Why it produces bad code**: The agent has the context but doesn't use it. This is the 
most wasteful anti-pattern — the research was done for nothing.

**Fix**: Before writing each file, re-state (internally) the relevant patterns found 
during research. Cross-reference against what you're about to write.
