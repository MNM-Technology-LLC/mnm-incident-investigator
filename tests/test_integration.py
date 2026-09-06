# SPDX-License-Identifier: Apache-2.0
"""Opt-in real-stack verification. No mocks and no claims about model quality.

MNM_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v
The test requires a dedicated running stack and changes its demo controls.
Use MNM_BASE_URL, MNM_MCP_URL and MNM_ORDERS_URL for container/internal URLs.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("MNM_INTEGRATION") != "1", reason="Set MNM_INTEGRATION=1 with a running demo stack")
def test_real_healthy_timeout_evidence_and_recovery(tmp_path):
    project = Path(__file__).resolve().parents[1]
    report_path = tmp_path / "smoke-report.json"
    completed = subprocess.run(
        [sys.executable, str(project / "scripts" / "smoke.py"),
         "--base-url", os.getenv("MNM_BASE_URL", "http://127.0.0.1:8080"),
         "--mcp-url", os.getenv("MNM_MCP_URL", "http://127.0.0.1:8001/mcp"),
         "--orders-url", os.getenv("MNM_ORDERS_URL", "http://127.0.0.1:8081"),
         "--output", str(report_path)],
        cwd=project, text=True, capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["verification"] == "deterministic_real_stack" and report["model_used"] is False
    assert {"healthy", "fault", "recovered"} == set(report["phases"])
    assert report["cleanup"] == {"reset": "ok", "traffic": "ok"}
    assert "every_citation_resolves_to_retrieved_evidence" in report["checks"]
