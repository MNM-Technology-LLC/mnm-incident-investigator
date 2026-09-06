"""Small authenticated telemetry receiver; only measured application events enter storage.

This is deliberately not an OTLP implementation. The demo instruments its requests
directly and exports this documented event schema. No scenario/control state is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Service = Literal["orders-service", "inventory-service"]
TraceId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
SpanId = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
SERVICES = ("orders-service", "inventory-service")
MAX_BODY_BYTES = 262_144
MAX_EVENTS = 100_000
RETENTION_SECONDS = 86_400


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("An explicit UTC timestamp is required")
    return value.astimezone(timezone.utc)


def redact_secrets(value: str) -> str:
    """Defense in depth for bounded untrusted text; never export credentials verbatim."""
    value = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value)
    value = re.sub(
        r"(?i)\b(password|passwd|(?:client[_-]?)?secret|(?:(?:access|refresh|id)[_-]?)?token|api[_-]?key|authorization|cookie)\b"
        r"[\"']?\s*[:=]\s*(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;]+)",
        r"\1=[REDACTED]", value,
    )
    value = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b", "[REDACTED]", value)
    value = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    return "".join(c if c >= " " else " " for c in value)[:512]


class EventAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    peer_service: Service | None = None
    error_type: Literal["timeout", "connection_error", "upstream_error", "internal_error"] | None = None
    timeout_ms: Annotated[int, Field(ge=1, le=60_000)] | None = None
    method: Literal["GET"] | None = None
    path: Literal["/api/orders", "/api/inventory"] | None = None
    span_kind: Literal["server", "client"] | None = None


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["log", "span", "metric"]
    service: Service
    timestamp: datetime
    trace_id: TraceId
    span_id: SpanId
    parent_span_id: SpanId | None = None
    name: Literal["HTTP GET /api/orders", "HTTP GET /api/inventory", "inventory.request"]
    duration_ms: Annotated[float, Field(ge=0, le=3_600_000)]
    status_code: Annotated[int, Field(ge=100, le=599)]
    level: Literal["INFO", "WARN", "ERROR"] = "INFO"
    message: Annotated[str, Field(max_length=2048)] = ""
    attributes: EventAttributes = Field(default_factory=EventAttributes)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return parse_utc(value)

    @field_validator("message")
    @classmethod
    def safe_message(cls, value: str) -> str:
        if re.search(r"(?i)\b(fault|injector|injection|scenario[_ -]?answer)\b|/internal/|delay[_ -]?ms", value):
            raise ValueError("Control-plane information is not telemetry")
        return redact_secrets(value)

    @model_validator(mode="after")
    def server_metrics_only(self) -> TelemetryEvent:
        if self.kind == "metric" and (self.attributes.span_kind != "server" or self.name == "inventory.request"):
            raise ValueError("Metrics must represent completed server requests")
        if self.trace_id == "0" * 32 or self.span_id == "0" * 16:
            raise ValueError("Trace and span IDs cannot be all zero")
        return self

    def as_record(self) -> dict:
        result = self.model_dump(mode="json", exclude_none=True)
        result["timestamp"] = utc_string(self.timestamp)
        result["record_id"] = "rec_" + hashlib.sha256(canonical_json(result).encode()).hexdigest()
        return result


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: Annotated[list[TelemetryEvent], Field(min_length=1, max_length=100)]


class TelemetryStore:
    """Single writer role. A keeper connection preserves readable WAL/SHM files."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._keeper = sqlite3.connect(self.db_path, timeout=2, check_same_thread=False)
        self._keeper.execute("PRAGMA journal_mode=WAL")
        self._keeper.execute("PRAGMA synchronous=NORMAL")
        self._keeper.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                record_id TEXT PRIMARY KEY, kind TEXT NOT NULL, service TEXT NOT NULL,
                timestamp REAL NOT NULL, trace_id TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_service_time ON events(service, kind, timestamp);
            CREATE INDEX IF NOT EXISTS events_kind_time ON events(kind, timestamp);
            CREATE INDEX IF NOT EXISTS events_trace_time ON events(trace_id, timestamp);
        """)
        self._keeper.commit()

    def ingest(self, events: list[dict | TelemetryEvent], *, now: datetime | None = None) -> int:
        if not 1 <= len(events) <= 100:
            raise ValueError("A batch must contain between 1 and 100 events")
        instant = now or datetime.now(timezone.utc)
        validated = [event if isinstance(event, TelemetryEvent) else TelemetryEvent.model_validate(event) for event in events]
        if any(not instant - timedelta(seconds=RETENTION_SECONDS) <= event.timestamp <= instant + timedelta(seconds=60) for event in validated):
            raise ValueError("Event timestamp outside the retention/clock-skew bounds")
        with sqlite3.connect(self.db_path, timeout=2) as connection:
            inserted = 0
            for event in validated:
                record = event.as_record()
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?)",
                    (record["record_id"], event.kind, event.service, event.timestamp.timestamp(), event.trace_id, canonical_json(record)),
                )
                inserted += cursor.rowcount
            connection.execute("DELETE FROM events WHERE timestamp < ?", (instant.timestamp() - RETENTION_SECONDS,))
            connection.execute(
                "DELETE FROM events WHERE record_id IN (SELECT record_id FROM events ORDER BY timestamp DESC LIMIT -1 OFFSET ?)",
                (MAX_EVENTS,),
            )
        return inserted

    def close(self) -> None:
        self._keeper.close()


def create_app(db_path: str | Path | None = None, ingest_token: str | None = None) -> FastAPI:
    token = ingest_token if ingest_token is not None else os.environ.get("TELEMETRY_INGEST_TOKEN", "")
    if not token:
        raise RuntimeError("TELEMETRY_INGEST_TOKEN must be configured")
    store = TelemetryStore(db_path or os.environ.get("TELEMETRY_DB", "/data/telemetry.db"))
    app = FastAPI(title="MNM measured telemetry receiver", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/v1/events")
    async def ingest(request: Request) -> dict:
        if not hmac.compare_digest(request.headers.get("x-telemetry-token", ""), token):
            raise HTTPException(401, "Invalid telemetry credentials")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BODY_BYTES:
                raise HTTPException(413, "Telemetry batch exceeds byte budget")
        try:
            batch = EventBatch.model_validate_json(bytes(data))
            count = store.ingest(batch.events)
        except (ValidationError, ValueError):
            # Pydantic error details echo the rejected input, which may contain secrets.
            raise HTTPException(422, "Invalid event schema, timestamp, or forbidden control-plane fields") from None
        except sqlite3.Error:
            raise HTTPException(503, "Telemetry storage unavailable") from None
        return {"accepted": count, "received": len(batch.events)}

    return app


def main() -> None:
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("BIND_HOST", "0.0.0.0"), port=4318)


if __name__ == "__main__":
    main()
