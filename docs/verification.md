# Verification record

This record distinguishes deterministic verification from real local-model evaluation. All retained application data is synthetic. Verification took place on September 5, 2026 in America/Chicago (September 6 UTC). Container runtime execution is explicitly unverified on this host.

## Environment actually used

- Apple M4 Max, 36 GiB unified RAM, macOS 26.3.1 on ARM64.
- Temurin Java 21.0.12.1, Maven 3.9.11, Spring Boot 3.5.16, Python 3.12.13.
- Ollama 0.22.0 with the downloaded `qwen3:8b` Q4_K_M model, approximately 5.2 GB; local Metal inference, no cloud service or credentials.
- Frozen Python dependency resolution in `uv.lock`.
- Chromium through Playwright 1.62.0 for real UI captures and separately labeled browser fixture tests.
- Docker Compose v2.39.4 CLI for configuration validation. **Docker Engine was not installed**, so images and Compose runtime/teardown were not executed here.

The project-native launcher (`scripts/dev.py --skip-build`) started the telemetry receiver, MCP server, both actual Java services, investigator API, and console. It was also stopped and restarted through its cleanup path. Native mode uses loopback processes and does not enforce Compose's container network and read-only mount boundaries.

## Deterministic checks actually run

| Check | Result |
| --- | --- |
| `.venv/bin/pytest` with `MNM_BROWSER=1` | **161 passed, 1 skipped**; the skip is the separately invoked running-stack integration wrapper |
| `.venv/bin/ruff check investigator tests scripts` | Passed |
| Java 21 Maven `verify` for `services/pom.xml` | **12 passed**, all three modules built |
| Real Java stack `scripts/smoke.py` | **6 checks passed**; 14 actual evidence snapshots resolved |
| `MNM_INTEGRATION=1 pytest tests/test_integration.py` | **1 passed**; separately reran the real-stack smoke against the final source |
| Compose `config --quiet` | Passed; six services, isolated networks, one loopback browser port |
| Python wheel build and isolated wheel installation | Passed; browser assets, LICENSE, and NOTICE included and served |
| Read-only SQLite/WAL test | Passed; reads a recent WAL commit and rejects attempted SQL writes |
| Java JAR license inspection | LICENSE, NOTICE, and dependency review included in all three JARs |

The full Python run includes 17 Chromium regressions for 320–1440 px layouts, recovery tables, keyboard/dialog focus, safe evidence rendering, invalid/expired investigation links, and unavailable/incomplete/failed states. Those browser state fixtures and scripted model adapters are **deterministic tests, not live AI evaluations**. Two installed-library deprecation warnings were emitted; no test failures remained.

The [retained smoke report](evaluations/smoke.json) records actual HTTP traffic and retrieved MCP query results. Its equally long eight-second windows contain eight requests per phase. The browser's separate recovery comparison uses 30-second windows with continuous traffic. The smoke check verifies healthy HTTP 200 responses, faulted HTTP 504 responses, trace/log correlation, resolving citations, absent-telemetry semantics, prohibited tools, and HTTP 200 recovery after reset. It does not invoke a model.

Security tests exercise malformed/forbidden tools, embedded log instructions, quoted secret redaction, query-window constraints, evidence tampering, streaming body limits, Host/Origin restrictions, and explicit Compose separation. They demonstrate these code-enforced boundaries, not universal resistance to every possible semantic prompt injection.

## Live model evaluation

Live evaluation uses `scripts/evaluate.py`. It asks the same question, “Why are orders failing?”, through the running investigation API and verifies cited evidence membership and snapshot checksums. Its `--expect` assertion is never supplied to the investigator. Each retained report includes the actual timeline, model assessment, and evidence snapshots so its citations remain inspectable after `make reset`.

The following three final evaluations used the selected `qwen3:8b` model and the final controller through the browser-facing API. Each used a fixed 30-second observation window. All expected assessments passed, and every citation resolved to a retrieved snapshot with a valid checksum.

| Real observation window | Actual model result | Elapsed time | Retained report |
| --- | --- | --- | --- |
| Healthy: 60 completed requests per service, zero errors | Healthy, high confidence; no incident inferred from the question | 21.333 s | [Healthy evaluation](evaluations/live-healthy.json), 5 citations |
| Fault: 60 orders errors/timeouts; inventory completed successfully after the caller timed out | Incident, high confidence; underlying reason for inventory delay remains unknown | 20.289 s | [Incident evaluation](evaluations/live-fault.json), 3 citations |
| Empty window after traffic stopped and exports settled | Incomplete, low confidence; absence of records does not establish zero traffic or zero errors | 22.336 s | [Missing-telemetry evaluation](evaluations/live-missing.json), 5 citations |

