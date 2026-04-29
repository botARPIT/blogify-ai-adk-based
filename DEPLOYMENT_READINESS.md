# Deployment Readiness Checklist

## Product and feature readiness

- [ ] Local login works with cookie auth
- [ ] Logout clears the session cleanly
- [ ] Dashboard can create a session
- [ ] Progress page polls and routes correctly
- [ ] Outline review can revise and approve
- [ ] Final review can approve and request revision
- [ ] Final output renders markdown correctly
- [ ] Copy markdown works
- [ ] Notification bell updates and routes correctly
- [ ] Budget page loads
- [ ] Session detail page loads
- [ ] Safe user-facing errors are shown for failed requests

## Backend runtime readiness

- [ ] PostgreSQL is reachable from API and worker
- [ ] Redis is reachable from API and worker
- [ ] Google API key is configured
- [ ] Tavily API key is configured if research is enabled
- [ ] Worker is deployed alongside the API
- [ ] Health endpoints are used by probes
- [ ] Metrics exposure policy is defined
- [ ] Internal service API key is set if upstream integration is enabled

## Database and migration readiness

- [ ] Alembic is the schema source of truth
- [ ] `alembic upgrade head` runs successfully in the target environment
- [ ] Auth tables exist
- [ ] Notification tables exist
- [ ] Canonical session and version tables exist
- [ ] Migration rollout happens before API rollout
- [ ] Rollback strategy for schema changes is documented

## Security readiness

- [ ] JWT secret is set per environment
- [ ] Cookie `Secure=true` in production
- [ ] `SameSite` policy reviewed against domain topology
- [ ] CORS origins restricted to real frontend domains
- [ ] Public error responses do not expose traceback/details
- [ ] `/internal/ai/*` requires `X-Internal-Api-Key`
- [ ] Admin routes are disabled unless intentionally used

## Observability readiness

- [ ] API liveness probe uses `/api/health`
- [ ] Readiness probe uses `/api/health/ready`
- [ ] API 5xx alert threshold is defined
- [ ] Worker retry alert threshold is defined
- [ ] Queue backlog alert threshold is defined
- [ ] Database availability alert is defined
- [ ] Redis availability alert is defined
- [ ] Migration/schema mismatch startup alert is defined

## Frontend responsiveness and usability

- [ ] Dashboard validated at 1440px
- [ ] Dashboard validated at 1024px
- [ ] Dashboard validated at 768px
- [ ] Dashboard validated at 390px
- [ ] Notification panel is usable on narrow screens
- [ ] Login page is usable on short-height screens
- [ ] Output page is readable on mobile
- [ ] Long topic/audience values do not break layout
- [ ] Review actions are reachable and obvious on mobile
- [ ] Session refresh does not strand the user on the wrong route

## Documentation and runbooks

- [ ] Root README reflects the canonical routes
- [ ] Local setup guide is current
- [ ] Production runbook exists
- [ ] Upstream integration guide exists
- [ ] Manual QA checklist exists
- [ ] Incident checklist exists for auth, migrations, worker failure, and provider-key issues

## Deployment gate

Only deploy when all sections above are green and the manual QA checklist has passed.
