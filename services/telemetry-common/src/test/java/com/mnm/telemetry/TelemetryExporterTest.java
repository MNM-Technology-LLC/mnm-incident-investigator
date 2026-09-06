// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;

class TelemetryExporterTest {
    @Test void exportsMeasuredServerAndClientEventsWithTokenAndCorrelation() throws Exception {
        var mapper = new ObjectMapper();
        var received = new CopyOnWriteArrayList<JsonNode>();
        var tokens = new CopyOnWriteArrayList<String>();
        var receiver = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        receiver.createContext("/v1/events", exchange -> {
            tokens.add(exchange.getRequestHeaders().getFirst("X-Telemetry-Token"));
            mapper.readTree(exchange.getRequestBody()).get("events").forEach(received::add);
            exchange.sendResponseHeaders(202, -1);
            exchange.close();
        });
        receiver.start();
        var exporter = new TelemetryExporter("orders-service", URI.create("http://127.0.0.1:" + receiver.getAddress().getPort() + "/v1/events"), "test-ingest-token", mapper);
        try {
            var server = TraceContext.fromParent(null);
            exporter.record(server, "HTTP GET /api/orders", Instant.now(), 612.3, 504, "request failed",
                    Map.of("span_kind", "server", "path", "/api/orders", "error_type", "timeout"), true);
            exporter.record(server.child(), "inventory.request", Instant.now(), 603.2, 504, "inventory request timed out",
                    Map.of("span_kind", "client", "peer_service", "inventory-service", "error_type", "timeout", "timeout_ms", 600), false);
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (received.size() < 5 && System.nanoTime() < deadline) Thread.sleep(20);
            assertEquals(5, received.size());
            assertEquals(1, received.stream().filter(e -> e.get("kind").asText().equals("metric")).count(), "Only server requests enter request statistics");
            assertEquals(2, received.stream().filter(e -> e.get("kind").asText().equals("span")).count());
            assertTrue(received.stream().allMatch(e -> e.get("trace_id").asText().equals(server.traceId())));
            assertTrue(tokens.stream().allMatch("test-ingest-token"::equals));
            assertTrue(received.stream().anyMatch(e -> e.get("duration_ms").asDouble() == 612.3));
            assertEquals(0, exporter.droppedEvents());
        } finally { exporter.close(); receiver.stop(0); }
    }

    @Test void failsClosedWithoutIngestToken() {
        assertThrows(IllegalArgumentException.class, () -> new TelemetryExporter("orders-service", URI.create("http://127.0.0.1:1/v1/events"), "", new ObjectMapper()));
    }

    @Test void unavailableCollectorDoesNotBlockRequestAndReportsLoss() throws Exception {
        var refused = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        int port = refused.getAddress().getPort();
        refused.stop(0);
        var exporter = new TelemetryExporter("orders-service", URI.create("http://127.0.0.1:" + port + "/v1/events"), "test", new ObjectMapper());
        try {
            long started = System.nanoTime();
            exporter.record(TraceContext.fromParent(null), "HTTP GET /api/orders", Instant.now(), 15, 200, "request completed", Map.of("span_kind", "server"), true);
            assertTrue((System.nanoTime() - started) / 1_000_000 < 300);
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (exporter.droppedEvents() == 0 && System.nanoTime() < deadline) Thread.sleep(20);
            assertEquals(3, exporter.droppedEvents());
        } finally { exporter.close(); }
    }
}
