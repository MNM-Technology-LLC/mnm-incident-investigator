# SPDX-License-Identifier: Apache-2.0
"""Release regressions using real files and stored observations, with no model calls.

These also run against an installed wheel by placing its installation directory
first on PYTHONPATH; the static-file test catches missing packaged browser assets.
"""

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from mnm_investigator.console import create_app
from mnm_investigator.mcp_client import validate_evidence
from mnm_investigator.mcp_server import TelemetryReader
from mnm_investigator.telemetry import TelemetryStore, utc_string


ROOT = Path(__file__).resolve().parents[1]


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.references.append((attributes["src"], "javascript"))
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.references.append((attributes["href"], "text/css"))


def test_packaged_console_serves_every_referenced_script_and_stylesheet():
    with TestClient(create_app()) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "MNM Incident Investigator" in page.text
        parser = AssetReferences()
        parser.feed(page.text)
        assert parser.references, "The console must include its working browser assets"
        for path, content_type in parser.references:
            assert path.startswith("/") and not path.startswith("//")
            asset = client.get(path)
            assert asset.status_code == 200, path
            assert content_type in asset.headers["content-type"], path
            assert len(asset.content) > 100, path
        assert "script-src 'self'" in page.headers["content-security-policy"]


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="File permissions do not restrict root")
def test_read_only_telemetry_volume_exposes_recent_wal_records(tmp_path):
    """A read-only reader sees commits still in WAL without creating writable files.

    An immutable=1 shortcut would miss the second commit. Permission changes model
    a read-only telemetry directory; an actual Docker mount still needs CI smoke.
    """
    telemetry_dir = tmp_path / "telemetry"
    store = TelemetryStore(telemetry_dir / "telemetry.db")
    reader = TelemetryReader(store.db_path, tmp_path / "evidence" / "evidence.db")
    now = datetime.now(timezone.utc)
    sample = {
        "kind": "metric", "service": "orders-service", "timestamp": utc_string(now),
        "trace_id": "a" * 32, "span_id": "b" * 16, "name": "HTTP GET /api/orders",
        "duration_ms": 18, "status_code": 200, "level": "INFO", "message": "request completed",
        "attributes": {"method": "GET", "path": "/api/orders", "span_kind": "server"},
    }
    store.ingest([sample], now=now)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.ingest([{**sample, "span_id": "c" * 16}], now=now)
    files = list(telemetry_dir.iterdir())
    assert (telemetry_dir / "telemetry.db-wal").stat().st_size > 0
    assert (telemetry_dir / "telemetry.db-shm").exists()
    try:
        for path in files:
            path.chmod(0o444)
        telemetry_dir.chmod(0o555)
        result = reader.query_metrics(
            "orders-service", utc_string(now - timedelta(seconds=1)), utc_string(now + timedelta(seconds=1)),
        )
        assert result["available"], result["limitations"]
        assert result["data"]["request_count"] == 2
        assert set(telemetry_dir.iterdir()) == set(files)
        with sqlite3.connect(store.db_path.as_uri() + "?mode=ro", uri=True) as connection:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("DELETE FROM events")
    finally:
        telemetry_dir.chmod(0o755)
        for path in files:
            if path.exists():
                path.chmod(0o644)
        store.close()


def test_archived_smoke_evidence_is_self_contained_and_checksum_valid():
    """Recheck recorded results; this is not a new live-stack execution."""
    report = json.loads((ROOT / "docs/evaluations/smoke.json").read_text())
    assert report["model_used"] is False
    assert report["verification"] == "deterministic_real_stack"
    snapshots = report["evidence"]
    assert snapshots
    for evidence_id, snapshot in snapshots.items():
        assert validate_evidence(snapshot, evidence_id=evidence_id) == snapshot
    for phase in report["phases"].values():
        for key, value in phase.items():
            if key.endswith("evidence_id"):
                assert value in snapshots
        for metrics in phase["metrics"].values():
            assert metrics["evidence_id"] in snapshots
    assert report["missing_telemetry_evidence_id"] in snapshots


def test_archived_smoke_recovery_compares_equal_windows_and_request_volumes():
    """The distributed report must preserve the basis for its recovery comparison."""
    report = json.loads((ROOT / "docs/evaluations/smoke.json").read_text())
    counts = {}
    for name, phase in report["phases"].items():
        start, end = (datetime.fromisoformat(phase["window"][key]) for key in ("start", "end"))
        assert (end - start).total_seconds() == report["window_seconds"]
        counts[name] = len(phase["requests"])
        for metrics in phase["metrics"].values():
            assert metrics["window_seconds"] == report["window_seconds"]
            assert metrics["request_count"] == counts[name]
    assert len(set(counts.values())) == 1
    assert counts["recovered"] > 0
