# Local model setup

The application stack and inference are installed separately. The default model is **Ollama `qwen3:8b`**, an 8-billion-parameter Qwen3 model with tool calling. Ollama lists its Q4_K_M download at approximately **5.2 GB**. The adapter checks that the selected downloaded model advertises `tools`; it rejects cloud models and remote forwarding. See the [model listing](https://ollama.com/library/qwen3:8b) and [Ollama tool-calling protocol](https://docs.ollama.com/capabilities/tool-calling).

## Install, download, and warm

Install [Ollama](https://ollama.com/download) for your host. This project was exercised with Ollama **0.22.0** and `qwen3:8b` on an **Apple M4 Max with 36 GiB unified memory**. Exact live results and the verification environment are recorded in [verification.md](verification.md); a successful run is not a guarantee that every model response will pass validation.

The tested local model manifest digest was `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` (5,225,388,164 bytes, Q4_K_M). Model tags can change; compare the digest returned by Ollama's local `/api/tags` endpoint when reproducing the recorded evaluation.

For Compose, its investigator container needs to reach the host Ollama server. Start Ollama with cloud features disabled and a host-reachable listener:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

If the Ollama desktop app or a system service already owns port 11434, stop that instance first or configure its environment instead of starting a second server. A listener on all interfaces also accepts connections from other reachable machines: keep port 11434 restricted to your host and Docker network. Ollama's [FAQ](https://docs.ollama.com/faq) documents environment configuration on macOS and Linux, host binding, and disabling cloud features.

In another terminal, download and warm the model:

```sh
ollama pull qwen3:8b
ollama show qwen3:8b
curl --fail http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"Reply ready."}],"think":false,"stream":false,"keep_alive":"10m"}'
```

The `show` output should include the tools capability. The warm-up is a readiness check, not an incident evaluation. Initial model loading can take longer than warm inference. Downloads require internet access; subsequent inference uses the downloaded weights locally, with no account or API key.

In this project's `.env`, retain:

```dotenv
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3:8b
INVESTIGATION_TIMEOUT_SECONDS=240
```

Run `make up`, then check the console's model status. Docker Compose adds the host gateway mapping for Linux. If using `make native`, the launcher translates the default Docker host alias to `http://127.0.0.1:11434`; use a loopback-only Ollama listener for that host-only mode:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

## Capacity and timing

Plan for about 5.2 GB for model weights plus several GB for container images, Maven/Python caches, and build outputs. A practical starting budget is **15–20 GB free disk and 24 GB system RAM**, with more memory useful when Docker and inference compete. These are planning estimates, not measured minimum requirements. Assigning Docker about 4 GB leaves room for its two Java services and Python processes; CPU-only hosts can be substantially slower.

The adapter requests a 16,384-token context, disables Qwen3 thinking output, uses temperature zero, and requests at most 2,000 output tokens per turn. Each model request has a 60-second deadline; the complete investigation defaults to 240 seconds, eight model turns, and 12 tool calls. A warm run may fit the demo's roughly 40–60-second investigation slot; slower hardware or validation retries can exceed it. The UI reports timeouts or incomplete investigations explicitly. It never silently substitutes a mock model.

To use another downloaded local model, change `OLLAMA_MODEL` and recreate the investigator (`docker compose up -d investigator`). It must support Ollama tool calling and work within these budgets. Re-run the separate live evaluation on healthy, incident, and missing-data windows before advertising it as tested. The five telemetry tools are discovered over MCP and provided to Ollama in its function-tool schema. A separate local `submit_assessment` function validates the final diagnosis without performing I/O or granting an additional MCP permission; the final model turn is reserved for synthesis.

## Model license

Qwen3-8B is supplied under its own upstream **Apache License 2.0**; see [Qwen's model license](https://huggingface.co/Qwen/Qwen3-8B/blob/main/LICENSE). Model weights are downloaded separately and are not included in this source repository or its application images. Preserve the model's upstream license and notices if you redistribute weights. Ollama's implementation is separately [MIT licensed](https://github.com/ollama/ollama/blob/main/LICENSE). Neither license changes the license of this project's dependencies or runtime images; see [dependencies.md](dependencies.md).
