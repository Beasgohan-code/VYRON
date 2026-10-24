"""The nightly live check is a tool, and a tool that silently stops checking is
worse than no tool — so its plumbing is tested offline with fake probes."""
from __future__ import annotations

import asyncio

from vyron.tools import livecheck


def _run(probes):
    async def scenario():
        checks = []
        for name, probe, critical in probes:
            checks.append(await livecheck._timed(name, probe(), critical=critical))
        return checks

    return asyncio.run(scenario())


def test_a_healthy_probe_reports_ok():
    async def fine():
        return "3 results"

    checks = _run([("youtube", fine, True)])
    assert checks[0].ok and checks[0].detail == "3 results" and checks[0].critical


def test_a_failing_probe_keeps_its_reason_and_never_raises():
    async def broken():
        raise RuntimeError("shape changed: 'items' missing")

    checks = _run([("saavn", broken, False)])
    assert checks[0].ok is False
    assert "shape changed" in checks[0].detail
    assert checks[0].critical is False


def test_only_critical_failures_fail_the_run(tmp_path, monkeypatch):
    async def fine():
        return "ok"

    async def broken():
        raise RuntimeError("down")

    # one optional source down: the run stays green
    monkeypatch.setattr(
        livecheck, "PROBES", [("youtube", fine, True), ("audius", broken, False)]
    )
    assert livecheck.main(["--json", str(tmp_path / "report.json")]) == 0
    assert (tmp_path / "report.json").is_file()

    # …but --strict makes every source matter
    assert livecheck.main(["--strict"]) == 1


def test_a_critical_failure_fails_the_run(monkeypatch):
    async def broken():
        raise RuntimeError("no results")

    monkeypatch.setattr(livecheck, "PROBES", [("youtube search", broken, True)])
    assert livecheck.main([]) == 1
