# Observability verification — 2026-10-26

Verified locally with isolated Docker Compose projects for development and
production, using disposable PostgreSQL/Redis data and two worker replicas.
The AWS GitHub workflow was disabled before publishing changes.

| Check | Result |
| --- | --- |
| Backend tests with real PostgreSQL/Redis configured | 254 passed; 1 opt-in Redis stress test skipped |
| Fresh database migrations | All migrations applied successfully |
| Frontend | TypeScript check and Vite production build passed |
| Python | Ruff, compilation and diff whitespace checks passed |
| Prometheus | Pinned image's `promtool check config` passed; API, reaper and both workers UP |
| Grafana | Both datasource paths reachable; five dashboards provisioned; all 39 PromQL queries execute |
| Metrics authentication | Missing/incorrect bearer token rejected; correct token accepted |
| Durable workflow metrics | Real API/DB/queue tests verify outline review, final review, COMPLETED and FAILED states |
| ADK metrics | SDK span tests verify model outcomes/tokens and agent invocation metrics |
| Trace delivery | API request trace exported through Collector and retrieved from Tempo through Grafana |
| Production reverse proxy | HTTP routing to API readiness passed using a local test hostname |

The lifecycle tests script the provider-facing executor. They exercise real
HTTP, PostgreSQL transactions, Redis queue operations, ownership claims, human
review transitions and metric updates without paid model/research requests.
The ADK editor test separately runs a deterministic fake LLM and verifies stored
events. Live model quality, provider credentials and external provider behavior
were not validated by these checks.

An unsupported Prometheus startup flag, token substitution, missing local trace
services, database readiness SQL and uptime initialization were corrected during
verification. Upstream rate limiting and ledger-based budget reconciliation were
retained during the merge with main and tested with the refactored workflow.

This is local runtime evidence. Azure infrastructure, DNS, public ACME HTTPS,
remote backups, cloud identities and resource sizing require validation in an
Azure account. The [Azure VM runbook](../runbooks/azure-vm.md) contains the deploy,
upgrade, rollback and SSH access commands. The single-VM deployment is not highly
available.
