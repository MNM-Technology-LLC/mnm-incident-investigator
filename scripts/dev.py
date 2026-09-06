#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the real stack on loopback without Docker; Ctrl-C stops every child process.

Use `make native` after installing Java 21, Maven, Python 3.12, and uv.
This convenience mode lacks Docker network and read-only volume isolation.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from setup_env import setup

ROOT = Path(__file__).resolve().parents[1]
PORTS = (4318, 8001, 8082, 8081, 8000, 8080)


def env_file(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result


def executable(name: str, configured: str | None = None) -> str:
    candidate = shutil.which(configured or name) or configured
    if not candidate or not Path(candidate).is_file():
        raise RuntimeError(f"Cannot find {name}; install it or configure its executable path")
    return candidate


def ensure_free_ports() -> None:
    for port in PORTS:
        with socket.socket() as probe:
            # Recently closed HTTP connections can remain in TIME_WAIT. Match
            # the servers' reuse behavior while still rejecting a live listener.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(f"Port {port} is in use. Stop the existing demo before starting native mode.") from error


def wait_ready(process: subprocess.Popen, url: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"A service exited during startup; inspect {ROOT / '.runtime'} for its log")
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Service did not become ready at {url}; inspect .runtime/*.log")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Use existing Java jars; Python environment must exist")
    args = parser.parse_args()
    children: list[tuple[str, subprocess.Popen]] = []
    logs = []

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        ensure_free_ports()
        settings = env_file(setup(ROOT))
        python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            raise RuntimeError("Project Python environment missing. Run uv sync --frozen first, or use make native.")
        java_home = os.getenv("JAVA_HOME")
        java = executable("java", str(Path(java_home) / "bin/java") if java_home else None)
        version = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10, check=True)
        if not re.search(r'version "21(?:\.|\")', version.stderr + version.stdout):
            raise RuntimeError("Java 21 is required. Set JAVA_HOME to a Java 21 installation.")
        if not args.skip_build:
            maven = executable("mvn", os.getenv("MAVEN_BIN"))
            subprocess.run([maven, "-B", "-ntp", "-f", "services/pom.xml", "package"], cwd=ROOT, check=True)
        state = ROOT / ".runtime"
        state.mkdir(exist_ok=True)
        # Child roles receive a small environment, never inherited demo credentials.
        inherited = {"PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT"}
        base = {key: value for key, value in os.environ.items() if key in inherited}
        base.update(BIND_HOST="127.0.0.1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        telemetry = {"TELEMETRY_DB": str(state / "telemetry.db")}
        ingest = {"TELEMETRY_ENDPOINT": "http://127.0.0.1:4318/v1/events",
                  "TELEMETRY_INGEST_TOKEN": settings["TELEMETRY_INGEST_TOKEN"]}
        controls = {"DEMO_CONTROL_TOKEN": settings["DEMO_CONTROL_TOKEN"]}
        # Compose's host alias is not needed when Python runs directly on the host.
        ollama_url = os.getenv("OLLAMA_BASE_URL", settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        if ollama_url == "http://host.docker.internal:11434":
            ollama_url = "http://127.0.0.1:11434"

        def java_command(service: str) -> list[str]:
            jar = ROOT / "services" / service / "target" / f"{service}-1.0.0.jar"
            if not jar.is_file():
                raise RuntimeError(f"Missing {jar}; run again without --skip-build")
            return [java, "-jar", str(jar), "--server.address=127.0.0.1"]

        specs = [
            ("telemetry", [str(python), "-m", "mnm_investigator.telemetry"],
             telemetry | {"TELEMETRY_INGEST_TOKEN": settings["TELEMETRY_INGEST_TOKEN"]}, 4318, "/health"),
            ("mcp", [str(python), "-m", "mnm_investigator.mcp_server"],
             telemetry | {"EVIDENCE_DB": str(state / "evidence.db"),
                          "INVESTIGATOR_UPSTREAM": "http://127.0.0.1:8000"}, 8001, "/health"),
            ("inventory", java_command("inventory-service"), ingest | controls, 8082, "/actuator/health"),
            ("orders", java_command("orders-service"),
             ingest | {"INVENTORY_URL": "http://127.0.0.1:8082"}, 8081, "/actuator/health"),
            ("investigator", [str(python), "-m", "mnm_investigator.api"],
             {"MCP_URL": "http://127.0.0.1:8001/mcp", "OLLAMA_BASE_URL": ollama_url,
              "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", settings.get("OLLAMA_MODEL", "qwen3:8b")),
              "INVESTIGATION_TIMEOUT_SECONDS": settings.get("INVESTIGATION_TIMEOUT_SECONDS", "240")}, 8000, "/health"),
            ("console", [str(python), "-m", "mnm_investigator.console"],
             controls | {"ORDERS_URL": "http://127.0.0.1:8081", "INVENTORY_URL": "http://127.0.0.1:8082",
                         "MCP_URL": "http://127.0.0.1:8001/mcp", "INVESTIGATOR_URL": "http://127.0.0.1:8001"},
             8080, "/health"),
        ]
        for name, command, extra, port, health in specs:
            log = (state / f"{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(command, cwd=ROOT, env=base | extra, stdout=log, stderr=subprocess.STDOUT)
            children.append((name, process))
            wait_ready(process, f"http://127.0.0.1:{port}{health}")
            print(f"{name} ready on 127.0.0.1:{port}", flush=True)
        print("Open http://127.0.0.1:8080 — Ctrl-C stops the stack. Native mode does not isolate process networks.",
              flush=True)
        while True:
            for name, child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited with code {child.returncode}; see .runtime/{name}.log")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping native stack…", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Native startup failed: {error}", file=sys.stderr)
        return 1
    finally:
        for _, child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
