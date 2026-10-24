# ---------------------------------------------------------------------------
#  Host telemetry ported from ShizuMusic's /stats card (MIT).
# ---------------------------------------------------------------------------
from __future__ import annotations

from vyron.ui import cards
from vyron.utils import sysinfo


def test_snapshot_is_json_safe_without_psutil(monkeypatch):
    monkeypatch.setattr(sysinfo, "psutil", None)
    snap = sysinfo.snapshot()
    assert snap["python"]
    assert snap["cpu_percent"] is None
    assert isinstance(snap["os"], str)
    assert sysinfo.summary_line(snap) in {"n/a"} or "cpu" in sysinfo.summary_line(snap)


def test_snapshot_with_psutil_reports_host_usage(monkeypatch):
    class _Freq:
        current = 2400.0

    class _Mem:
        total = 8 * 1024 ** 3
        used = 2 * 1024 ** 3
        percent = 25.0

    class _Disk:
        total = 100 * 1024 ** 3
        used = 40 * 1024 ** 3
        percent = 40.0

    class _Psutil:
        @staticmethod
        def cpu_percent(interval=None):
            return 12.5

        @staticmethod
        def cpu_freq():
            return _Freq()

        @staticmethod
        def cpu_count(logical=True):
            return 8 if logical else 4

        @staticmethod
        def virtual_memory():
            return _Mem()

        @staticmethod
        def disk_usage(_path):
            return _Disk()

    monkeypatch.setattr(sysinfo, "psutil", _Psutil)
    snap = sysinfo.snapshot()
    assert snap["cpu_percent"] == 12.5
    assert snap["cpu_freq_mhz"] == 2400
    assert snap["cores_physical"] == 4
    assert snap["ram_total_gb"] == 8.0
    assert snap["disk_percent"] == 40.0
    assert "cpu 12.5%" in sysinfo.summary_line(snap)


def test_snapshot_survives_a_broken_psutil(monkeypatch):
    class _Broken:
        @staticmethod
        def cpu_percent(interval=None):
            raise RuntimeError("no /proc")

    monkeypatch.setattr(sysinfo, "psutil", _Broken)
    snap = sysinfo.snapshot()
    assert snap["cpu_percent"] is None
    assert snap["python"]


def test_stats_card_renders_the_system_block():
    markup = cards.stats_card(
        uptime=60,
        chats=1,
        active=0,
        tracks=3,
        downloads=1,
        cache_bytes=0,
        backend="json",
        version="1.3.0",
        system={
            "os": "Linux",
            "release": "6.1",
            "python": "3.11.9",
            "cpu_percent": 18.0,
            "cores_logical": 2,
            "ram_used_gb": 1.5,
            "ram_total_gb": 4.0,
            "ram_percent": 37.5,
            "disk_used_gb": 10.0,
            "disk_total_gb": 40.0,
            "disk_percent": 25.0,
            "loadavg": 0.5,
        },
    )
    assert "18.0%" in markup
    assert "2c" in markup
    assert "1.5 / 4.0 GB" in markup
    assert "Linux 6.1" in markup


def test_stats_card_skips_the_block_without_telemetry():
    markup = cards.stats_card(
        uptime=1, chats=0, active=0, tracks=0, downloads=0,
        cache_bytes=0, backend="json", version="1.3.0", system=None,
    )
    assert "CPU" not in markup
