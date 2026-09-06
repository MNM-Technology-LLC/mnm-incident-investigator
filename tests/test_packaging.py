# SPDX-License-Identifier: Apache-2.0
"""Deployment boundary regressions, independent of a Docker engine or model."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import stat

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_investigator_has_no_control_network_credentials_or_telemetry_write_access():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = compose["services"]
    agent = services["investigator"]
    for controlled in ("console", "orders-service", "inventory-service", "telemetry"):
        assert set(agent["networks"]).isdisjoint(services[controlled]["networks"])
    assert not agent.get("volumes")
    assert "TELEMETRY_INGEST_TOKEN" not in agent["environment"]
    assert "DEMO_CONTROL_TOKEN" not in agent["environment"]
    assert "telemetry-data:/telemetry:ro" in services["mcp"]["volumes"]
    assert "application" not in services["mcp"]["networks"]
    assert services["console"]["ports"] == ["127.0.0.1:${CONSOLE_PORT:-8080}:8080"]
    assert all(not value.get("ports") for name, value in services.items() if name != "console")
    assert all(compose["networks"][name]["internal"] for name in ("application", "console-read", "agent-read"))
    assert all(service["read_only"] for service in services.values())


def test_local_setup_creates_private_credentials_and_preserves_settings(tmp_path):
    spec = spec_from_file_location("mnm_setup_env", ROOT / "scripts/setup_env.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text())
    path = module.setup(tmp_path)
    original = path.read_text()
    assert "generate-me" not in original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    module.setup(tmp_path)
    assert path.read_text() == original
    changed = original.replace("OLLAMA_MODEL=qwen3:8b", "OLLAMA_MODEL=custom:model")
    path.write_text(changed)
    module.setup(tmp_path)
    assert path.read_text() == changed
    settings = dict(line.split("=", 1) for line in original.splitlines() if line and not line.startswith("#"))
    assert settings["TELEMETRY_INGEST_TOKEN"] != settings["DEMO_CONTROL_TOKEN"]
    assert len(settings["TELEMETRY_INGEST_TOKEN"]) >= 40
