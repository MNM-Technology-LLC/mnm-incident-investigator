#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluate the REAL local model against the current application observation window.

Run after establishing healthy traffic, a fault, or a window without telemetry.
--expect is an evaluator assertion, never provided to the investigator/model.
This script performs no fault injection and never substitutes a mock model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import httpx


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--expect", choices=("healthy", "incident", "incomplete"))
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path(".runtime/live-evaluation.json"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    start = time.monotonic()
    report = {"mode": "live", "expected_assessment": args.expect, "passed": False,
              "note": "One real local-model run; this is not a statistical reliability estimate.", "evidence": []}
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.get(base + "/api/model")
            response.raise_for_status()
            report["model_status"] = response.json()
            if not report["model_status"].get("available"):
                raise RuntimeError("The real local model is unavailable; no mock substitution was made")
            response = client.post(base + "/api/investigations", json={
                "question": "Why are orders failing?", "window_seconds": args.window_seconds,
            })
            response.raise_for_status()
            job_id = response.json()["id"]
            print(f"Live investigation {job_id} · {report['model_status']['model']}", flush=True)
            last = 0
            while time.monotonic() - start < 270:
                response = client.get(base + "/api/investigations/" + job_id)
                response.raise_for_status()
                job = response.json()
                report["investigation"] = job
                for event in job["timeline"][last:]:
                    print(f"{event['type']}: {event.get('summary', '')}", flush=True)
                last = len(job["timeline"])
                if job["status"] != "running":
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Evaluation exceeded its polling deadline")
            if job["status"] != "complete" or not job.get("diagnosis"):
                raise RuntimeError("Live investigation failed: " + (job.get("error") or job["status"]))
            retrieved = {event["evidence_id"] for event in job["timeline"] if event.get("evidence_id")}
            for citation in job["diagnosis"]["evidence"]:
                evidence_id = citation["id"]
                if evidence_id not in retrieved:
                    raise RuntimeError("The diagnosis cited evidence not retrieved during this investigation")
                response = client.get(base + "/api/evidence/" + evidence_id)
                response.raise_for_status()
                snapshot = response.json()
                content = {key: value for key, value in snapshot.items() if key != "evidence_id"}
                if "ev_" + hashlib.sha256(canonical(content).encode()).hexdigest() != evidence_id:
                    raise RuntimeError("Evidence checksum did not match its cited identifier")
                report["evidence"].append(snapshot)
            assessment = job["diagnosis"]["assessment"]
            report["passed"] = args.expect is None or assessment == args.expect
            if not report["passed"]:
                report["error"] = f"Expected {args.expect}, received {assessment}; inspect the actual model output"
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as error:
        report["error"] = str(error)
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{'PASS' if report['passed'] else 'FAIL'} · actual live evaluation saved to {args.output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
