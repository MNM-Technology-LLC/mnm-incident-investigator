#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify a running demo with actual HTTP traffic and read-only MCP telemetry.

This is a deterministic application/telemetry check. It does not call a model,
produce an AI diagnosis, or measure live model investigation quality. Run this
against a dedicated demo stack: it changes the demo fault and stops traffic.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

import httpx

from mnm_investigator.mcp_client import ALLOWED_TOOLS, MCPGateway, ToolPermissionError

WINDOW_SECONDS = 8
SETTLE_SECONDS = 3
REQUEST_COUNT = 8
REQUEST_INTERVAL_SECONDS = 0.5
SERVICES = ("orders-service", "inventory-service")


def now() -> datetime:
    return datetime.now(timezone.utc)


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def control(client: httpx.AsyncClient, base_url: str, action: str, body: dict) -> dict:
    response = await client.post(
        f"{base_url}/api/demo/{action}", json=body, headers={"X-Demo-Control": "1"},
    )
    response.raise_for_status()
    return response.json()


async def collect_window(client: httpx.AsyncClient, orders_url: str, expected_status: int) -> dict:
    """Schedule a bounded, identical workload in each fixed observation window."""
    start = now()
    end = start + timedelta(seconds=WINDOW_SECONDS)
    clock = asyncio.get_running_loop()
    started = clock.time()

    async def request(index: int) -> dict:
        await asyncio.sleep(max(0, started + index * REQUEST_INTERVAL_SECONDS - clock.time()))
        request_start = time.monotonic()
        response = await client.get(f"{orders_url}/api/orders")
        duration_ms = round((time.monotonic() - request_start) * 1000, 3)
        require(response.status_code == expected_status,
                f"Request {index + 1}: expected HTTP {expected_status}, got {response.status_code}")
        payload = response.json()
        trace_id = payload.get("trace_id", "")
        require(re.fullmatch(r"[0-9a-f]{32}", trace_id), "Response is missing a valid trace ID")
        return {"status_code": response.status_code, "trace_id": trace_id, "duration_ms": duration_ms}

    requests = await asyncio.gather(*(request(index) for index in range(REQUEST_COUNT)))
    require(now() < end, "Requests exceeded their fixed observation window")
    # Close the query window first, then let the bounded asynchronous exporters settle.
    await asyncio.sleep(max(0, started + WINDOW_SECONDS + SETTLE_SECONDS - clock.time()))
    return {"window": {"start": start.isoformat(), "end": end.isoformat()}, "requests": requests}


def verify_correlated_trace(trace: dict, trace_id: str, expected_status: int) -> dict:
    require(trace["available"], f"Trace {trace_id} is unavailable")
    data = trace["data"]
    require(data.get("complete") is True, f"Trace {trace_id} has missing parent/client spans")
    spans = data["spans"]
    require(all(span["trace_id"] == trace_id for span in spans), "Trace contains unrelated spans")
    roots = [span for span in spans if span["service"] == "orders-service"
             and span["attributes"].get("span_kind") == "server"]
    clients = [span for span in spans if span["service"] == "orders-service"
               and span["attributes"].get("span_kind") == "client"
               and span["attributes"].get("peer_service") == "inventory-service"]
    inventory = [span for span in spans if span["service"] == "inventory-service"
                 and span["attributes"].get("span_kind") == "server"]
    require(len(roots) == len(clients) == len(inventory) == 1,
            "Expected one orders server, orders client, and inventory server span")
    root, downstream, child = roots[0], clients[0], inventory[0]
    require(downstream["parent_span_id"] == root["span_id"], "Client span has an unrelated parent")
    require(child["parent_span_id"] == downstream["span_id"], "Inventory span has an unrelated parent")
    require(root["status_code"] == downstream["status_code"] == expected_status,
            "Correlated order spans disagree with the actual response status")
    require(child["status_code"] == 200, "Inventory did not complete its request successfully")
    require(any(log["service"] == "orders-service" and log["trace_id"] == trace_id
                for log in data["logs"]), "Trace has no correlated orders log")
    require(any(log["service"] == "inventory-service" and log["trace_id"] == trace_id
                for log in data["logs"]), "Trace has no correlated inventory log")
    observed = {"trace_id": trace_id, "orders_duration_ms": root["duration_ms"],
                "inventory_duration_ms": child["duration_ms"],
                "timeout_ms": downstream["attributes"].get("timeout_ms")}
    if expected_status == 504:
        require(downstream["attributes"].get("error_type") == "timeout", "No observed client timeout")
        require(observed["timeout_ms"] == 600, "Expected the documented 600 ms orders timeout")
        require(child["duration_ms"] > observed["timeout_ms"],
                "Inventory latency did not exceed the observed orders timeout")
    return observed


