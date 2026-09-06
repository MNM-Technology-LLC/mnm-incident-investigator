# Contributing

Keep the project focused on an investigation an engineer can reproduce and verify. New scenarios should preserve the healthy baseline, observation-only investigator, bounded traffic, recovery check, and honest missing-data behavior.

Install Python 3.12, uv, Java 21, and Maven 3.9. Run from this directory:

```sh
uv sync --frozen
make test
make native
```

`JAVA_HOME` selects Java 21; `MAVEN_BIN` can select a Maven executable. Native mode binds services to loopback and stops them together on Ctrl-C. Use Compose to test network and read-only volume boundaries. `make up` starts Compose; `make smoke` checks the actual Java-to-MCP path without a model; `make down` stops it. Do not run native and Compose stacks on the same ports.

Before opening a pull request:

- Explain the concrete problem and resulting behavior. Include relevant commands and results, and identify anything untested.
- Preserve strict MCP schemas, service/time filters, immutable evidence IDs, fixed investigation windows, and explicit missing-data states. Add meaningful tests for changed boundaries or behavior.
- Keep operator credentials, fault state, and scenario answers out of telemetry and model context. Treat all telemetry text as untrusted; never add a shell or unrestricted network tool.
- Keep screenshots connected to real measurements. Retain a measured live evaluation report when changing agent prompts or model behavior; label mock-based tests separately.
- Run `make test` and, for runtime changes, `make smoke`. Model evaluation is separate; see [verification](docs/verification.md).
- Review new dependency licenses and update [dependencies](docs/dependencies.md). Do not commit `.env`, `.runtime`, database files, downloaded models, build outputs, or real client data.

The file map and request contracts are in [CONTRACT.md](CONTRACT.md); the broader design is in [architecture](docs/architecture.md). A standalone copy of this directory is the repository root for its GitHub Actions workflow.

By submitting an intentional contribution, you offer it under this project's Apache-2.0 license, consistent with section 5 of [LICENSE](LICENSE). Report security concerns according to [SECURITY.md](SECURITY.md).
