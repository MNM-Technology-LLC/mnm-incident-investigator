#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Capture the actual running UI and provenance. Never mocks APIs or changes demo state.

    uv run python scripts/capture_ui.py --output docs/screenshots/healthy.png
    uv run python scripts/capture_ui.py --job-id <32-hex-id> --output docs/screenshots/incident.png

Requires `uv run playwright install chromium` and the application stack.
The JSON sidecar identifies the capture time, actual endpoints, and retrieved records.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--job-id", help="Existing investigation ID; does not start an investigation")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        parser.error("--base-url must be an HTTP(S) application origin without query or fragment")
    if args.job_id and not re.fullmatch(r"[a-f0-9]{32}", args.job_id):
        parser.error("--job-id must be a 32-character lowercase hexadecimal identifier")
    if args.width < 320 or args.height < 320:
        parser.error("Viewport dimensions must be at least 320 pixels")
    url = base + "/" + ("?" + urlencode({"investigation": args.job_id}) if args.job_id else "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda event: errors.append(event.text) if event.type == "error" else None)

        def get(path: str):
            response = page.request.get(base + path, timeout=30000)
            if not response.ok:
                raise RuntimeError(f"Actual endpoint {path} returned HTTP {response.status}")
            return response.json()

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#last-updated")).not_to_have_text("Waiting for first observation", timeout=30000)
        expect(page.locator("#model-label")).not_to_have_text("Checking local model", timeout=30000)
        job = get(f"/api/investigations/{args.job_id}") if args.job_id else None
        if job:
            if job.get("mode") != "live":
                raise RuntimeError("Refusing a showcase capture of a non-live investigation")
            expect(page.locator("#timeline-meta")).to_contain_text("Live AI investigation", timeout=30000)
            expect(page.locator("#investigation-state")).not_to_contain_text("Loading", timeout=30000)
        evidence_ids = sorted({
            event["evidence_id"] for event in (job or {}).get("timeline", []) if event.get("evidence_id")
        } | {
            citation["id"] for citation in ((job or {}).get("diagnosis") or {}).get("evidence", [])
        })
        for evidence_id in evidence_ids:
            if not re.fullmatch(r"ev_[a-f0-9]{8,64}", evidence_id):
                raise RuntimeError(f"Invalid evidence ID in retrieved investigation: {evidence_id}")
            get(f"/api/evidence/{evidence_id}")
        metadata = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": "Actual running application; no route mocks, replay data, or screenshot alterations",
            "url": url,
            "viewport": {"width": args.width, "height": args.height},
            "investigation": job,
            "resolved_evidence_ids": evidence_ids,
            "dashboard": get("/api/dashboard"),
            "recovery": get("/api/demo/recovery"),
            "model": get("/api/model"),
            "browser_errors": errors,
        }
        page.screenshot(path=str(args.output), full_page=True, animations="disabled")
        sidecar = args.output.with_suffix(".json")
        sidecar.write_text(json.dumps(metadata, indent=2) + "\n")
        browser.close()
    if errors:
        raise RuntimeError(f"Captured UI reported browser errors: {errors}")
    print(f"Captured actual UI: {args.output}\nProvenance: {sidecar}")


if __name__ == "__main__":
    main()
