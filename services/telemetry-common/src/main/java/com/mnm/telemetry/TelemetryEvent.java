// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import java.util.Map;

/** Only observations are exportable; control state is deliberately absent. */
public record TelemetryEvent(String kind, String service, String timestamp, String trace_id,
        String span_id, String parent_span_id, String name, double duration_ms,
        int status_code, String level, String message, Map<String, Object> attributes) { }
