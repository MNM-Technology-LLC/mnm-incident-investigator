"""Fixed investigation bridge tests; all upstream HTTP is mocked, with no network I/O."""

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from mnm_investigator import mcp_server


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    calls, options = [], []
    behavior = {"status": 200, "body": b'{"status":"ok"}'}

    def upstream(request):
        calls.append(request)
        if behavior.get("error"):
            raise httpx.ConnectError("private upstream details", request=request)
        return httpx.Response(behavior["status"], content=behavior["body"])

    original_client = httpx.AsyncClient

    def client_factory(**kwargs):
        options.append(kwargs.copy())
        return original_client(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", client_factory)
    monkeypatch.setenv("INVESTIGATOR_UPSTREAM", "http://investigator:8000/")
    server = mcp_server.create_server(tmp_path / "missing-telemetry.db", tmp_path / "evidence.db")
    with TestClient(server.streamable_http_app()) as client:
        yield client, server, calls, options, behavior


@pytest.mark.parametrize("path", ["/api/demo/fault", "/internal/fault", "/api/demo/reset", "/arbitrary"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_control_and_arbitrary_paths_never_reach_upstream(bridge, path, method):
    client, _, calls, _, _ = bridge
    assert client.request(method, path).status_code == 404
    assert calls == []


@pytest.mark.parametrize("job_id", ["invalid", "A" * 32, "a" * 31, "a" * 33, "http:inventory", "%2e%2e%2finternal%2ffault"])
def test_invalid_investigation_ids_are_blocked_before_http(bridge, job_id):
    client, _, calls, _, _ = bridge
    assert client.get("/api/investigations/" + job_id).status_code == 404
    assert calls == []


def test_only_fixed_paths_and_upstream_are_used(bridge):
    client, _, calls, options, _ = bridge
    assert client.get("/api/model?url=http://inventory-service:8082/internal/fault").status_code == 200
    payload = {"question": "Why are orders failing?", "window_seconds": 30}
    assert client.post("/api/investigations", json=payload,
        headers={"Authorization": "Bearer caller-secret", "X-Demo-Control": "1", "X-Upstream": "http://evil.example"}).status_code == 200
    job_id = "a" * 32
    assert client.get("/api/investigations/" + job_id + "?path=/internal/fault").status_code == 200
    assert [str(request.url) for request in calls] == [
        "http://investigator:8000/api/model", "http://investigator:8000/api/investigations",
        "http://investigator:8000/api/investigations/" + job_id,
    ]
    assert [request.method for request in calls] == ["GET", "POST", "GET"]
    assert json.loads(calls[1].content) == payload
    assert "authorization" not in calls[1].headers
    assert "x-demo-control" not in calls[1].headers
    assert all(option == {"timeout": 12, "follow_redirects": False, "trust_env": False} for option in options)


def test_request_body_and_json_limits_apply_before_upstream(bridge):
    client, _, calls, _, _ = bridge
    assert client.post("/api/investigations", content=b"x" * 4097).status_code == 413
    assert client.post("/api/investigations", content=b"not-json").status_code == 400
    assert calls == []


def test_response_budget_errors_and_redirects_are_bounded(bridge):
    client, _, calls, _, behavior = bridge
    behavior["body"] = b"x" * 131073
    assert client.get("/api/model").status_code == 502
    behavior["body"] = b"not-json"
    assert client.get("/api/model").status_code == 503
    behavior["error"] = True
    unavailable = client.get("/api/model")
    assert unavailable.status_code == 503
    assert "private upstream details" not in unavailable.text
    behavior.update(error=False, status=302, body=b'{"detail":"redirect"}')
    before = len(calls)
    assert client.get("/api/model", follow_redirects=False).status_code == 302
    assert len(calls) == before + 1


def test_proxy_adds_no_mcp_tools_and_rejects_other_methods(bridge):
    client, server, calls, _, _ = bridge
    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert tool_names == mcp_server.READ_ONLY_TOOLS
    assert len(tool_names) == 5
    assert client.post("/api/model").status_code == 405
    assert client.get("/api/investigations").status_code == 405
    assert client.post("/api/investigations/" + "a" * 32).status_code == 405
    assert calls == []
