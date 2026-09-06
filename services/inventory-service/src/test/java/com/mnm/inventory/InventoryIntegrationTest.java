// SPDX-License-Identifier: Apache-2.0
package com.mnm.inventory;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"telemetry.token=test-ingest-token", "control.token=test-control-token"})
class InventoryIntegrationTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final CopyOnWriteArrayList<JsonNode> EVENTS = new CopyOnWriteArrayList<>();
    private static final HttpServer RECEIVER;
    @LocalServerPort int port;

    static {
        try {
            RECEIVER = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            RECEIVER.createContext("/v1/events", exchange -> {
                MAPPER.readTree(exchange.getRequestBody()).get("events").forEach(EVENTS::add);
                exchange.sendResponseHeaders(202, -1);
                exchange.close();
            });
            RECEIVER.start();
        } catch (IOException error) { throw new ExceptionInInitializerError(error); }
    }

    @DynamicPropertySource static void configure(DynamicPropertyRegistry registry) {
        registry.add("telemetry.endpoint", () -> "http://127.0.0.1:" + RECEIVER.getAddress().getPort() + "/v1/events");
    }
    @AfterAll static void stop() { RECEIVER.stop(0); }

    private HttpResponse<String> call(String path, String body, String token) throws Exception {
        try (var client = HttpClient.newHttpClient()) {
            var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(Duration.ofSeconds(5));
            if (body != null) request.header("X-Demo-Control-Token", token).header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
            else request.GET();
            return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
        }
    }

    @Test void faultIsProtectedObservableAndReversibleWithoutExportingControlState() throws Exception {
        assertEquals(403, call("/internal/fault", "{\"enabled\":true}", "incorrect").statusCode());
        var healthy = call("/api/inventory", null, null);
        assertEquals(200, healthy.statusCode());
        assertEquals(200, call("/internal/fault", "{\"enabled\":true}", "test-control-token").statusCode());
        long started = System.nanoTime();
        var delayed = call("/api/inventory", null, null);
        double delayedMs = (System.nanoTime() - started) / 1_000_000.0;
        assertEquals(200, delayed.statusCode());
        assertTrue(delayedMs >= 1750, "The injected behavior must be actual latency");
        assertEquals(200, call("/internal/fault", "{\"enabled\":false}", "test-control-token").statusCode());
        var recovered = call("/api/inventory", null, null);
        assertEquals(200, recovered.statusCode());
        String recoveredTrace = MAPPER.readTree(recovered.body()).get("trace_id").asText();
        long deadline = System.nanoTime() + 5_000_000_000L;
        while (EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(recoveredTrace)).count() < 3 && System.nanoTime() < deadline) Thread.sleep(20);
        assertEquals(9, EVENTS.size(), "Exactly three observed application requests, each with span/log/metric");
        assertTrue(EVENTS.stream().allMatch(e -> e.get("name").asText().equals("HTTP GET /api/inventory")));
        assertTrue(EVENTS.stream().noneMatch(e -> e.toString().contains("fault") || e.toString().contains("enabled") || e.toString().contains("test-control-token")));
        var metric = EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(recoveredTrace) && e.get("kind").asText().equals("metric")).findFirst().orElseThrow();
        assertTrue(metric.get("duration_ms").asDouble() < 600, "Reset restores latency inside the orders timeout");
    }

    @Test void livenessDoesNotAdvertiseScenarioStateOrCreateApplicationMetrics() throws Exception {
        int before = EVENTS.size();
        var health = call("/actuator/health", null, null);
        assertEquals("{\"status\":\"UP\"}", health.body());
        Thread.sleep(250);
        assertEquals(before, EVENTS.size());
    }

    @Test void rejectsMissingControlValue() throws Exception {
        assertEquals(400, call("/internal/fault", "{}", "test-control-token").statusCode());
        assertEquals(400, call("/internal/fault", "{\"enabled\":\"true\"}", "test-control-token").statusCode());
    }
}
