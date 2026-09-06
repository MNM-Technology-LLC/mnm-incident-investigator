// SPDX-License-Identifier: Apache-2.0
package com.mnm.inventory;

import com.mnm.telemetry.TraceContext;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InventoryController {
    private final AtomicBoolean delayed = new AtomicBoolean(false);
    private final byte[] controlToken;

    public InventoryController(@Value("${control.token}") String token) {
        if (token.isBlank()) throw new IllegalArgumentException("DEMO_CONTROL_TOKEN is required");
        controlToken = token.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping("/actuator/health")
    public Map<String, String> liveness() { return Map.of("status", "UP"); }

    @GetMapping("/api/inventory")
    public ResponseEntity<Map<String, Object>> inventory(HttpServletRequest request) {
        try {
            Thread.sleep(delayed.get() ? 1800 : 12);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            request.setAttribute("error_type", "internal_error");
            return ResponseEntity.status(503).body(Map.of("error", "request_interrupted"));
        }
        TraceContext trace = (TraceContext) request.getAttribute(TraceContext.REQUEST_ATTRIBUTE);
        return ResponseEntity.ok(Map.of("sku", "DEMO-SKU-001", "available", true, "trace_id", trace.traceId()));
    }

    public record FaultRequest(Boolean enabled) { }

    /** Separate control API. Never log the request, token, state, or scenario name. */
    @PostMapping("/internal/fault")
    public ResponseEntity<Map<String, String>> fault(
            @RequestHeader(name = "X-Demo-Control-Token", defaultValue = "") String token,
            @RequestBody FaultRequest body) {
        if (!MessageDigest.isEqual(controlToken, token.getBytes(StandardCharsets.UTF_8))) {
            return ResponseEntity.status(403).body(Map.of("error", "forbidden"));
        }
        if (body.enabled() == null) return ResponseEntity.badRequest().body(Map.of("error", "enabled_boolean_required"));
        delayed.set(body.enabled());
        return ResponseEntity.ok(Map.of("status", "applied"));
    }
}
