// SPDX-License-Identifier: Apache-2.0
package com.mnm.telemetry;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
public class TelemetryConfiguration {
    @Bean TelemetryExporter telemetryExporter(@Value("${spring.application.name}") String service,
            @Value("${telemetry.endpoint}") URI endpoint, @Value("${telemetry.token}") String token, ObjectMapper mapper) {
        return new TelemetryExporter(service, endpoint, token, mapper);
    }

    @Bean FilterRegistrationBean<TelemetryFilter> telemetryFilter(TelemetryExporter exporter) {
        var bean = new FilterRegistrationBean<>(new TelemetryFilter(exporter));
        bean.setOrder(1);
        bean.addUrlPatterns("/api/*");
        return bean;
    }
}
