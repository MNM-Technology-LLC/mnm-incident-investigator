// SPDX-License-Identifier: Apache-2.0
package com.mnm.inventory;

import com.mnm.telemetry.TelemetryConfiguration;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;

@SpringBootApplication
@Import(TelemetryConfiguration.class)
public class InventoryApplication {
    public static void main(String[] args) { SpringApplication.run(InventoryApplication.class, args); }
}
