#!/usr/bin/env python3
"""Measure latency/error percentiles for a read-only HTTP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections.abc import Sequence

import httpx


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


async def run(args: argparse.Namespace) -> int:
    try:
        headers = json.loads(os.getenv("BLOGIFY_BENCH_HEADERS", "{}"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"BLOGIFY_BENCH_HEADERS must be a JSON object: {exc}") from exc
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        raise SystemExit("BLOGIFY_BENCH_HEADERS must be a JSON object of string keys and values")

    url = args.base_url.rstrip("/") + "/" + args.path.lstrip("/")
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    failures = 0
    completed = 0
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)

    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers=headers) as client:
        async def request_once() -> None:
            nonlocal failures, completed
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    elapsed = time.perf_counter() - started
                    latencies.append(elapsed)
                    completed += 1
                    if response.status_code < 200 or response.status_code >= 400:
                        failures += 1
                except httpx.HTTPError:
                    latencies.append(time.perf_counter() - started)
                    completed += 1
                    failures += 1

        for _ in range(args.warmup):
            await request_once()
        latencies.clear()
        failures = 0
        completed = 0
        started = time.perf_counter()
        await asyncio.gather(*(request_once() for _ in range(args.requests)))
        elapsed = time.perf_counter() - started

    report = {
        "url": url,
        "requests": completed,
        "failures": failures,
        "error_rate": failures / completed if completed else 1.0,
        "duration_seconds": round(elapsed, 3),
        "throughput_rps": round(completed / elapsed, 2) if elapsed else 0,
        "latency_ms": {
            "min": round(min(latencies, default=0) * 1000, 2),
            "mean": round(statistics.fmean(latencies) * 1000, 2) if latencies else 0,
            "p50": round(percentile(latencies, 0.50) * 1000, 2),
            "p95": round(percentile(latencies, 0.95) * 1000, 2),
            "p99": round(percentile(latencies, 0.99) * 1000, 2),
            "max": round(max(latencies, default=0) * 1000, 2),
        },
    }
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--path", default="/api/health", help="Read-only endpoint path")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if min(args.requests, args.concurrency) < 1 or args.warmup < 0:
        parser.error("requests/concurrency must be positive and warmup cannot be negative")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
