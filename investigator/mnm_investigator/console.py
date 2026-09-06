"""Browser and operator controls. Never imported by the investigator process."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from .http_boundary import BoundedRequestBody
from .mcp_client import MCPGateway

SERVICES = ("orders-service", "inventory-service")
WINDOW_SECONDS = 30


def utcnow():
    return datetime.now(timezone.utc)


def window(end=None):
    end = end or utcnow() - timedelta(seconds=3)
    return {"start": (end - timedelta(seconds=WINDOW_SECONDS)).isoformat(), "end": end.isoformat()}


class TrafficAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    running: StrictBool


class FaultAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class DemoState:
    def __init__(self, client, orders_url, inventory_url, control_token):
        self.client = client
        self.orders_url = orders_url
        self.inventory_url = inventory_url
        self.control_token = control_token
        self.traffic_task = None
        self.traffic = {"running": False, "requests_sent": 0, "successes": 0, "failures": 0, "started_at": None}
        self.fault_enabled = None  # Unknown until a control acknowledgement; no fabricated state after restart.
        self.recovery = None
        self.lock = asyncio.Lock()

    async def fault(self, enabled):
        try:
            response = await self.client.post(
                self.inventory_url + "/internal/fault", json={"enabled": enabled},
                headers={"X-Demo-Control-Token": self.control_token}, timeout=5,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "Inventory control unavailable; fault state is unknown") from None
        self.fault_enabled = enabled

    async def send_request(self):
        self.traffic["requests_sent"] += 1
        try:
            response = await self.client.get(self.orders_url + "/api/orders", timeout=4)
            ok = response.status_code == 200
        except httpx.HTTPError:
            ok = False
        self.traffic["successes" if ok else "failures"] += 1

    async def traffic_loop(self):
        self.traffic["running"] = True
        self.traffic["started_at"] = utcnow().isoformat()
        pending = set()
        clock = asyncio.get_running_loop()
        deadline = clock.time() + 360
        next_tick = clock.time()
        try:
            while clock.time() < deadline:
                if len(pending) < 8:
                    task = asyncio.create_task(self.send_request())
                    pending.add(task)
                    task.add_done_callback(pending.discard)
                next_tick += 0.5
                await asyncio.sleep(max(0, next_tick - clock.time()))
        finally:
            self.traffic["running"] = False
            await asyncio.gather(*pending, return_exceptions=True)

    async def set_traffic(self, running):
        if running and (self.traffic_task is None or self.traffic_task.done()):
            self.traffic["running"] = True
            self.traffic_task = asyncio.create_task(self.traffic_loop())
        elif not running and self.traffic_task and not self.traffic_task.done():
            self.traffic_task.cancel()
            await asyncio.gather(self.traffic_task, return_exceptions=True)
            self.traffic["running"] = False


def create_app(gateway=None, transport=None) -> FastAPI:
    gateway = gateway or MCPGateway()
    client = httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False, transport=transport)
    state = DemoState(
        client, os.getenv("ORDERS_URL", "http://127.0.0.1:8081"),
        os.getenv("INVENTORY_URL", "http://127.0.0.1:8082"),
        os.getenv("DEMO_CONTROL_TOKEN", "local-demo-control-change-me"),
    )
    investigator_url = os.getenv("INVESTIGATOR_URL", "http://127.0.0.1:8000")

    @asynccontextmanager
    async def lifespan(app):
        yield
        await state.set_traffic(False)
        await client.aclose()

    app = FastAPI(title="MNM Incident Investigator console", lifespan=lifespan)
    app.add_middleware(BoundedRequestBody)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "console", "testserver"])
    app.state.demo = state

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = request.headers.get("host", "")
            if origin:
                try:
                    parsed_origin = urlsplit(origin)
                    same_origin = parsed_origin.scheme == request.url.scheme and parsed_origin.netloc == expected
                except ValueError:
                    same_origin = False
                if not same_origin:
                    return JSONResponse({"detail": "Cross-origin writes are forbidden"}, status_code=403)
            if request.url.path.startswith("/api/demo/") and not secrets.compare_digest(
                request.headers.get("x-demo-control", ""), "1"
            ):
                return JSONResponse({"detail": "Explicit demo control header required"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    async def read_metrics(bounds):
        async def read(service):
            try:
                result = await gateway.call_tool("query_metrics", {"service": service, **bounds})
                return {**result["data"], "available": result["available"], "evidence_id": result["evidence_id"],
                        "limitations": result.get("limitations", [])}
            except Exception:
                return {"service": service, "available": False, "request_count": 0, "error_count": 0,
                        "timeout_count": 0, "error_rate": None, "p50_ms": None, "p95_ms": None,
                        "requests_per_second": None, "limitations": ["Telemetry connection unavailable"]}
        values = await asyncio.gather(*(read(service) for service in SERVICES))
        return dict(zip(SERVICES, values))

    @app.get("/api/dashboard")
    async def dashboard():
        bounds = window()
        metrics = await read_metrics(bounds)
        services = []
        for service, measurement in metrics.items():
            status = "no_data"
            if measurement.get("available") and measurement.get("request_count", 0):
                status = "degraded" if measurement.get("error_count", 0) else "healthy"
            services.append({**measurement, "service": service, "status": status})
        return {"window": bounds, "services": services, "metrics": metrics,
                "traffic": state.traffic.copy(), "controls": {"fault_enabled": state.fault_enabled},
                "telemetry_available": any(m.get("available") for m in metrics.values()), "mode": "live"}

    @app.post("/api/demo/traffic")
    async def traffic(body: TrafficAction):
        async with state.lock:
            await state.set_traffic(body.running)
        return state.traffic

    @app.post("/api/demo/fault")
    async def fault(body: FaultAction):
        async with state.lock:
            if state.recovery and state.recovery.get("status") == "collecting":
                raise HTTPException(409, "Wait for recovery measurement to finish before changing the fault")
            await state.fault(body.enabled)
        return {"fault_enabled": state.fault_enabled}

    @app.post("/api/demo/reset")
    async def reset():
        async with state.lock:
            if state.recovery and state.recovery.get("status") == "collecting":
                return await recovery()
            before_bounds = window()
            before_metrics = await read_metrics(before_bounds)
            await state.fault(False)
            after_start = utcnow() + timedelta(seconds=3)
            state.recovery = {
                "status": "collecting", "window_seconds": WINDOW_SECONDS,
                "before": {**before_bounds, "metrics": before_metrics}, "after": None,
                "after_start": after_start.isoformat(),
                "after_end": (after_start + timedelta(seconds=WINDOW_SECONDS)).isoformat(),
            }
        return await recovery()

    @app.get("/api/demo/recovery")
    async def recovery():
        if not state.recovery:
            return {"status": "idle", "window_seconds": WINDOW_SECONDS, "before": None,
                    "after": None, "remaining_seconds": 0, "summary": "Reset the fault to compare recovery."}
        snapshot = state.recovery
        end = datetime.fromisoformat(snapshot["after_end"])
        remaining = max(0, math.ceil((end + timedelta(seconds=3) - utcnow()).total_seconds()))
        if snapshot["status"] == "collecting" and remaining == 0:
            bounds = {"start": snapshot["after_start"], "end": snapshot["after_end"]}
            after = await read_metrics(bounds)
            snapshot["after"] = {**bounds, "metrics": after}
            before = snapshot["before"]["metrics"]
            sufficient = all(
                before[s].get("available") and after[s].get("available")
                and before[s].get("request_count", 0) >= 10 and after[s].get("request_count", 0) >= 10
                and 0.7 <= after[s]["request_count"] / before[s]["request_count"] <= 1.3
                for s in SERVICES
            )
            snapshot["status"] = "complete" if sufficient else "insufficient"
            if not sufficient:
                summary = "Comparison incomplete: use continuous traffic and at least 10 requests per service in equally long windows with comparable volume."
            elif after["orders-service"]["error_count"] == 0 and after["inventory-service"]["error_count"] == 0:
                summary = "No service errors observed in the recovery window at comparable request volume. This verifies observed behavior in these windows only."
            else:
                summary = "Service errors remain in the recovery window. Inspect current evidence before claiming recovery."
            snapshot["summary"] = summary
        return {k: v for k, v in snapshot.items() if not k.startswith("after_")} | {
            "remaining_seconds": remaining,
            "summary": snapshot.get("summary", "Collecting an equivalent 30-second window after in-flight requests settle."),
        }

    async def proxy(path, method="GET", body=None):
        try:
            response = await client.request(method, investigator_url + path, json=body)
            value = response.json()
            return JSONResponse(value, status_code=response.status_code)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Investigator is unavailable") from None

    @app.get("/api/model")
    async def model():
        return await proxy("/api/model")

    @app.post("/api/investigations", status_code=202)
    async def investigations(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, "Invalid JSON") from None
        return await proxy("/api/investigations", "POST", payload)

    @app.get("/api/investigations/{job_id}")
    async def investigation(job_id: str):
        if not all(c in "0123456789abcdef" for c in job_id) or len(job_id) != 32:
            raise HTTPException(404, "Investigation not found")
        return await proxy("/api/investigations/" + job_id)

    @app.get("/api/evidence/{evidence_id}")
    async def evidence(evidence_id: str):
        try:
            result = await gateway.evidence(evidence_id)
        except Exception:
            raise HTTPException(503, "Evidence store unavailable") from None
        if result is None:
            raise HTTPException(404, "Evidence not found")
        return result

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
    return app


def main():
    uvicorn.run(create_app(), host=os.getenv("BIND_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()
