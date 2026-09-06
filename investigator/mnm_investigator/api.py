"""Investigation API. This process has no demo controls or application credentials."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import uvicorn

from .mcp_client import MCPGateway
from .http_boundary import BoundedRequestBody


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(default="Why are orders failing?", min_length=1, max_length=500)
    window_seconds: int = Field(default=30, ge=10, le=300)


def create_app(gateway=None, model=None) -> FastAPI:
    from .agent import Investigator, OllamaModel, ModelUnavailable
    gateway = gateway or MCPGateway()
    model = model or OllamaModel()
    jobs: dict[str, dict] = {}
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="MNM read-only investigator", lifespan=lifespan)
    app.add_middleware(BoundedRequestBody)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/model")
    async def model_status():
        return await model.status()

    async def run(job, question):
        def emit(event):
            job["timeline"].append({
                "sequence": len(job["timeline"]) + 1,
                "timestamp": utcnow().isoformat(), **event,
            })
        try:
            async with asyncio.timeout(int(os.getenv("INVESTIGATION_TIMEOUT_SECONDS", "240"))):
                result = await Investigator(model, gateway).run(question, job["window"], emit)
            job["diagnosis"] = result
            job["status"] = "complete"
        except ModelUnavailable as exc:
            job["status"] = "unavailable"
            job["error"] = str(exc)[:400]
        except TimeoutError:
            job["status"] = "failed"
            job["error"] = "Investigation reached its time budget. Retrieved evidence remains available."
        except Exception:
            job["status"] = "failed"
            job["error"] = "Investigation could not complete. Check model and telemetry availability; collected evidence remains available."
        finally:
            emit({"type": "status", "summary": "Investigation " + job["status"]})

    @app.post("/api/investigations", status_code=202)
    async def investigate(body: InvestigationRequest):
        if any(job["status"] == "running" for job in jobs.values()):
            raise HTTPException(409, "An investigation is already running")
        while len(jobs) >= 25:
            jobs.pop(next(iter(jobs)))
        # Closed window excludes in-flight exports. The exact bounds stay fixed throughout the run.
        end = utcnow() - timedelta(seconds=3)
        job = {
            "id": uuid.uuid4().hex, "status": "running", "mode": "live",
            "model": model.name, "started_at": utcnow().isoformat(),
            "window": {"start": (end - timedelta(seconds=body.window_seconds)).isoformat(), "end": end.isoformat()},
            "timeline": [], "diagnosis": None, "error": None,
        }
        jobs[job["id"]] = job
        task = asyncio.create_task(run(job, body.question))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"id": job["id"], "status": job["status"]}

    @app.get("/api/investigations/{job_id}")
    async def investigation(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "Investigation not found; jobs expire when this process restarts")
        return jobs[job_id]

    @app.get("/api/evidence/{evidence_id}")
    async def evidence(evidence_id: str):
        try:
            result = await gateway.evidence(evidence_id)
        except Exception:
            raise HTTPException(503, "Evidence store unavailable") from None
        if result is None:
            raise HTTPException(404, "Evidence not found")
        return result

    return app


def main():
    uvicorn.run(create_app(), host=os.getenv("BIND_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
