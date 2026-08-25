#!/usr/bin/env python3
"""Prepare local generated artifacts for the context-chaining prototype."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
SCHEMAS = LOCAL / "schemas"
FORBIDDEN_ENV = ("CODEX_API_KEY", "ANTHROPIC_API_KEY")
V2_BUNDLE = "codex_app_server_protocol.v2.schemas.json"


def require_keyless_environment() -> None:
    present = [name for name in FORBIDDEN_ENV if name in os.environ]
    if present:
        names = ", ".join(present)
        raise SystemExit(f"refusing to run with API-key environment variables present: {names}")


def command_output(*argv: str) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def codex_version() -> str:
    output = command_output("codex", "--version")
    match = re.search(r"(\d+\.\d+\.\d+)", output)
    if match is None:
        raise SystemExit(f"could not parse Codex version from: {output!r}")
    return match.group(1)


def generate_schema(destination: Path, *, experimental: bool) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    argv = ["codex", "app-server", "generate-json-schema"]
    if experimental:
        argv.append("--experimental")
    argv.extend(("--out", str(destination)))
    subprocess.run(argv, check=True)
    bundle = destination / V2_BUNDLE
    if not bundle.is_file():
        raise SystemExit(f"Codex did not generate {bundle}")
    return bundle


def main() -> None:
    require_keyless_environment()
    version = codex_version()
    version_root = SCHEMAS / f"codex-{version}"
    stable = generate_schema(version_root / "stable", experimental=False)
    experimental = generate_schema(version_root / "experimental", experimental=True)
    manifest = {
        "captured_at": datetime.now(UTC).astimezone().isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "codex_cli": version,
        "bundles": {
            "stable_v2": {"path": str(stable.relative_to(ROOT)), "sha256": sha256(stable)},
            "experimental_v2": {
                "path": str(experimental.relative_to(ROOT)),
                "sha256": sha256(experimental),
            },
        },
        "api_key_environment": {name: "absent" for name in FORBIDDEN_ENV},
        "persistent_config_changed": False,
    }
    LOCAL.mkdir(exist_ok=True)
    manifest_path = LOCAL / "schema-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    print(f"wrote {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