async def run_smoke(base_url: str, mcp_url: str, orders_url: str, report: dict | None = None) -> dict:
    """Raise on failed checks; always attempt to disable the fault and stop traffic."""
    report = report if report is not None else {}
    report.update({
        "verification": "deterministic_real_stack", "model_used": False, "status": "running",
        "started_at": now().isoformat(), "window_seconds": WINDOW_SECONDS,
        "requests_per_window": REQUEST_COUNT, "settle_seconds": SETTLE_SECONDS,
        "limitations": [
            "This report verifies actual application behavior and retrieval, not AI diagnosis quality.",
            "Observed inventory delay explains the timeout; telemetry alone does not establish its underlying cause.",
            "The comparison uses equal 8-second verification windows; the browser recovery view uses 30 seconds.",
        ],
        "checks": [], "phases": {}, "evidence": {}, "cleanup": {},
    })
    base_url, orders_url = base_url.rstrip("/"), orders_url.rstrip("/")
    gateway = MCPGateway(mcp_url)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        try:
            response = await client.get(f"{base_url}/health")
            response.raise_for_status()
            await control(client, base_url, "traffic", {"running": False})
            # A previous reset owns a 30-second recovery window. Finish it before
            # taking exclusive control of this dedicated verification run.
            for _ in range(45):
                response = await client.get(f"{base_url}/api/demo/recovery")
                response.raise_for_status()
                if response.json().get("status") != "collecting":
                    break
                await asyncio.sleep(1)
            else:
                raise AssertionError("A previous recovery measurement did not finish within 45 seconds")
            await control(client, base_url, "fault", {"enabled": False})
            await asyncio.sleep(SETTLE_SECONDS)

            async with gateway.session() as session:
                tools = await session.list_tools()
                require({tool["function"]["name"] for tool in tools} == ALLOWED_TOOLS,
                        "The investigator did not receive exactly the five permitted tools")
                for forbidden in ("trigger_fault", "reset", "run_shell"):
                    try:
                        await session.call_tool(forbidden, {"enabled": True})
                    except ToolPermissionError:
                        pass
                    else:
                        raise AssertionError(f"Investigator permission boundary accepted {forbidden}")
                report["checks"].append("investigator_tool_allowlist_enforced")

                async def evidence(tool: str, args: dict) -> dict:
                    value = await session.call_tool(tool, args)
                    evidence_id = value["evidence_id"]
                    resolved = await gateway.evidence(evidence_id)
                    require(resolved == value, f"Evidence {evidence_id} did not resolve to the retrieved snapshot")
                    browser = await client.get(f"{base_url}/api/evidence/{evidence_id}")
                    browser.raise_for_status()
                    require(browser.json() == value, f"Browser citation {evidence_id} did not resolve")
                    report["evidence"][evidence_id] = value
                    return value

                async def phase(label: str, status: int) -> dict:
                    print(f"Measuring {label}: {REQUEST_COUNT} requests in {WINDOW_SECONDS}s...", flush=True)
                    measured = await collect_window(client, orders_url, status)
                    report["phases"][label] = measured
                    bounds = measured["window"]
                    metrics = {}
                    for service in SERVICES:
                        result = await evidence("query_metrics", {"service": service, **bounds})
                        require(result["available"], f"{label}: {service} metrics are missing")
                        require(result["data"]["request_count"] == REQUEST_COUNT,
                                f"{label}: expected exactly {REQUEST_COUNT} {service} samples; "
                                "stop other clients or inspect exporter loss")
                        expected_errors = REQUEST_COUNT if status == 504 and service == "orders-service" else 0
                        require(result["data"]["error_count"] == expected_errors,
                                f"{label}: measured {service} errors disagree with requests")
                        require(result["data"]["timeout_count"] == expected_errors,
                                f"{label}: measured {service} timeout count disagrees with requests")
                        metrics[service] = {"evidence_id": result["evidence_id"], **result["data"]}
                    measured["metrics"] = metrics
                    health = await evidence("get_service_health", bounds)
                    expected_health = {"orders-service": "degraded" if status == 504 else "healthy",
                                       "inventory-service": "healthy"}
                    require({entry["service"]: entry["status"] for entry in health["data"]["services"]}
                            == expected_health, f"{label}: health disagrees with observed completed requests")
                    measured["health_evidence_id"] = health["evidence_id"]
                    return measured

                await phase("healthy", 200)
                report["checks"].append("healthy_requests_and_metrics_have_no_incident_signal")
                await control(client, base_url, "fault", {"enabled": True})
                incident = await phase("fault", 504)
                fault_bounds = incident["window"]
                logs = await evidence("search_logs", {"service": "orders-service", "level": "ERROR",
                                                       "limit": 50, **fault_bounds})
                actual_trace_ids = {request["trace_id"] for request in incident["requests"]}
                logged_trace_ids = {record["trace_id"] for record in logs["data"]["records"]}
                require(actual_trace_ids <= logged_trace_ids, "Some actual timeouts have no correlated error log")
                require(not logs["data"]["truncated"], "Timeout log evidence unexpectedly exceeded its bound")
                incident["logs_evidence_id"] = logs["evidence_id"]
                trace_id = incident["requests"][0]["trace_id"]
                trace = await evidence("get_trace", {"trace_id": trace_id, **fault_bounds})
                incident["observed_trace"] = verify_correlated_trace(trace, trace_id, 504)
                incident["trace_evidence_id"] = trace["evidence_id"]
                topology = await evidence("get_service_map", fault_bounds)
                require(any(edge["source"] == "orders-service" and edge["target"] == "inventory-service"
                            and edge["error_count"] == REQUEST_COUNT for edge in topology["data"]["edges"]),
                        "No observed orders-to-inventory failing dependency")
                incident["map_evidence_id"] = topology["evidence_id"]
                report["checks"].append("actual_504s_correlate_to_logs_and_inventory_spans_beyond_timeout")

                await control(client, base_url, "reset", {})
                await asyncio.sleep(SETTLE_SECONDS)
                recovered = await phase("recovered", 200)
                recovery_trace_id = recovered["requests"][0]["trace_id"]
                recovery_trace = await evidence("get_trace", {"trace_id": recovery_trace_id,
                                                               **recovered["window"]})
                recovered["observed_trace"] = verify_correlated_trace(recovery_trace, recovery_trace_id, 200)
                recovered["trace_evidence_id"] = recovery_trace["evidence_id"]
                require(recovered["observed_trace"]["inventory_duration_ms"] < 600,
                        "Recovered inventory response still exceeds the configured orders timeout")
                report["checks"].append("reset_restores_success_in_equal_windows_at_equal_volume")

                # The receiver rejects events older than 24h, so a closed window
                # two days ago gives an empty observation without disrupting it.
                missing_end = now() - timedelta(days=2)
                missing = await evidence("query_metrics", {"service": "orders-service",
                    "start": (missing_end - timedelta(seconds=WINDOW_SECONDS)).isoformat(),
                    "end": missing_end.isoformat()})
                require(missing["available"] is False and missing["limitations"],
                        "An empty observation was not reported as unavailable")
                require(all(missing["data"][key] is None for key in
                            ("error_rate", "p50_ms", "p95_ms", "requests_per_second")),
                        "Missing telemetry produced fabricated rates or latency")
                report["missing_telemetry_evidence_id"] = missing["evidence_id"]
                report["checks"].extend(["missing_telemetry_is_explicit", "every_citation_resolves_to_retrieved_evidence"])
        except Exception as error:
            report["status"] = "failed"
            report["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            # Cleanup has independent attempts: an unavailable fault endpoint
            # must never prevent stopping the bounded background traffic worker.
            for action, body in (("reset", {}), ("traffic", {"running": False})):
                try:
                    await control(client, base_url, action, body)
                    report["cleanup"][action] = "ok"
                except Exception as error:
                    report["cleanup"][action] = f"failed: {type(error).__name__}: {error}"
            report["finished_at"] = now().isoformat()
        require(all(value == "ok" for value in report["cleanup"].values()),
                "Cleanup was incomplete; inspect the report and manually reset the demo")
        report["status"] = "passed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Demo console URL")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp", help="Read-only MCP endpoint")
    parser.add_argument("--orders-url", default="http://127.0.0.1:8081", help="Orders application URL")
    parser.add_argument("--output", type=Path, default=Path(".runtime/smoke-report.json"))
    arguments = parser.parse_args()
    report: dict[str, Any] = {}
    result = 0
    print("Deterministic real-stack verification; no model is invoked. The demo must be dedicated to this run.",
          flush=True)
    try:
        asyncio.run(run_smoke(arguments.base_url, arguments.mcp_url, arguments.orders_url, report))
    except Exception as error:
        report["status"] = "failed"
        report.setdefault("error", f"{type(error).__name__}: {error}")
        print(f"FAILED: {report['error']}", file=sys.stderr)
        result = 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['status'].upper()}: {len(report.get('checks', []))} checks; report: {arguments.output}", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
