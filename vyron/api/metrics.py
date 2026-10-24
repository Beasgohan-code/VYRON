# ---------------------------------------------------------------------------
#  VYRON API — in-process metrics
#
#  Lightweight, dependency-free counters that answer "is the API healthy?"
#  without a Prometheus stack: request totals by route/status, download volume,
#  latency percentiles over the last 500 calls, uptime.
#
#  Exposed at GET /v1/metrics as JSON, or Prometheus text with
#  `?format=prometheus` (or `Accept: text/plain`).
# ---------------------------------------------------------------------------
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    requests: Counter = field(default_factory=Counter)  # "route|status" → count
    routes: Counter = field(default_factory=Counter)  # route → count
    errors: Counter = field(default_factory=Counter)  # code → count
    latencies: list[float] = field(default_factory=list)  # ms, last 500
    downloads: int = 0
    bytes_served: int = 0
    rate_limited: int = 0

    # ── recording ──────────────────────────────────────────────────────────
    def observe(self, route: str, status: int, elapsed_ms: float, *, code: str = "") -> None:
        label = route or "unknown"
        self.requests[f"{label}|{status}"] += 1
        self.routes[label] += 1
        self.latencies.append(round(max(0.0, elapsed_ms), 2))
        del self.latencies[:-500]
        if code:
            self.errors[code] += 1
        if status == 429:
            self.rate_limited += 1

    def note_download(self, size: int) -> None:
        self.downloads += 1
        self.bytes_served += max(0, int(size))

    # ── reporting ──────────────────────────────────────────────────────────
    def _percentile(self, value: float) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, max(0, int(round((value / 100) * len(ordered))) - 1))
        return ordered[index]

    def snapshot(self) -> dict:
        total = sum(self.requests.values())
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "requests": total,
            "downloads": self.downloads,
            "bytes_served": self.bytes_served,
            "rate_limited": self.rate_limited,
            "latency_ms": {
                "avg": round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else 0.0,
                "p50": self._percentile(50),
                "p95": self._percentile(95),
                "p99": self._percentile(99),
            },
            "by_status": {
                code: sum(count for key, count in self.requests.items() if key.endswith(f"|{code}"))
                for code in sorted({key.rsplit("|", 1)[-1] for key in self.requests})
            },
            "top_routes": [
                {"route": route, "hits": hits}
                for route, hits in self.routes.most_common(12)
            ],
            "errors": dict(self.errors),
        }

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = [
            "# HELP vyron_api_requests_total Total HTTP requests handled by the music API.",
            "# TYPE vyron_api_requests_total counter",
            f"vyron_api_requests_total {snap['requests']}",
            "# HELP vyron_api_downloads_total Track downloads served.",
            "# TYPE vyron_api_downloads_total counter",
            f"vyron_api_downloads_total {snap['downloads']}",
            "# HELP vyron_api_bytes_served_total Audio bytes streamed.",
            "# TYPE vyron_api_bytes_served_total counter",
            f"vyron_api_bytes_served_total {snap['bytes_served']}",
            "# HELP vyron_api_rate_limited_total Requests rejected by the rate limiter.",
            "# TYPE vyron_api_rate_limited_total counter",
            f"vyron_api_rate_limited_total {snap['rate_limited']}",
            "# HELP vyron_api_uptime_seconds Process uptime.",
            "# TYPE vyron_api_uptime_seconds gauge",
            f"vyron_api_uptime_seconds {snap['uptime_seconds']}",
            "# HELP vyron_api_request_duration_ms Request latency percentiles.",
            "# TYPE vyron_api_request_duration_ms gauge",
            f'vyron_api_request_duration_ms{{quantile="0.5"}} {snap["latency_ms"]["p50"]}',
            f'vyron_api_request_duration_ms{{quantile="0.95"}} {snap["latency_ms"]["p95"]}',
            f'vyron_api_request_duration_ms{{quantile="0.99"}} {snap["latency_ms"]["p99"]}',
        ]
        for route, hits in self.routes.items():
            safe = route.replace('"', "")
            lines.append(f'vyron_api_route_requests_total{{route="{safe}"}} {hits}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()

__all__ = ["METRICS", "Metrics"]
