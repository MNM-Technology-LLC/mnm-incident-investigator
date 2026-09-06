#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create project-only local tokens; preserve user settings and never print secrets."""
from __future__ import annotations

import argparse
from pathlib import Path
import secrets


def setup(root: Path) -> Path:
    destination = root / ".env"
    source = destination if destination.exists() else root / ".env.example"
    contents = source.read_text(encoding="utf-8")
    lines = contents.splitlines()
    for key in ("TELEMETRY_INGEST_TOKEN", "DEMO_CONTROL_TOKEN"):
        matched = False
        for index, line in enumerate(lines):
            if line.startswith(key + "="):
                matched = True
                if line.partition("=")[2].strip() in {"", "generate-me"}:
                    lines[index] = key + "=" + secrets.token_urlsafe(32)
        if not matched:
            lines.append(key + "=" + secrets.token_urlsafe(32))
    result = "\n".join(lines) + "\n"
    if destination.exists():
        destination.chmod(0o600)
        if contents != result:
            destination.write_text(result, encoding="utf-8")
    else:
        # Create with restricted permissions before writing any credentials.
        import os
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(result)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    path = setup(arguments.root.resolve())
    print(f"Local settings ready: {path} (credentials are not printed)")


if __name__ == "__main__":
    main()
