# Observability

Blogify emits structured JSON logs to stdout, Prometheus metrics from `/metrics`,
and OpenTelemetry traces from the API, worker, and reaper. Grafana queries
Prometheus for metrics, Elasticsearch for logs, and Tempo for traces.

## Production Docker Compose

The production Compose stack includes Tempo, an OpenTelemetry Collector, and
Filebeat. The Collector receives OTLP over the private Compose network and
forwards traces to Tempo. Filebeat reads the Linux Docker JSON log files through
a read-only host mount and forwards them to Elasticsearch over verified TLS.
Grafana is provisioned with all three data sources. A `trace_id` field in a log
entry links to the corresponding Tempo trace.

Set these values in the deployment secret store before starting the stack:

- `ELASTICSEARCH_URL`: HTTPS URL for the Elasticsearch cluster.
- `ELASTICSEARCH_FILEBEAT_USERNAME` and `ELASTICSEARCH_FILEBEAT_PASSWORD`: a
  dedicated Filebeat writer account.
- `ELASTICSEARCH_GRAFANA_USERNAME` and `ELASTICSEARCH_GRAFANA_PASSWORD`: a
  read-only account for Grafana.
- `METRICS_BEARER_TOKEN`: a random token shared by the API and Prometheus.

Use Elasticsearch index lifecycle management to cap log retention and disk
usage. Keep Elasticsearch, Tempo, the Collector, Prometheus, and Grafana off
public host ports; the production Compose file exposes only the existing web
proxy ports.

## Azure runtime note

The Filebeat service in `docker-compose.prod.yml` is for a Linux Docker host. It
reads `/var/lib/docker/containers`, so it fits Azure VM hosting with Docker
Compose. AKS needs a node-level Filebeat DaemonSet configured for the cluster's
container log paths. Managed container platforms need their platform log export
or a supported collector integration instead of this host mount. The app-side
OTLP instrumentation and Collector/Tempo configuration remain reusable.

For AKS, set the Collector receiver address to a private in-cluster endpoint and
store Tempo data in durable object storage before using this as a production
trace backend. The included local filesystem Tempo storage is a starter setup,
not a highly available distributed deployment.

## Local Compose usage

From `backend/`, combine the base services and local app definition:

```bash
docker compose -f docker-compose.base.yml -f docker-compose.local.yml up -d
```

This starts a single-node, unauthenticated Elasticsearch container for local
development only. It has no published host port. Filebeat reads Docker
`json-file` logs from a Linux host. Do not reuse production credentials for
local work.
