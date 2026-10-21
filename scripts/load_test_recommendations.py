"""Small connection-pooled load test for the recommendation endpoints."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

QUERIES = (
    "사진 촬영을 배우고 전시회도 해보고 싶어",
    "프로그래밍과 AI 프로젝트를 하고 싶어",
    "밴드에서 작곡과 공연을 하고 싶어",
    "클라이밍과 등산을 하고 싶어",
    "헌혈과 지역 봉사를 하고 싶어",
    "보드게임을 즐기고 싶어",
    "여행하며 친구를 사귀고 싶어",
    "농구를 제대로 배우고 싶어",
)


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percent) - 1)
    return ordered[index]


def request_once(client: httpx.Client, index: int) -> tuple[float, bool]:
    started = time.perf_counter()
    try:
        response = client.post(
            "/api/v1/recommendations",
            json={"query": QUERIES[index % len(QUERIES)], "top_k": 5},
        )
        body = response.json()
        ok = response.status_code == 200 and isinstance(body.get("results"), list)
    except (httpx.HTTPError, ValueError):
        ok = False
    return (time.perf_counter() - started) * 1_000, ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1_000)
    args = parser.parse_args()

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    with (
        httpx.Client(base_url=args.base_url, timeout=15, limits=limits) as client,
        ThreadPoolExecutor(max_workers=args.concurrency) as executor,
    ):
        list(executor.map(lambda index: request_once(client, index), range(args.concurrency)))
        started = time.perf_counter()
        futures = [
            executor.submit(request_once, client, index)
            for index in range(args.requests)
        ]
        results = [future.result() for future in as_completed(futures)]

    durations = [duration for duration, _ in results]
    failures = sum(not ok for _, ok in results)
    elapsed = time.perf_counter() - started
    error_rate = failures / len(results)
    p95 = percentile(durations, 0.95)
    summary = {
        "requests": len(results),
        "concurrency": args.concurrency,
        "failures": failures,
        "error_rate": round(error_rate, 4),
        "requests_per_second": round(len(results) / elapsed, 2),
        "latency_ms": {
            "mean": round(statistics.fmean(durations), 2),
            "p50": round(percentile(durations, 0.50), 2),
            "p95": round(p95, 2),
            "p99": round(percentile(durations, 0.99), 2),
            "max": round(max(durations), 2),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(error_rate > args.max_error_rate or p95 > args.max_p95_ms)


if __name__ == "__main__":
    raise SystemExit(main())
