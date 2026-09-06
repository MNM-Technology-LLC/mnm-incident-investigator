"""Deterministic console boundary and recovery tests; no simulated AI is presented."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from mnm_investigator.console import create_app


class MetricGateway:
    def __init__(self, count=60, errors=0, available=True):
        self.count, self.errors, self.available = count, errors, available
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"evidence_id": "ev_" + "a" * 64, "tool": name, "available": self.available,
                "data": {"service": args["service"], "request_count": self.count,
                         "error_count": self.errors, "error_rate": self.errors / self.count if self.count else None,
                         "timeout_count": self.errors, "p95_ms": 25 if self.count else None}, "limitations": []}

    async def evidence(self, evidence_id):
        return None


def app_for(gateway=None, responses=None):
    def handle(request):
        if responses is not None:
            responses.append(request)
        return httpx.Response(200, json={"enabled": False})
    return create_app(gateway=gateway or MetricGateway(), transport=httpx.MockTransport(handle))


def test_control_requires_explicit_header_and_same_origin():
    with TestClient(app_for()) as client:
        assert client.post("/api/demo/fault", json={"enabled": True}).status_code == 403
        assert client.post("/api/demo/fault", json={"enabled": True}, headers={
            "X-Demo-Control": "1", "Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/api/demo/fault", json={"enabled": True}, headers={
            "X-Demo-Control": "1", "Origin": "http://testserver"}).status_code == 200


def test_control_inputs_are_strict_and_proxy_cannot_address_arbitrary_routes():
    with TestClient(app_for()) as client:
        assert client.post("/api/demo/fault", json={"enabled": "false"}, headers={"X-Demo-Control": "1"}).status_code == 422
        assert client.get("/api/investigations/internal-fault").status_code == 404
        assert client.get("/api/evidence/not-an-evidence").status_code == 404


def test_dashboard_reports_only_measured_activity_and_unknown_initial_fault():
    gateway = MetricGateway(count=0, available=False)
    with TestClient(app_for(gateway)) as client:
        data = client.get("/api/dashboard").json()
    assert data["controls"]["fault_enabled"] is None
    assert not data["telemetry_available"]
    assert all(s["status"] == "no_data" and s["p95_ms"] is None for s in data["services"])
    assert {name for name, _ in gateway.calls} == {"query_metrics"}
    assert all(set(args) == {"service", "start", "end"} for _, args in gateway.calls)


def test_reset_compares_equal_closed_windows_and_observed_recovery():
    gateway = MetricGateway(errors=60)
    app = app_for(gateway)
    with TestClient(app) as client:
        response = client.post("/api/demo/reset", json={}, headers={"X-Demo-Control": "1"})
        assert response.status_code == 200
        assert response.json()["status"] == "collecting"
        assert client.post("/api/demo/fault", json={"enabled": True}, headers={"X-Demo-Control": "1"}).status_code == 409
        snapshot = app.state.demo.recovery
        after_end = datetime.now(timezone.utc) - timedelta(seconds=4)
        snapshot["after_start"] = (after_end - timedelta(seconds=30)).isoformat()
        snapshot["after_end"] = after_end.isoformat()
        gateway.errors = 0
        result = client.get("/api/demo/recovery").json()
        assert result["status"] == "complete"
        assert "No service errors" in result["summary"]
        for label in ("before", "after"):
            bounds = result[label]
            assert (datetime.fromisoformat(bounds["end"]) - datetime.fromisoformat(bounds["start"])).total_seconds() == 30


@pytest.mark.parametrize("after_count", [0, 5, 20])
def test_recovery_does_not_claim_success_when_traffic_stops_or_changes(after_count):
    gateway = MetricGateway(errors=60)
    app = app_for(gateway)
    with TestClient(app) as client:
        client.post("/api/demo/reset", json={}, headers={"X-Demo-Control": "1"})
        snapshot = app.state.demo.recovery
        end = datetime.now(timezone.utc) - timedelta(seconds=4)
        snapshot["after_start"] = (end - timedelta(seconds=30)).isoformat()
        snapshot["after_end"] = end.isoformat()
        gateway.count, gateway.errors = after_count, 0
        assert client.get("/api/demo/recovery").json()["status"] == "insufficient"


def test_control_credentials_go_only_to_inventory_not_telemetry():
    requests = []
    gateway = MetricGateway()
    with TestClient(app_for(gateway, requests)) as client:
        client.post("/api/demo/fault", json={"enabled": True}, headers={"X-Demo-Control": "1"})
        client.get("/api/dashboard")
    assert len(requests) == 1 and requests[0].url.path == "/internal/fault"
    assert requests[0].headers.get("X-Demo-Control-Token")
    assert "enabled" not in str(gateway.calls)
