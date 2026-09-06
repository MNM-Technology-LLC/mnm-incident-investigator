// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.regex.Pattern;

/** A minimal W3C version-00 trace context: every request creates a new span. */
public record TraceContext(String traceId, String spanId, String parentSpanId) {
    public static final String REQUEST_ATTRIBUTE = TraceContext.class.getName();
    private static final Pattern TRACEPARENT = Pattern.compile("00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})");
    private static final SecureRandom RANDOM = new SecureRandom();

    public static TraceContext fromParent(String header) {
        if (header != null && header.length() == 55) {
            var matcher = TRACEPARENT.matcher(header);
            if (matcher.matches() && !matcher.group(1).equals("0".repeat(32)) && !matcher.group(2).equals("0".repeat(16))) {
                return new TraceContext(matcher.group(1), newId(8), matcher.group(2));
            }
        }
        return new TraceContext(newId(16), newId(8), null);
    }

    public TraceContext child() { return new TraceContext(traceId, newId(8), spanId); }
    public String traceparent() { return "00-" + traceId + "-" + spanId + "-01"; }

    private static String newId(int bytes) {
        byte[] value = new byte[bytes];
        do { RANDOM.nextBytes(value); } while (HexFormat.of().formatHex(value).equals("0".repeat(bytes * 2)));
        return HexFormat.of().formatHex(value);
    }
}
