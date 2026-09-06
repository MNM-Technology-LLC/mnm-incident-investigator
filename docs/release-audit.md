# Release audit

The independent packaging audit verified the built Python wheel, browser assets,
read-only SQLite access, and the integrity of the retained deterministic smoke
report. These checks supplement the application, security, and model evaluations;
they do not replace a Docker runtime test or a live model evaluation.

## Checks actually performed

| Check | Observed result | Scope |
| --- | --- | --- |
| Build the Python wheel using cached build dependencies | Passed | `uv build --offline --wheel`; not an image build |
| Install that wheel into a separate temporary directory | Passed | Non-editable installation; imported module path verified outside the checkout |
| Run `tests/test_release.py` against source and installed wheel | 4 passed in each run | Actual HTTP static-asset responses, WAL reads, and retained artifact checks |
| Inspect wheel contents | Passed | `index.html`, `app.js`, `styles.css`, Apache `LICENSE`, and `NOTICE` present |
| Read a telemetry directory with files set to `0444` and directory to `0555` | Passed | Two committed samples visible, including a recent WAL-only commit; attempted SQL write rejected |
| Validate retained smoke evidence | Passed | All 14 SHA-256 evidence IDs matched their included snapshots; phase citations resolved within the report |
| Verify recorded recovery comparison | Passed | Equal eight-second windows and eight observed requests per service in each phase |
| Ruff on the added release tests | Passed | No lint findings |
| Docker Compose configuration validation | Passed | Compose v2 parsed the complete configuration with local environment interpolation |

The wheel tests used the already installed development dependencies. They establish
that the wheel contains and serves its own browser files; they are not a clean,
networked installation test. The permission test runs as a normal user and skips
when run as root, because root would not be constrained by those permission bits.

The retained [smoke report](evaluations/smoke.json) is a prior execution against the
real Java application. This audit revalidated that artifact without generating
traffic or changing the fault. It records healthy orders succeeding 8/8, faulted
orders timing out 8/8 with HTTP 504, and recovered orders succeeding 8/8. A correlated
fault trace contains an inventory duration of approximately 1,800 ms and the
orders client's observed 600 ms timeout setting. This supports the downstream-delay
mechanism. It does not reveal why inventory was delayed. The smoke report explicitly
sets `model_used` to `false`.

## Boundaries reviewed

The investigator receives no application or fault-control credentials, has no
telemetry volume mounted, and shares no Compose network with the console,
application services, or telemetry writer. MCP exposes the five allowed telemetry
tools and reads a telemetry volume mounted read-only. A separate evidence volume
holds query snapshots. Its constrained investigation API proxy bridges the two
read networks without forwarding arbitrary paths or destinations.

SQLite reads use `mode=ro`, `query_only`, fixed query structure, parameter binding,
and bounded execution. The writer's keeper connection preserves WAL/SHM files for
read-only readers. The regression test deliberately leaves a commit in WAL; a
shortcut using SQLite's immutable-file mode would miss that record.

Fault and reset requests belong to the console and inventory control endpoint.
Controller tool permissions are enforced independently of the model. Redaction,
input schemas, fixed investigation windows, snapshot checksums, citation membership,
and basic evidence-sufficiency checks are implemented in code. Logs remain untrusted
text even after schema validation and redaction.

Recovery uses equally long 30-second browser windows, waits for in-flight requests
and export grace, and requires at least ten completed samples per service in both
windows with comparable request volume. The report says the comparison is
incomplete when telemetry or sufficient traffic is unavailable. Its eight-second
smoke windows are explicitly separate from the browser's 30-second comparison.

## Limits and remaining execution

- Docker Engine was unavailable on the development host. Image builds, actual
  read-only volume mounts, Compose network reachability, and Compose teardown have
  **not** been executed there. CI is configured to build/start the stack and run
  smoke verification; configuration validation alone does not establish a CI pass.
- The native application run lacks Compose's network and filesystem isolation.
  Review the Compose tests and run its real-stack smoke check before presenting
  isolation as validated on a target host.
- Snapshot hashes establish integrity and query provenance. They do not prove that
  every sentence in a model explanation follows logically from the cited records.
  Inspect the evidence and uncertainty before accepting a diagnosis.
- Telemetry contains completed observations. Instrumentation gaps, dropped exports,
  and window boundaries can hide requests or spans. No-data results must remain
  unknown; error-free samples only describe their observation window.
- Live model findings and durations belong in [verification](verification.md) and
  its retained evaluation artifacts. The four release tests do not run Ollama,
  assess model reasoning quality, or establish universal prompt-injection resistance.

The audit found missing license/notice propagation in the initial image recipes
and the recipes now explicitly copy them. Rebuilt Java JARs include LICENSE, NOTICE,
and the dependency review; the source-built wheel includes its license and notice.
An actual Docker build is still needed to verify final image contents.
