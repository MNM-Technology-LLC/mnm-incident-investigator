"""Schemas at the model trust boundary; model output never grants permissions."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Service = Literal["orders-service", "inventory-service"]
EvidenceId = Annotated[str, Field(pattern=r"^ev_[0-9a-f]{16,64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Window(StrictModel):
    start: str
    end: str

    @model_validator(mode="after")
    def validate_utc(self):
        start, end = (datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (self.start, self.end))
        if any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in (start, end)):
            raise ValueError("Explicit UTC timestamps are required")
        if not 0 < (end - start).total_seconds() <= 900:
            raise ValueError("The observation window must be positive and at most 15 minutes")
        return self


class OptionalServiceWindow(Window):
    service: Service | None = None


class ServiceWindow(Window):
    service: Service


class LogWindow(ServiceWindow):
    level: Literal["INFO", "WARN", "ERROR"] | None = None
    trace_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None
    limit: Annotated[int, Field(ge=1, le=50)] = 20


class TraceWindow(Window):
    trace_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


TOOL_ARGUMENTS = {
    "get_service_health": OptionalServiceWindow,
    "get_service_map": OptionalServiceWindow,
    "query_metrics": ServiceWindow,
    "search_logs": LogWindow,
    "get_trace": TraceWindow,
}


class Citation(StrictModel):
    id: EvidenceId = Field(description="Copy the complete evidence_id string from a retrieved tool result, including its ev_ prefix and full hash.")
    reason: Text = Field(description="Explain the specific observation in this retrieved result that supports the assessment.")


class Diagnosis(StrictModel):
    assessment: Literal["incident", "healthy", "incomplete"]
    impact: Text
    likely_cause: Text
    confidence: Literal["low", "moderate", "high"]
    confidence_basis: Text
    evidence: Annotated[list[Citation], Field(max_length=12, description="An array of objects, each with id and reason strings. Use complete retrieved evidence IDs, never plain strings or shortened IDs.")]
    uncertainty: Annotated[list[Text], Field(min_length=1, max_length=8, description="An array of strings explaining what the telemetry cannot establish, including any unknown underlying cause.")]
    next_steps: Annotated[list[Text], Field(min_length=1, max_length=8, description="An array of strings describing concrete additional observations or engineer actions that would resolve the uncertainty.")]


def inline_local_schema_refs(schema: dict) -> dict:
    """Expand local JSON Schema references for model tool descriptions.

    Pydantic remains the runtime validator. The returned schema is a fresh tree;
    reference siblings use allOf so overlapping constraints are preserved.
    Recursive and external references are deliberately unsupported for this
    finite output schema and fail during construction instead of weakening it.
    """
    def expand(value, references=()):
        if isinstance(value, list):
            return [expand(item, references) for item in value]
        if not isinstance(value, dict):
            return value
        siblings = {key: expand(item, references) for key, item in value.items() if key not in {"$defs", "$ref"}}
        if "$ref" not in value:
            return siblings
        reference = value["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/") or reference in references:
            raise ValueError("Only finite local JSON Schema references can be expanded")
        target = schema
        try:
            for component in reference[2:].split("/"):
                target = target[component.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise ValueError("JSON Schema reference does not resolve") from None
        resolved = expand(target, (*references, reference))
        return {"allOf": [resolved, siblings]} if siblings else resolved

    return expand(schema)
