// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

/** Best-effort, bounded export. Network failure can never block an application request. */
public final class TelemetryExporter {
    private static final Logger LOG = LoggerFactory.getLogger(TelemetryExporter.class);
    private final ArrayBlockingQueue<TelemetryEvent> queue = new ArrayBlockingQueue<>(2000);
    private final ScheduledExecutorService worker;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(700)).build();
    private final ObjectMapper mapper;
    private final URI endpoint;
    private final String token;
    private final String service;
    private final AtomicLong dropped = new AtomicLong();

    public TelemetryExporter(String service, URI endpoint, String token, ObjectMapper mapper) {
        if (token == null || token.isBlank()) throw new IllegalArgumentException("TELEMETRY_INGEST_TOKEN is required");
        this.service = service;
        this.endpoint = endpoint;
        this.token = token;
        this.mapper = mapper;
        this.worker = Executors.newSingleThreadScheduledExecutor(r -> {
            var thread = new Thread(r, "bounded-telemetry-exporter");
            thread.setDaemon(true);
            return thread;
        });
        worker.scheduleWithFixedDelay(this::flush, 100, 200, TimeUnit.MILLISECONDS);
    }

    public void record(TraceContext context, String name, Instant startedAt, double durationMs,
                       int status, String message, Map<String, Object> attributes, boolean server) {
        String level = status >= 400 ? "ERROR" : "INFO";
        String completedAt = Instant.now().toString();
        offer(new TelemetryEvent("span", service, startedAt.toString(), context.traceId(), context.spanId(),
                context.parentSpanId(), name, durationMs, status, level, message, Map.copyOf(attributes)));
        if (server) offer(new TelemetryEvent("metric", service, completedAt, context.traceId(), context.spanId(),
                context.parentSpanId(), name, durationMs, status, level, message, Map.copyOf(attributes)));
        offer(new TelemetryEvent("log", service, completedAt, context.traceId(), context.spanId(),
                context.parentSpanId(), name, durationMs, status, level, message, Map.copyOf(attributes)));
        var previous = MDC.getCopyOfContextMap();
        try {
            // ECS reads MDC. Do not duplicate these keys in fluent pairs; client logs need their own span.
            MDC.put("trace_id", context.traceId());
            MDC.put("span_id", context.spanId());
            var line = status >= 400 ? LOG.atError() : LOG.atInfo();
            line.addKeyValue("parent_span_id", context.parentSpanId())
                    .addKeyValue("duration_ms", durationMs).addKeyValue("status_code", status)
                    .addKeyValue("attributes", attributes).log(message);
        } finally {
            if (previous == null) MDC.clear(); else MDC.setContextMap(previous);
        }
    }

    private void offer(TelemetryEvent event) {
        if (!queue.offer(event)) reportDropped(1);
    }

    private void reportDropped(long count) {
        long total = dropped.addAndGet(count);
        LOG.atWarn().addKeyValue("dropped_events", total)
                .log("Telemetry export unavailable or queue full; observations were lost");
    }

    private void flush() {
        var batch = new ArrayList<TelemetryEvent>(100);
        queue.drainTo(batch, 100);
        if (batch.isEmpty()) return;
        try {
            var request = HttpRequest.newBuilder(endpoint).timeout(Duration.ofMillis(1500))
                    .header("Content-Type", "application/json").header("X-Telemetry-Token", token)
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(Map.of("events", batch)))).build();
            int status = client.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
            if (status < 200 || status >= 300) reportDropped(batch.size());
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            reportDropped(batch.size());
        } catch (Exception failed) {
            // Neither destination credentials nor exception messages enter application telemetry.
            reportDropped(batch.size());
        }
    }

    public long droppedEvents() { return dropped.get(); }

    @PreDestroy
    public void close() {
        worker.shutdown();
        try {
            if (!worker.awaitTermination(2, TimeUnit.SECONDS)) worker.shutdownNow();
        } catch (InterruptedException interrupted) {
            worker.shutdownNow();
            Thread.currentThread().interrupt();
        }
        client.close();
    }
}
