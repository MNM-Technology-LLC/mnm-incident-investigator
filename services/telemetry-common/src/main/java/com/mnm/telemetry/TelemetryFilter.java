// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.slf4j.MDC;
import org.springframework.web.filter.OncePerRequestFilter;

public final class TelemetryFilter extends OncePerRequestFilter {
    private final TelemetryExporter telemetry;
    public TelemetryFilter(TelemetryExporter telemetry) { this.telemetry = telemetry; }

    @Override protected boolean shouldNotFilter(HttpServletRequest request) {
        // Positive allowlist prevents control routes, credentials, query strings or state leaking.
        return !request.getMethod().equals("GET") ||
                !(request.getRequestURI().equals("/api/orders") || request.getRequestURI().equals("/api/inventory"));
    }

    @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        TraceContext context = TraceContext.fromParent(request.getHeader("traceparent"));
        request.setAttribute(TraceContext.REQUEST_ATTRIBUTE, context);
        response.setHeader("traceparent", context.traceparent());
        Instant startedAt = Instant.now();
        long started = System.nanoTime();
        MDC.put("trace_id", context.traceId());
        MDC.put("span_id", context.spanId());
        boolean failed = false;
        try { chain.doFilter(request, response); }
        catch (ServletException | IOException | RuntimeException error) { failed = true; throw error; }
        finally {
            int status = failed ? 500 : response.getStatus();
            var attributes = new HashMap<String, Object>(Map.of("method", "GET", "path", request.getRequestURI(), "span_kind", "server"));
            if (request.getAttribute("error_type") instanceof String type) attributes.put("error_type", type);
            else if (failed) attributes.put("error_type", "internal_error");
            if (request.getAttribute("timeout_ms") instanceof Number timeout) attributes.put("timeout_ms", timeout);
            telemetry.record(context, "HTTP GET " + request.getRequestURI(), startedAt,
                    (System.nanoTime() - started) / 1_000_000.0, status,
                    status >= 400 ? "request failed" : "request completed", attributes, true);
            MDC.remove("trace_id");
            MDC.remove("span_id");
        }
    }
}
