# Deploy Blogify on an Azure Linux VM

This is a Docker Compose deployment on one Azure VM. It runs the API, background
workers, reaper, PostgreSQL, Redis, Prometheus, Grafana, Tempo and the OpenTelemetry
Collector. HTTPS certificates are managed by nginx-proxy and ACME. The frontend
can continue to run on Vercel; set its `VITE_API_BASE_URL` to the API's HTTPS URL.

Compose on a single server is a documented Docker production pattern:
https://docs.docker.com/compose/how-tos/production/ . This setup is suitable for a
small deployment. It has one host as a failure boundary; it is not highly
available. For a managed deployment with independent scaling, use Azure Container
Apps with managed PostgreSQL, Azure Managed Redis, ACR managed identity and a
separate metrics collection design. Compose service names and local disk volumes
must not be copied unchanged into Container Apps.

## One-time Azure and host setup

1. Create an Ubuntu 24.04 LTS VM with a static public IP and persistent managed disk.
   Start with 4 vCPUs, 8 GiB RAM and at least 64 GiB disk for the build plus the
   monitoring stack; size from actual traffic. Azure VM creation is documented at
   https://learn.microsoft.com/en-us/azure/virtual-machines/linux/quick-create-cli .
2. Allow inbound TCP 80 and 443. Restrict SSH (22) to your workstation's public IP.
   Leave PostgreSQL, Redis, worker metrics, Prometheus, Grafana, Tempo and OTLP
   ports closed in the Azure network security group.
3. Point the API domain's DNS A record to the VM IP. Install Docker Engine and the
   Compose plugin using https://docs.docker.com/engine/install/ubuntu/ .
4. On the VM, clone the repository and prepare the environment from its root:

   ```bash
   git clone https://github.com/botARPIT/blogify-ai-adk-based.git
   cd blogify-ai-adk-based
   cp .env.prod.example .env.prod
   chmod 600 .env.prod
   ```

   Edit `.env.prod`: set domain, certificate email, exact frontend CORS origin,
   provider keys, and independent random secrets. `openssl rand -hex 32` generates
   one secret. The password in `DATABASE_URL` must match `POSTGRES_PASSWORD`.
   The API and worker provider settings are shared by Compose. Production metrics
   require the bearer token; browser API authentication uses JWT cookies.

## Deploy

From the repository root:

```bash
docker compose --env-file .env.prod -f backend/docker-compose.prod.yml up -d --build --wait
```

The same backend image is built for API, workers and migration service. The
one-shot `migrate` service must finish successfully before API, workers or reaper
start. PostgreSQL, Redis, Grafana, Prometheus, Tempo and certificates use named
volumes. Only the reverse proxy publishes public ports 80/443. Prometheus and
Grafana bind to VM loopback for SSH access.

Check application health and processes:

```bash
docker compose --env-file .env.prod -f backend/docker-compose.prod.yml ps -a
curl --fail https://api.example.com/api/health/ready
docker compose --env-file .env.prod -f backend/docker-compose.prod.yml logs --tail=100 migrate api worker reaper prometheus grafana otel-collector tempo
```

Initial HTTPS issuance requires public DNS and ports 80/443 to reach the VM.
`--wait` checks container startup and configured application health checks; use
the metric checks below to confirm the complete monitoring path.

## View production metrics on your local machine

Run on your workstation (choose free local ports):

```bash
ssh -N -L 13001:127.0.0.1:3000 -L 19090:127.0.0.1:9090 azureuser@YOUR_VM_IP
```

Open Grafana at http://localhost:13001 and Prometheus at http://localhost:19090 .
Log into Grafana with `GRAFANA_USER` and `GRAFANA_PASSWORD` from the VM's env file.
The Prometheus datasource already queries the VM's Prometheus; no production
metrics ports need to be exposed publicly or scraped by a local Prometheus.

In Prometheus `/targets`, all API, worker and reaper targets must be UP. Query
`up`, `blog_sessions_by_status`, `redis_queue_items`, and `workers_active`.
Open Grafana's **Blogify** folder and the **API Golden Signals** and **Backend
Runtime and Generation** dashboards. New counters and duration panels need
application activity; a successful scrape alone does not generate model calls.

For a scripted check, with the SSH tunnel running and the Grafana credentials
available in your local shell:

```bash
python3 backend/scripts/check-observability.py --prometheus http://localhost:19090 --grafana http://localhost:13001
```

See [observability](../backend/observability.md) for metric meanings and trace access.

## Upgrade, scale and roll back

For reproducible releases, set `BACKEND_IMAGE` in `.env.prod` to an immutable tag
such as `blogify-backend:<git-commit>` (or an ACR image name). Keep the previous
image tag. After updating the checkout and tag, run the deploy command again.
Alternatively build and push the image in CI and use `docker compose pull` plus
`up -d --no-build --wait` on the VM. ACR stores images; the VM runs containers.

Scale workers with:

```bash
docker compose --env-file .env.prod -f backend/docker-compose.prod.yml up -d --no-build --scale worker=3
```

Prometheus resolves every worker replica through Docker DNS. Each process has
its own metrics endpoint; durable session counts remain PostgreSQL snapshots.
For an application rollback, restore the previous image tag and run `up -d
--no-build --wait`. Database migrations remain applied; check compatibility before
rolling back code, and use a tested backup restore if a schema rollback is needed.

## Backups and operations

Schedule PostgreSQL logical backups, encrypt them and copy them off the VM (for
example to Azure Blob Storage using the VM's managed identity). Verify restoration
periodically. A minimal manual dump from the repository root is:

```bash
docker compose --env-file .env.prod -f backend/docker-compose.prod.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > blogify-backup.sql
```

Named volumes persist container replacements. `docker compose down -v` deletes
those volumes and must not be used for a routine update. Configure Azure VM disk
and host monitoring and log retention. TLS, DNS, Azure firewall rules, remote
backups and real provider calls need validation in your Azure account.

The legacy `.github/workflows/deploy.yml` is disabled and has no push or
`workflow_run` trigger. Merging to main runs CI and its image publishing job;
it performs no AWS or Azure runtime deployment. Azure deployment is the explicit
Compose command above.
