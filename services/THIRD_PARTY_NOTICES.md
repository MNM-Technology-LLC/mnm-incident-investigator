# Dependencies and license compatibility

Original MNM Incident Investigator code and documentation use [Apache-2.0](../LICENSE). This review checked installed Python distribution metadata, resolved Java runtime JARs and Maven POM license declarations, and the upstream licenses linked below. It covers the current source release's dependency choices, not a complete legal or operating-system binary audit. Dependencies retain their own licenses.

## Compatibility findings

The application uses unmodified libraries under permissive licenses, plus separately licensed MPL/EPL components. Its original source can remain Apache-2.0 with those components kept separate and their notices and source obligations observed. This is not a claim that every component is itself Apache-2.0.

- **certifi** declares MPL-2.0. Its certificate bundle and applicable notices remain under that license. Corresponding source is available from the [certifi source repository](https://github.com/certifi/python-certifi) and the [versioned package distribution](https://pypi.org/project/certifi/2026.7.22/#files). If distributing a built environment, retain its notices and identify the applicable source; modifications to covered files need their MPL terms. Mozilla explicitly discusses combining MPL and Apache code in its [MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).
- **Logback 1.5.34** offers EPL-2.0 or LGPL-2.1-only. This project's compatibility review uses its EPL-2.0 option; it does not change or copy Logback source. Keep its own license and source access when distributing JARs. See the [upstream dual-license declaration](https://raw.githubusercontent.com/qos-ch/logback/master/LICENSE.txt), [Logback source](https://github.com/qos-ch/logback), and versioned [core sources](https://repo.maven.apache.org/maven2/ch/qos/logback/logback-core/1.5.34/logback-core-1.5.34-sources.jar) and [classic sources](https://repo.maven.apache.org/maven2/ch/qos/logback/logback-classic/1.5.34/logback-classic-1.5.34-sources.jar).
- **Jakarta Annotations 2.1.1** declares EPL-2.0 and a GPLv2 alternative with the Classpath Exception. This review uses the EPL-2.0 option. Its [license](https://github.com/jakartaee/common-annotations-api/blob/master/LICENSE.md), [source repository](https://github.com/jakartaee/common-annotations-api), and [versioned sources](https://repo.maven.apache.org/maven2/jakarta/annotation/jakarta.annotation-api/2.1.1/jakarta.annotation-api-2.1.1-sources.jar) remain separate. The [Eclipse EPL FAQ](https://www.eclipse.org/legal/epl-2.0/faq/) explains the distinction between separate modules and modified covered code.
- **MIT, BSD, Apache-2.0, PSF-2.0, and MIT-0 packages** retain their copyright and license notices. Preserve packaged `LICENSE` and `NOTICE` files in redistributed environments. Alternative license expressions are shown as declared, rather than treating them as additional requirements on the original project code.

If publishing prebuilt containers or a complete binary bundle, retain the runtime images' notices and corresponding source information as well. The Dockerfiles use upstream runtime images; they do not relicense the operating system, Python, or Java. Recheck the resolved inventory whenever the lockfile, parent BOM, base images, or model changes.

## Java runtime inventory

The assembled Spring Boot JARs were inspected, including their nested `BOOT-INF/lib` entries. Licenses were checked in available embedded POMs and resolved Maven parent POMs; some JARs do not embed their POM. Both services use the same pinned Spring Boot BOM. The project's own `telemetry-common` is Apache-2.0.

| Resolved component | Version | License / primary source |
| --- | --- | --- |
| Spring Boot and auto-configuration / JAR tooling | 3.5.16 | [Apache-2.0](https://github.com/spring-projects/spring-boot/blob/main/LICENSE.txt) |
| Spring AOP, Beans, Context, Core, Expression, JCL, Web, WebMVC | 6.2.19 | [Apache-2.0](https://github.com/spring-projects/spring-framework/blob/main/LICENSE.txt) |
| Jackson core, databind, JDK8/JSR310 datatypes, parameter names | 2.21.4 | [Apache-2.0](https://github.com/FasterXML/jackson-core/blob/2.21/LICENSE) |
| Jackson annotations | 2.21 | [Apache-2.0](https://github.com/FasterXML/jackson-annotations/blob/2.x/LICENSE) |
| Embedded Tomcat core, EL, WebSocket | 10.1.55 | [Apache-2.0](https://github.com/apache/tomcat/blob/10.1.x/LICENSE) |
| Micrometer observation and commons | 1.15.12 | [Apache-2.0](https://github.com/micrometer-metrics/micrometer/blob/main/LICENSE) |
| Log4j API and SLF4J bridge | 2.24.3 | [Apache-2.0](https://github.com/apache/logging-log4j2/blob/2.x/LICENSE.txt) |
| SLF4J API and JUL bridge | 2.0.18 | [MIT](https://github.com/qos-ch/slf4j/blob/master/LICENSE.txt) |
| Logback core and classic | 1.5.34 | EPL-2.0 OR LGPL-2.1-only; see review above |
| Jakarta Annotations API | 2.1.1 | EPL-2.0 OR GPL-2.0 with Classpath Exception; see review above |
| SnakeYAML | 2.4 | [Apache-2.0](https://bitbucket.org/snakeyaml/snakeyaml/src/master/LICENSE.txt) |

Java test dependencies come through `spring-boot-starter-test`; its JUnit, Mockito, AssertJ, Awaitility, Hamcrest, and JSON testing libraries are development dependencies, not nested runtime JARs. Maven resolves their versions from the BOM. Inspect the full graph when updating it:

```sh
mvn -B -ntp -f services/pom.xml dependency:tree
```

## Python inventory

`uv.lock` fixes the dependency resolution. The following snapshot comes from the installed development environment using `pip-licenses --format=json`; it therefore includes test/browser tooling in addition to runtime packages. The production Dockerfile uses `uv sync --frozen --no-dev`.

Reproduce the metadata check after synchronization:

```sh
uv sync --frozen
uv run --frozen pip-licenses --format=json
```

The reporting tool omits itself and some helper packages from its default output. Their installed metadata was checked separately: `pip-licenses` 5.5.5 (MIT), `prettytable` 3.18.0 (BSD-3-Clause), and `wcwidth` 0.8.3 (MIT). Hatchling is an isolated build dependency, not installed in this runtime environment; its upstream [license is MIT](https://github.com/pypa/hatch/blob/master/LICENSE.txt).

| Package | Installed version | Declared license |
| --- | --- | --- |
| PyJWT | 2.13.0 | MIT |
| PyYAML | 6.0.3 | MIT License |
| Pygments | 2.21.0 | BSD-2-Clause |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| greenlet | 3.5.5 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| httpx-sse | 0.4.3 | MIT |
| idna | 3.19 | BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 1.29.1 | MIT License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| playwright | 1.62.0 | Apache-2.0 |
| pluggy | 1.6.0 | MIT License |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pydantic_core | 2.46.5 | MIT |
| pyee | 13.0.1 | MIT License |
| pytest | 8.4.2 | MIT License |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| ruff | 0.16.6 | MIT |
| sse-starlette | 3.4.11 | BSD-3-Clause |
| starlette | 1.6.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.52.4 | BSD-3-Clause |

## Runtime, tooling, and model

- Python is provided by the `python:3.12-slim-bookworm` image and retains the [Python license](https://docs.python.org/3/license.html) and Debian package notices.
- Java runs in `eclipse-temurin:21-jre-jammy`; Temurin/OpenJDK licensing includes GPLv2 with the Classpath Exception and separate bundled notices. See [Adoptium's FAQ](https://adoptium.net/docs/faq). Maven 3.9.9 / Temurin 21 is used in the Java build stage.
- uv 0.11.23 is used in the Python build stage and CI; its source offers [MIT or Apache-2.0](https://github.com/astral-sh/uv). Docker Engine and Compose support a local setup without a paid service. Docker Desktop is optional and has [separate subscription terms](https://docs.docker.com/subscription-billing/desktop-license/).
- Browser HTML/CSS/JavaScript and icons are original project assets. No external font or frontend CDN is required. Playwright and its downloaded Chromium are test tools with their own upstream notices; browser binaries are not included in project source or runtime images.
- Ollama and Qwen3 model weights are installed separately. Ollama is MIT; Qwen3-8B is Apache-2.0 under its upstream model license. See [model setup](../docs/model-setup.md). The repository contains synthetic application data and actual screenshots of that data, not client data.
