# Security boundaries

MNM Incident Investigator is a local showcase using synthetic requests. Keep its
console on the documented loopback address. It has no account system or production
access-control model. Do not expose the console or Ollama to the public internet.

## Investigator permissions

The model can request exactly five telemetry tools: `get_service_health`,
`get_service_map`, `query_metrics`, `search_logs`, and `get_trace`. Both the controller
and MCP client enforce this allowlist in code. The MCP server independently exposes
only these tools. Tool annotations describe permissions; they do not grant them.
There is no shell, arbitrary HTTP, file, SQL, ingestion, or fault-control tool.

Every argument must match a strict schema. Services and telemetry paths are fixed
enumerations; trace IDs must be hexadecimal. The controller fixes one UTC observation
window and rejects attempts to extend or replace it. Queries use parameterized SQL,
read-only SQLite connections, `PRAGMA query_only`, a two-second execution budget,
and row/byte caps. Each MCP operation has an eight-second deadline. Investigation
turns, calls, context size, model output, and total duration are bounded.

In Docker Compose, the investigator shares no network with either Java application
or the console. It receives neither application-control nor telemetry-ingestion
credentials and mounts neither database. Its model network permits access to the
operator's local Ollama installation. This is intentional model connectivity, not
an assertion that the container has no network egress.

The MCP process mounts telemetry read-only and keeps evidence in a separate writable
volume. It has no network shared with the telemetry receiver or applications. A
bridge exposes only fixed investigation/model API routes to the console; its paths,
upstream destination, methods, request/response budgets, and lack of forwarded caller
credentials are enforced in code. It cannot proxy application or control routes.

## Demo controls and telemetry

Fault injection and reset exist only in the operator console and inventory control
endpoint. Inventory authenticates control requests with a separately generated
credential. Application exporters use a different ingestion credential. Neither
credential is sent to Ollama or included in evidence.

Only the console is published, bound to `127.0.0.1`. The console validates Host
headers, rejects cross-origin writes, and requires an explicit header for demo
actions. These are browser protections for a local demo, not user authentication.
Console and investigation API write bodies are capped at 4 KiB while streaming,
before JSON/schema parsing. Browser responses set a restrictive content security
policy, prohibit framing, avoid caching, and disable content-type sniffing.

The telemetry receiver authenticates writes and accepts only a bounded application
event schema. Arbitrary attributes, control endpoints, injector state, and scenario
answers are not part of that schema. Control messages are not exported by Java
instrumentation; an additional receiver check rejects recognizable control text.
Logs retain trace IDs and observable outcomes, including downstream timeout details.
Those observations establish a failure mechanism, not the hidden reason inventory
became slow.

Known credential forms are redacted before persistence and again when text crosses
the model boundary. Coverage includes quoted JSON keys and escaped values, common
password/token/API-key fields, Bearer/Basic authorization, common provider key
patterns, and HTTP URL credentials. Rejected ingestion payloads are not echoed in
validation errors. Pattern redaction is defense in depth; it is not guaranteed to
recognize arbitrary or encoded secrets. This project uses synthetic application
data and should not receive real credentials in log messages.

## Untrusted evidence and citations

Log text and tool output remain untrusted data, even if they contain `SYSTEM`, tool
requests, URLs, or instructions. The controller places telemetry in an explicitly
untrusted tool-result envelope. Model output never changes permissions. Adversarial
tests script a model that follows injected instructions and verify that control and
shell calls still never reach a transport.

Evidence snapshots include the executed query, data, availability, and limitations.
Their IDs are SHA-256 content hashes generated after redaction. The MCP client checks
the snapshot schema, checksum, tool, and requested filters/window; evidence HTTP
retrieval checks the requested ID as well. Stored snapshots are checksum-verified
on retrieval and survive telemetry retention until a clean reset. A diagnosis may
cite only evidence retrieved in its investigation. Deterministic sufficiency checks
reject false healthy/incident claims and incident conclusions lacking correlated
error logs and traces.

Hashes detect content changes and incorrect query provenance; they are not digital
signatures or independent proof that instrumentation is truthful. The receiver,
application instrumentation, MCP implementation, local host, and local operator
remain trusted. A compromised exporter with the ingestion credential can submit
false observations. An LLM can still write a misleading interpretation of valid
evidence; engineers should inspect citations and uncertainty. Tests do not establish
universal resistance to prompt injection or prove live model reasoning quality.

## Verification and reporting

`make check` runs deterministic permission, redaction, schema, stream-budget,
evidence-integrity, malicious-model, origin, and Compose-isolation assertions.
`make smoke` exercises actual application behavior separately. Live Ollama evaluation
is explicitly separate from scripted tests; see the evaluation documentation.

For a suspected vulnerability, avoid posting credentials, private telemetry, or an
exploit against a deployed service in a public issue. Use the repository host's
private vulnerability-reporting feature when enabled; otherwise contact the
maintainer listed in repository metadata to arrange a private report. Include the
affected revision, boundary crossed, and a synthetic reproducer.
