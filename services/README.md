# Java demo services

Both services target Java 21 and use Spring Boot 3.5.16. All payloads are synthetic. The root Docker Compose setup builds them with Maven and runs them on Java 21; no local Maven installation is needed for that path.

For Java development, install Java 21 and Maven 3.9, then run from this directory:

```sh
mvn -B -ntp verify
```

The tests launch real local HTTP servers. They verify successful requests, an actual 600 ms downstream timeout, upstream HTTP failure classification, W3C trace propagation and parentage, measured telemetry export, collector unavailability, protected fault control, real inventory latency, and recovery. They do not invoke a language model.

`orders-service` serves `GET /api/orders` on port 8081 and calls `GET /api/inventory` on port 8082. Inventory normally spends approximately 12 ms in its synthetic work; the controlled delay is 1,800 ms. Orders applies a 600 ms total HTTP request timeout and a 400 ms connection timeout. A response timeout returns HTTP 504; other downstream failures return HTTP 502. `GET /actuator/health` is a deliberately minimal liveness endpoint, not a claim that application requests are healthy.

Inventory accepts `POST /internal/fault` with `{"enabled":true}` or `{"enabled":false}` only with the `X-Demo-Control-Token` header. This control belongs to the console network. There is no state inspection endpoint. The investigator never receives the token or an application network route.

Configuration:

| Variable | Service | Default / requirement |
| --- | --- | --- |
| `PORT` | both | 8081 for orders, 8082 for inventory |
| `INVENTORY_URL` | orders | `http://inventory-service:8082` |
| `TELEMETRY_ENDPOINT` | both | `http://telemetry:4318/v1/events` |
| `TELEMETRY_INGEST_TOKEN` | both | Required; set by root setup |
| `DEMO_CONTROL_TOKEN` | inventory | Required; set by root setup |

The intentionally small telemetry implementation records actual server spans, the orders HTTP client span, structured application logs, and one metric observation per completed server request. It propagates W3C version-00 `traceparent`; malformed contexts generate a new trace. The receiver computes rates and percentiles from completed request observations. Span timestamps are request start times; log and metric timestamps are completion times. Durations use the monotonic clock. All requests are sampled for this bounded demo. This is custom instrumentation, not an OpenTelemetry protocol exporter.

Structured console logs use Spring's ECS JSON format and include `trace_id` and `span_id`. Only `GET /api/orders` and `GET /api/inventory` enter the telemetry export path; headers, query strings, request bodies, liveness probes and controls are excluded. Export uses a 2,000-event queue, batches of at most 100, and a 1.5-second network timeout on a dedicated worker. Queue saturation or an unavailable receiver drops observations and emits a local warning; failed batches are not replayed. Missing observations must be treated as missing telemetry, not successful requests. Graceful shutdown is bounded and can discard queued observations.

The Dockerfile takes a `SERVICE` build argument (`orders-service` or `inventory-service`) and runs as an unprivileged user. Spring Boot dependency versions come from the pinned parent BOM. The original Java code is Apache-2.0; see the project's license and dependency notes.
