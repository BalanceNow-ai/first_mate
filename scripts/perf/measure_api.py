#!/usr/bin/env python3
"""Latency measurement against the local stack (through the nginx proxy).

Reports p50/p95/p99 per endpoint for N requests at concurrency C. Uses a real GoTrue
session (confirmation via Mailpit) for authenticated endpoints. The results describe the
stated local environment only — they are not production performance evidence.

Usage: python3 scripts/perf/measure_api.py [--requests 300] [--concurrency 10] [--only search]

Search is rate limited per client address (RATE_LIMIT_SEARCH_PER_MINUTE, default 120):
measure it with --only search --requests 100 in a fresh minute, or 429s dominate.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "e2e"))
from api_journey import Stack, anon_key  # noqa: E402


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round(p / 100 * (len(values) - 1)))))
    return values[k]


async def run(url: str, headers: dict, n: int, c: int) -> tuple[list[float], int]:
    sem = asyncio.Semaphore(c)
    lat: list[float] = []
    errors = 0
    async with httpx.AsyncClient(timeout=30) as client:
        async def one():
            nonlocal errors
            async with sem:
                t = time.perf_counter()
                r = await client.get(url, headers=headers)
                lat.append((time.perf_counter() - t) * 1000)
                if r.status_code >= 400:
                    errors += 1
        for _ in range(5):  # warm-up
            await client.get(url, headers=headers)
        await asyncio.gather(*(one() for _ in range(n)))
    return lat, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:18080")
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--only", default="", help="substring filter on endpoint names")
    a = ap.parse_args()
    s = Stack(a.base, a.mailpit, anon_key(os.environ["SUPABASE_JWT_SECRET"]))
    email, pw = f"perf-{uuid.uuid4().hex[:8]}@example.test", f"Pw-{uuid.uuid4().hex}"
    s.auth("signup", {"email": email, "password": pw})
    s.http.get(s.confirmation_link(email), follow_redirects=False)
    tok = s.auth("token", {"email": email, "password": pw}, grant_type="password").json()["access_token"]
    s.api("POST", "/auth/provision", tok, json={})
    v = s.api("POST", "/vessels/", tok, json={"nickname": "Perf", "make": "Stabicraft", "model": "2050 Supercab",
                                               "year": 2021, "engine_make": "Yamaha", "engine_model": "F150"}).json()
    prod = s.api("GET", "/products/", params={"limit": 1}).json()["items"][0]
    auth = {"Authorization": f"Bearer {tok}"}
    api = f"{a.base}/api/v1"
    cases = [
        ("GET /products (public, page 24)", f"{api}/products/?limit=24", {}, 200),
        ("GET /products (vessel, compatible_only)", f"{api}/products/?vessel_id={v['id']}&compatible_only=true&limit=24", auth, 200),
        ("GET /products/{id}", f"{api}/products/{prod['id']}", {}, 200),
        ("GET /search/products?q=filter", f"{api}/search/products?q=filter&limit=24", {}, 100),
        ("GET /search/products?q=filter (vessel)", f"{api}/search/products?q=filter&vessel_id={v['id']}&limit=24", auth, 100),
        ("GET /cart", f"{api}/cart/", auth, 200),
        ("GET /vessels", f"{api}/vessels/", auth, 200),
        ("GET /orders", f"{api}/orders/", auth, 200),
        ("GET /loyalty/points", f"{api}/loyalty/points", auth, 200),
    ]
    print(f"requests={a.requests} concurrency={a.concurrency} base={a.base}")
    print(f"{'endpoint':45} {'p50':>7} {'p95':>7} {'p99':>7} {'target':>7} {'err':>4}  result")
    failed = 0
    for name, url, headers, target in cases:
        if a.only and a.only not in name:
            continue
        lat, err = asyncio.run(run(url, headers, a.requests, a.concurrency))
        p95 = pct(lat, 95)
        ok = p95 < target and err == 0
        failed += not ok
        print(f"{name:45} {statistics.median(lat):7.1f} {p95:7.1f} {pct(lat, 99):7.1f} {target:7d} {err:4d}  {'PASS' if ok else 'MISS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
