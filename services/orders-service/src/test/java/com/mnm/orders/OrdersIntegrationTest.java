// SPDX-License-Identifier: Apache-2.0
package com.mnm.orders;

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
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = "telemetry.token=test-ingest-token")
@ExtendWith(OutputCaptureExtension.class)
class OrdersIntegrationTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final CopyOnWriteArrayList<JsonNode> EVENTS = new CopyOnWriteArrayList<>();
    private static final CopyOnWriteArrayList<String> HEADERS = new CopyOnWriteArrayList<>();
    private static final HttpServer DOWNSTREAM = createServer();
    private static final HttpServer RECEIVER = createServer();
    private static volatile int downstreamDelayMs = 12;
    private static volatile int downstreamStatus = 200;
    @LocalServerPort int port;

    static {
        DOWNSTREAM.createContext("/api/inventory", exchange -> {
            HEADERS.add(exchange.getRequestHeaders().getFirst("traceparent"));
            try { Thread.sleep(downstreamDelayMs); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
            try { exchange.sendResponseHeaders(downstreamStatus, -1); } catch (IOException disconnected) { /* caller timed out */ }
            exchange.close();
        });
        DOWNSTREAM.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        RECEIVER.createContext("/v1/events", exchange -> {
            MAPPER.readTree(exchange.getRequestBody()).get("events").forEach(EVENTS::add);
            exchange.sendResponseHeaders(202, -1);
            exchange.close();
        });
        DOWNSTREAM.start();
        RECEIVER.start();
    }

    private static HttpServer createServer() {
        try { return HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0); }
        catch (IOException error) { throw new ExceptionInInitializerError(error); }
    }

    @DynamicPropertySource static void configure(DynamicPropertyRegistry registry) {
        registry.add("inventory.url", () -> "http://127.0.0.1:" + DOWNSTREAM.getAddress().getPort());
        registry.add("telemetry.endpoint", () -> "http://127.0.0.1:" + RECEIVER.getAddress().getPort() + "/v1/events");
    }

    @BeforeEach void baseline() { downstreamDelayMs = 12; downstreamStatus = 200; }
    @AfterAll static void stop() { DOWNSTREAM.stop(0); RECEIVER.stop(0); }

    private HttpResponse<String> order(String traceId) throws Exception {
        try (var client = HttpClient.newHttpClient()) {
            return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/orders"))
                    .timeout(Duration.ofSeconds(5)).header("traceparent", "00-" + traceId + "-1122334455667788-01").GET().build(), HttpResponse.BodyHandlers.ofString());
        }
    }

    private void awaitEvents(String traceId) throws InterruptedException {
        long deadline = System.nanoTime() + 5_000_000_000L;
        while (EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(traceId)).count() < 5 && System.nanoTime() < deadline) Thread.sleep(20);
    }

    @Test void healthyRequestPropagatesTraceAndRecordsSuccess(CapturedOutput output) throws Exception {
        String trace = "0123456789abcdef0123456789abcdef";
        var response = order(trace);
        assertEquals(200, response.statusCode());
        assertEquals("accepted", MAPPER.readTree(response.body()).get("status").asText());
        assertEquals(trace, MAPPER.readTree(response.body()).get("trace_id").asText());
        assertTrue(HEADERS.stream().anyMatch(h -> h.startsWith("00-" + trace + "-")));
        awaitEvents(trace);
        var spans = EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(trace) && e.get("kind").asText().equals("span")).toList();
        assertEquals(2, spans.size());
        var server = spans.stream().filter(e -> e.get("attributes").get("span_kind").asText().equals("server")).findFirst().orElseThrow();
        var client = spans.stream().filter(e -> e.get("attributes").get("span_kind").asText().equals("client")).findFirst().orElseThrow();
        assertEquals(server.get("span_id"), client.get("parent_span_id"));
        assertEquals(200, server.get("status_code").asInt());
        assertTrue(output.getOut().contains("\"trace_id\":\"" + trace + "\""), "Console logs must be structured and correlated");
        assertTrue(output.getOut().contains("\"message\":\"inventory request completed\""));
        assertFalse(output.getAll().contains("failed to append"));
    }

    @Test void downstreamLatencyProducesBoundedTimeoutAndCorrelatedEvidence() throws Exception {
        downstreamDelayMs = 1800;
        String trace = "1123456789abcdef0123456789abcdef";
        var response = order(trace);
        assertEquals(504, response.statusCode());
        assertEquals("inventory_timeout", MAPPER.readTree(response.body()).get("error").asText());
        awaitEvents(trace);
        var metric = EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(trace) && e.get("kind").asText().equals("metric")).findFirst().orElseThrow();
        assertEquals("timeout", metric.get("attributes").get("error_type").asText());
        assertEquals(600, metric.get("attributes").get("timeout_ms").asInt());
        assertTrue(metric.get("duration_ms").asDouble() >= 550);
        assertTrue(metric.get("duration_ms").asDouble() < 1600);
        assertTrue(EVENTS.stream().anyMatch(e -> e.get("trace_id").asText().equals(trace) && e.get("message").asText().equals("inventory request timed out")));
    }

    @Test void downstreamHttpFailureIsNotMisclassifiedAsTimeout() throws Exception {
        downstreamStatus = 503;
        String trace = "2123456789abcdef0123456789abcdef";
        assertEquals(502, order(trace).statusCode());
        awaitEvents(trace);
        var metric = EVENTS.stream().filter(e -> e.get("trace_id").asText().equals(trace) && e.get("kind").asText().equals("metric")).findFirst().orElseThrow();
        assertEquals("upstream_error", metric.get("attributes").get("error_type").asText());
    }
}
