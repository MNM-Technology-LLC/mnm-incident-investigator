# Troubleshooting

Start with the exact UI state and the measured observation window. The dashboard ends its normal window three seconds behind the current time so recently completed telemetry can arrive. A Java liveness check can pass while orders requests fail.

| Symptom | Check and action |
| --- | --- |
| `make up` cannot find Docker/Compose | Install Docker Engine and the Compose v2 plugin, and start the engine. `docker compose version` and `docker info` should work. Host Python 3 and `make` are also required. |
| First build is slow or cannot resolve dependencies | Initial image, Maven, Python, and model downloads require network access and disk space. Retry after restoring connectivity; caches are reused. `make logs` shows service startup progress. |
| Console port is occupied | Change `CONSOLE_PORT` in `.env`, then run `make up` and open that port. Native mode uses fixed ports 4318, 8001, 8082, 8081, 8000, and 8080; stop their existing demo processes before starting it. |
| Local model unavailable | Run `ollama show qwen3:8b`, warm the downloaded model, and inspect `curl http://127.0.0.1:8080/api/model`. Follow [model setup](model-setup.md) for host binding. The stack itself can be healthy without a model. |
| Ollama is reachable on host but not from Compose | Check `OLLAMA_HOST`, host firewall, `.env`'s `OLLAMA_BASE_URL`, and the host gateway route. Inside a container, `127.0.0.1` is that container. Restart the investigator after changing its configuration. |
| Model does not support tools | Use `qwen3:8b` or another downloaded model whose `ollama show` capabilities include tools. Cloud forwarding and cloud model tags are intentionally rejected. |
| Inference times out or returns an incomplete assessment | Warm the model; inspect memory pressure and Ollama logs. Each model request has a 60-second limit. Schema errors, unsupported citations, exhausted budgets, or missing correlated evidence also yield an incomplete assessment. Inspect the timeline and retrieved records before retrying. |
| Dashboard shows dashes / No data | Start traffic and allow at least 33 seconds. No records are not proof of health. Check the telemetry/MCP logs and service export warnings. |
| Inventory says healthy while orders fail | Health classifies completed request errors. Inventory can finish successfully after orders has timed out. Compare inventory latency with the correlated orders client span and its recorded timeout. |
| Fault button fails | Inventory may be unavailable or have a mismatched control token. Run `make setup`, then `make up` to align generated settings. The UI reports unknown state when the control request cannot be acknowledged. |
| Reset shows insufficient comparison | Keep traffic running across both windows. Each service needs at least 10 requests per 30-second window and comparable volumes. Traffic ends after 360 seconds; restart it, collect a fresh pre-reset window, and reset again after the prior comparison finishes. |
| Errors remain immediately after reset | In-flight slow requests and the trailing dashboard window can still contain errors. Wait for the separately measured recovery window, about 36 seconds, and inspect its results. |
| Evidence link returns 404 | Confirm MCP is available. `make reset` deletes snapshots; an investigator restart also loses in-memory jobs. Use a new investigation after a destructive reset. |
| Native startup rejects Java | Set `JAVA_HOME` to Java 21 and install Maven 3.9, or set `MAVEN_BIN` to its executable. Check `java -version`. Native process logs are in `.runtime/`. |
| Browser control POST returns 403 | Use the built-in same-origin UI. Scripted operator requests must send `X-Demo-Control: 1`; an Origin header, if supplied, must match the host. Agent endpoints do not accept demo controls. |

## Useful diagnostics

These commands inspect the Compose stack without exposing `.env` tokens:

```sh
docker compose ps
docker compose logs --tail 100 orders-service inventory-service telemetry mcp investigator
curl --fail http://127.0.0.1:8080/api/dashboard
curl --fail http://127.0.0.1:8080/api/model
```

If the receiver was unavailable, failed exports are not replayed. Restore it, keep traffic running, and collect a fresh window. Never treat the gap as zero failures. Telemetry is retained for 24 hours and at most 100,000 events; evidence snapshots persist until the evidence volume is deleted.

For a clean Compose demonstration, `make reset` removes only this project's telemetry/evidence volumes and restarts the stack with the fault disabled. It preserves downloaded models. `make down` stops containers without deleting evidence.

For native mode, Ctrl-C in the launching terminal stops all child processes. Its `.runtime` databases persist separately from Compose volumes. After stopping the native launcher, remove only `.runtime/telemetry.db` and `.runtime/evidence.db` if you intentionally want to discard its stored measurements; restart with `make native`.

When reporting a defect, include the command, UI error, versions, observation timestamps, and relevant redacted logs. Include the live evaluation report for model behavior. Do not attach `.env` or real application secrets.
