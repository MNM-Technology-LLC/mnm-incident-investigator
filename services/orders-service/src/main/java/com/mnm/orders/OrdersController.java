// SPDX-License-Identifier: Apache-2.0
package com.mnm.orders;

import com.mnm.telemetry.TelemetryExporter;
import com.mnm.telemetry.TraceContext;
import jakarta.annotation.PreDestroy;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrdersController {
    private final TelemetryExporter telemetry;
    private final URI inventoryEndpoint;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(400)).build();
    private static final int TIMEOUT_MS = 600;

    public OrdersController(TelemetryExporter telemetry, @Value("${inventory.url}") URI inventoryBase) {
        this.telemetry = telemetry;
        this.inventoryEndpoint = inventoryBase.resolve("/api/inventory");
    }

    @GetMapping("/actuator/health")
    public Map<String, String> liveness() { return Map.of("status", "UP"); }

    @GetMapping("/api/orders")
    public ResponseEntity<Map<String, String>> order(HttpServletRequest request) {
        TraceContext server = (TraceContext) request.getAttribute(TraceContext.REQUEST_ATTRIBUTE);
        TraceContext clientSpan = server.child();
        Instant startedAt = Instant.now();
        long started = System.nanoTime();
        var attributes = new HashMap<String, Object>(Map.of("peer_service", "inventory-service", "method", "GET",
                "path", "/api/inventory", "span_kind", "client", "timeout_ms", TIMEOUT_MS));
        int status = 500;
        String message = "inventory request failed";
        try {
            var outbound = HttpRequest.newBuilder(inventoryEndpoint).timeout(Duration.ofMillis(TIMEOUT_MS))
                    .header("traceparent", clientSpan.traceparent()).GET().build();
            int downstreamStatus = client.send(outbound, HttpResponse.BodyHandlers.discarding()).statusCode();
            status = downstreamStatus;
            if (downstreamStatus < 200 || downstreamStatus >= 300) {
                attributes.put("error_type", "upstream_error");
                request.setAttribute("error_type", "upstream_error");
                return ResponseEntity.status(502).body(Map.of("error", "inventory_unavailable", "trace_id", server.traceId()));
            }
            message = "inventory request completed";
            return ResponseEntity.ok(Map.of("order_id", UUID.randomUUID().toString(), "status", "accepted", "sku", "DEMO-SKU-001", "trace_id", server.traceId()));
        } catch (HttpTimeoutException timeout) {
            status = 504;
            message = "inventory request timed out";
            attributes.put("error_type", "timeout");
            request.setAttribute("error_type", "timeout");
            request.setAttribute("timeout_ms", TIMEOUT_MS);
            return ResponseEntity.status(504).body(Map.of("error", "inventory_timeout", "trace_id", server.traceId()));
        } catch (IOException unavailable) {
            status = 502;
            attributes.put("error_type", "connection_error");
            request.setAttribute("error_type", "connection_error");
            return ResponseEntity.status(502).body(Map.of("error", "inventory_unavailable", "trace_id", server.traceId()));
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            status = 503;
            attributes.put("error_type", "internal_error");
            request.setAttribute("error_type", "internal_error");
            return ResponseEntity.status(503).body(Map.of("error", "request_interrupted", "trace_id", server.traceId()));
        } finally {
            telemetry.record(clientSpan, "inventory.request", startedAt, (System.nanoTime() - started) / 1_000_000.0,
                    status, message, attributes, false);
        }
    }

    @PreDestroy public void close() { client.close(); }
}
