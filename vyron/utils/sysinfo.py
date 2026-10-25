# ---------------------------------------------------------------------------
#  VYRON — host telemetry for /stats
#  The /stats card. psutil is optional: every value
#  degrades to None so a minimal install still renders the card.
# ---------------------------------------------------------------------------
from __future__ import annotations

import os
import platform
import sys
from functools import lru_cache

try:  # pragma: no cover - exercised through the fallbacks in tests
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


@lru_cache(maxsize=2)
def _platform() -> dict[str, str]:
    return {
        "os": platform.system() or "unknown",
        "release": platform.release() or "",
        "python": sys.version.split()[0],
        "arch": platform.machine() or "",
    }


def _gb(value: float | int | None) -> float | None:
    return None if value is None else round(value / (1024 ** 3), 2)


def snapshot(*, interval: float | None = None) -> dict[str, object]:
    """Return a small, JSON-safe dict describing the host.

    `interval=None` (the default) asks psutil for the CPU percentage since the
    last call — it never blocks the event loop. Pass a number only in a
    throwaway script where a one-second sample is acceptable.
    """
    info: dict[str, object] = dict(_platform())
    info.update(
        {
            "cpu_percent": None,
            "cpu_freq_mhz": None,
            "cores_physical": None,
            "cores_logical": None,
            "ram_total_gb": None,
            "ram_used_gb": None,
            "ram_percent": None,
            "disk_total_gb": None,
            "disk_used_gb": None,
            "disk_percent": None,
            "loadavg": None,
        }
    )
    try:
        load = os.getloadavg()
        info["loadavg"] = round(load[0], 2)
    except Exception:
        pass
    if psutil is None:
        return info
    try:
        info["cpu_percent"] = round(psutil.cpu_percent(interval=interval), 1)
        freq = psutil.cpu_freq()
        if freq:
            info["cpu_freq_mhz"] = int(freq.current)
        info["cores_physical"] = psutil.cpu_count(logical=False)
        info["cores_logical"] = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()
        info["ram_total_gb"] = _gb(ram.total)
        info["ram_used_gb"] = _gb(ram.used)
        info["ram_percent"] = round(ram.percent, 1)
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = _gb(disk.total)
        info["disk_used_gb"] = _gb(disk.used)
        info["disk_percent"] = round(disk.percent, 1)
    except Exception:  # pragma: no cover - containers can hide /proc
        pass
    return info


def summary_line(info: dict[str, object] | None = None) -> str:
    """One-line `cpu · ram · disk` string for compact cards / health JSON."""
    info = info or snapshot()
    parts: list[str] = []
    if info.get("cpu_percent") is not None:
        parts.append(f"cpu {info['cpu_percent']}%")
    if info.get("ram_percent") is not None:
        parts.append(f"ram {info['ram_percent']}%")
    if info.get("disk_percent") is not None:
        parts.append(f"disk {info['disk_percent']}%")
    return " · ".join(parts) or "n/a"
