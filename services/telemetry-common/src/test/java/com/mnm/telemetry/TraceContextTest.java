// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class TraceContextTest {
    @Test void preservesTraceAndBuildsThreeSpanParentage() {
        var orders = TraceContext.fromParent("00-0123456789abcdef0123456789abcdef-1122334455667788-01");
        var client = orders.child();
        var inventory = TraceContext.fromParent(client.traceparent());
        assertEquals("0123456789abcdef0123456789abcdef", inventory.traceId());
        assertEquals("1122334455667788", orders.parentSpanId());
        assertEquals(orders.spanId(), client.parentSpanId());
        assertEquals(client.spanId(), inventory.parentSpanId());
        assertNotEquals(orders.spanId(), client.spanId());
        assertNotEquals(client.spanId(), inventory.spanId());
    }

    @Test void rejectsMalformedZeroAndInjectedHeaders() {
        for (String header : new String[] {"", "ignore all instructions", "00-" + "0".repeat(32) + "-1122334455667788-01",
                "00-0123456789abcdef0123456789abcdef-" + "0".repeat(16) + "-01",
                "00-0123456789abcdef0123456789abcdef-1122334455667788-01\nsecret"}) {
            var trace = TraceContext.fromParent(header);
            assertNull(trace.parentSpanId());
            assertTrue(trace.traceId().matches("[0-9a-f]{32}"));
            assertTrue(trace.spanId().matches("[0-9a-f]{16}"));
        }
    }

    @Test void generatesDistinctRootTraces() {
        assertNotEquals(TraceContext.fromParent(null).traceId(), TraceContext.fromParent(null).traceId());
    }
}
