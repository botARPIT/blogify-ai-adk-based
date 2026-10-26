#!/usr/bin/env python3
"""Check live scrapes, persisted metrics, Grafana provisioning and panel queries."""

import argparse
import base64
import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_json(url, *, auth=None):
    request = Request(url)
    if auth:
        request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def verify(args):
    password = os.environ.get("GRAFANA_PASSWORD")
    if not password:
        raise RuntimeError("Set GRAFANA_PASSWORD in your shell for the Grafana checks")
    auth = os.environ.get("GRAFANA_USER", "admin") + ":" + password
    targets = read_json(args.prometheus + "/api/v1/targets")["data"]["activeTargets"]
    for job in ("blogify-api", "blogify-worker", "blogify-reaper"):
        matches = [target for target in targets if target["labels"].get("job") == job]
        required = args.workers if job == "blogify-worker" else 1
        if len(matches) < required or any(target["health"] != "up" for target in matches):
            errors = [target.get("lastError") for target in matches if target["health"] != "up"]
            raise RuntimeError(f"{job}: need {required} healthy targets; errors={errors}")
        print(f"PASS {job}: {len(matches)} healthy scrape targets")

    def query(expression):
        try:
            result = read_json(args.prometheus + "/api/v1/query?" + urlencode({"query": expression}))
        except HTTPError as exc:
            raise RuntimeError(f"PromQL failed: {expression}: {exc.read().decode()}") from exc
        if result["status"] != "success":
            raise RuntimeError(f"PromQL failed: {expression}")
        return result["data"]["result"]

    for metric in ("blog_sessions_by_status", "redis_queue_items", "database_connections"):
        if not query(metric + '{job="blogify-api"}'):
            raise RuntimeError(f"Missing runtime metric: {metric}")
    freshness = query('time() - runtime_metrics_refresh_success_timestamp_seconds{job="blogify-api"}')
    if not freshness or any(float(item["value"][1]) > 60 for item in freshness):
        raise RuntimeError("API runtime snapshots are missing or older than 60 seconds")
    print("PASS durable workflow, Redis and PostgreSQL metrics are fresh")

    health = read_json(args.grafana + "/api/health")
    if health.get("database") != "ok":
        raise RuntimeError("Grafana database is not healthy")
    for uid in ("prometheus", "tempo"):
        if uid == "tempo":
            # Grafana 10's Tempo plugin does not implement /health. Verify its
            # actual provisioned proxy path against Tempo's readiness endpoint.
            request = Request(args.grafana + "/api/datasources/proxy/uid/tempo/ready")
            request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
            with urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError("Tempo is not ready through the Grafana datasource")
            print("PASS Grafana datasource: tempo")
            continue
        health = read_json(args.grafana + f"/api/datasources/uid/{uid}/health", auth=auth)
        if health.get("status") != "OK":
            raise RuntimeError(f"Grafana datasource {uid}: {health}")
        print(f"PASS Grafana datasource: {uid}")

    dashboards = read_json(args.grafana + "/api/search?type=dash-db", auth=auth)
    titles = {item["title"] for item in dashboards}
    for title in ("API Golden Signals", "Backend Runtime and Generation"):
        if title not in titles:
            raise RuntimeError(f"Dashboard was not provisioned: {title}")
    expressions = set()
    for dashboard in dashboards:
        detail = read_json(args.grafana + "/api/dashboards/uid/" + dashboard["uid"], auth=auth)
        for panel in detail["dashboard"].get("panels", []):
            for target in panel.get("targets", []):
                expression = target.get("expr")
                if expression:
                    expressions.add(expression)
    for expression in sorted(expressions):
        query(expression)
    print(f"PASS {len(dashboards)} provisioned dashboards and {len(expressions)} PromQL queries")
    print("Model and worker outcome panels need generation activity to contain samples.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--grafana", default="http://localhost:3001")
    parser.add_argument("--workers", type=int, default=1, help="Minimum expected worker replicas")
    parser.add_argument("--wait", type=int, default=0, help="Retry for this many seconds during startup")
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait
    while True:
        try:
            verify(args)
            return
        except Exception as exc:
            if time.monotonic() >= deadline:
                parser.exit(1, f"FAIL {exc}\n")
            time.sleep(3)


if __name__ == "__main__":
    main()