The incident's cited trace contains an orders HTTP client span of **600.581 ms**, HTTP 504 and an observed **600 ms** timeout setting. Its correlated inventory server child lasted **1,803.382 ms** and returned HTTP 200. These measurements support the downstream-delay mechanism; the model cannot observe the operator's fault state or establish the underlying reason for that delay.

Earlier development runs with `qwen3:4b` and `qwen2.5:7b` exposed format retries and incomplete results. A [representative earlier incomplete run](evaluations/development-incomplete.json) is retained separately and is not a passing evaluation. Investigation found premature assessment guidance before any tool result and missing citation fields in a submitted assessment. The final controller requires a model-chosen telemetry call before normal assessment submission, expands nested output schemas, supplies safe field-specific validation feedback, and reserves its final turn for synthesis. The typed `submit_assessment` function performs no I/O; MCP still exposes only its five read-only telemetry tools.

These are individual real runs, not a reliability benchmark. Temperature zero does not guarantee identical tool choices or wording. Every natural-language claim still needs engineering review against its cited data, and an observed downstream delay does not establish why inventory was slow.

## Actual browser and recovery

The [healthy](screenshots/healthy.png), [incident](screenshots/incident.png), and [recovery](screenshots/recovery.png) images were captured from the running Java/Python application with real Ollama jobs. Their adjacent JSON files record capture time, actual API responses, resolved evidence IDs, and zero browser errors. No response mocking, replayed results, or screenshot alterations were used. Separate checks of the actual completed incident and recovery view at 320, 390, 768, 1024, and 1440 px found no horizontal overflow or browser errors.

The actual browser's **Reset fault** button was clicked while traffic continued. Both services completed **60 requests in each 30-second window**. Orders errors and timeouts fell from **60 to 0**; orders p95 fell from **603.319 ms to 21.017 ms**, and inventory p95 from **1,806.673 ms to 16.575 ms**. The [recovery report](evaluations/recovery.json) includes all four resolving query snapshots and explicitly limits recovery to the observed windows. This comparison is deterministic measurement following an operator action; it is not a model-generated recovery claim.

## Reproduce

With development prerequisites installed:

```sh
uv sync --frozen
uv run playwright install chromium
MNM_BROWSER=1 uv run --frozen pytest -q
mvn -B -ntp -f services/pom.xml verify
make up
make smoke
```

For host development, use `make native` instead of `make up`; in a second terminal run:

```sh
uv run --frozen python scripts/smoke.py --output .runtime/smoke-report.json
```

Set up the actual model as documented in [model setup](model-setup.md). Use the browser controls to establish each observation window, then run:

```sh
uv run --frozen python scripts/evaluate.py --expect healthy --output .runtime/live-healthy.json
# Trigger the fault and collect a full window before the next command.
uv run --frozen python scripts/evaluate.py --expect incident --output .runtime/live-fault.json
# Stop traffic and allow at least 33 seconds for an empty observation window.
uv run --frozen python scripts/evaluate.py --expect incomplete --output .runtime/live-missing.json
```

Capture the actual browser with an existing live job ID:

```sh
uv run --frozen python scripts/capture_ui.py --job-id JOB_ID --output .runtime/incident.png
```

The capture command uses no mocked responses and also writes provenance JSON. See the [release audit](release-audit.md) for wheel, WAL, and deployment checks, and [troubleshooting](troubleshooting.md) for failure states.

## Remaining limitations

- Docker builds, actual container isolation, Compose startup/reset, and the GitHub Actions workflow still need execution on a Docker-capable host. Configuration validation and native execution do not establish those results.
- The small telemetry receiver uses a custom documented JSON protocol, not OTLP. Best-effort exporters can drop observations; no-data results remain unknown. Traces can be partial at window boundaries.
- Query snapshots persist until a clean reset and can grow with prolonged use; investigation jobs are bounded and in memory. Archived evaluation JSON preserves its own cited snapshots independently.
- Regular-expression redaction and schema/citation validation do not establish semantic truth or exhaustive secret detection. The demo is local and synthetic, with no production multi-user authentication.
- The local model's inference time and investigation quality vary with model version, hardware, and observations. A bounded incomplete assessment is an intended honest outcome when support is insufficient.
