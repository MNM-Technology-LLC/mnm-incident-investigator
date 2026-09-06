# SPDX-License-Identifier: Apache-2.0
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY . .
RUN mvn -B -ntp -DskipTests package

FROM eclipse-temurin:21-jre-jammy AS runtime
ARG SERVICE
RUN useradd --system --uid 10001 --create-home mnm
WORKDIR /app
COPY --from=build --chown=10001:10001 /build/${SERVICE}/target/${SERVICE}-1.0.0.jar /app/app.jar
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md /app/
USER 10001:10001
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=65 -XX:+ExitOnOutOfMemoryError"
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
