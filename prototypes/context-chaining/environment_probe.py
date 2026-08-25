#!/usr/bin/env python3
"""Record the keyless, effective environment for both prototype Harnesses."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)
from claude_agent_sdk._cli_version import __cli_version__ as CLAUDE_BUNDLED_CLI_VERSION

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
LOCAL = ROOT / "local"
TRACES = LOCAL / "traces"
EVIDENCE = ROOT / "evidence" / "environment.md"
SCHEMA_MANIFEST = LOCAL / "schema-manifest.json"
FORBIDDEN_ENV = ("CODEX_API_KEY", "ANTHROPIC_API_KEY")
SMOKE_PROMPT = """This is an inert environment probe. Do not use tools, read files, run commands,
or access the network. Reply with exactly: ENVIRONMENT_PROBE_OK"""
EXPECTED_REPLY = "ENVIRONMENT_PROBE_OK"


def now() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def require_keyless_environment() -> None:
    present = [name for name in FORBIDDEN_ENV if name in os.environ]
    if present:
        names = ", ".join(present)
        raise SystemExit(f"refusing to run with API-key environment variables present: {names}")


def command_output(*argv: str) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True, env=os.environ.copy())
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class Trace:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._stream = path.open("x", encoding="utf-8")

    def write(self, source: str, payload: Any) -> None:
        event = {"at": now(), "source": source, "payload": jsonable(payload)}
        self._stream.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


class CodexAppServer:
    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self.process: asyncio.subprocess.Process | None = None
        self.notifications: list[dict[str, Any]] = []
        self._request_id = 0
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> CodexAppServer:
        self.process = await asyncio.create_subprocess_exec(
            "codex",
            "app-server",
            "--stdio",
            cwd=REPO,
            env=os.environ.copy(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self.process is not None
        if self.process.stdin is not None:
            self.process.stdin.close()
            await self.process.stdin.wait_closed()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:
            self.process.terminate()
            await self.process.wait()
        if self._stderr_task is not None:
            await self._stderr_task

    async def _drain_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while line := await self.process.stderr.readline():
            self.trace.write("codex.stderr", line.decode(errors="replace").rstrip())

    async def send(self, message: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.trace.write("client.send", message)
        self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await self.process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=120)
        if not line:
            code = await self.process.wait()
            raise RuntimeError(f"Codex app-server closed stdout with exit code {code}")
        message: dict[str, Any] = json.loads(line)
        self.trace.write("server.receive", message)
        return message

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Codex {method} failed: {message['error']}")
                result: dict[str, Any] = message.get("result") or {}
                return result
            if "method" in message and "id" not in message:
                self.notifications.append(message)
                continue
            raise RuntimeError(f"unexpected Codex app-server message: {message}")

    async def wait_for_notification(self, method: str, *, turn_id: str) -> dict[str, Any]:
        while True:
            message = await self.receive()
            if message.get("method") == method:
                params: dict[str, Any] = message.get("params") or {}
                observed_turn = params.get("turnId") or (params.get("turn") or {}).get("id")
                if observed_turn == turn_id:
                    return params
            if "method" in message and "id" not in message:
                self.notifications.append(message)
                continue
            raise RuntimeError(f"unexpected Codex app-server message: {message}")


def selected_codex_config(config_result: dict[str, Any]) -> dict[str, Any]:
    config = config_result.get("config") or {}
    keys = (
        "model",
        "model_provider",
        "model_context_window",
        "model_auto_compact_token_limit",
        "model_auto_compact_token_limit_scope",
        "model_reasoning_effort",
    )
    selected = {key: config.get(key) for key in keys}
    selected["custom_compact_prompt"] = config.get("compact_prompt") is not None
    return selected


async def probe_codex(stamp: str, smoke_workspace: Path) -> dict[str, Any]:
    trace = Trace(TRACES / f"{stamp}-codex-environment.jsonl")
    try:
        async with CodexAppServer(trace) as client:
            await client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "my-team-context-chaining-prototype",
                        "version": "0.1",
                    },
                    "capabilities": {"experimentalApi": False},
                },
            )
            await client.send({"method": "initialized"})
            account = await client.request("account/read", {"refreshToken": False})
            account_value = account.get("account") or {}
            if account_value.get("type") != "chatgpt":
                raise RuntimeError(
                    "Codex is not using ChatGPT subscription authentication "
                    f"(account type: {account_value.get('type')!r})"
                )
            config = await client.request("config/read", {"cwd": str(REPO), "includeLayers": True})
            thread_result = await client.request(
                "thread/start",
                {
                    "cwd": str(smoke_workspace),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "baseInstructions": "",
                    "developerInstructions": "",
                },
            )
            thread_id: str = thread_result["thread"]["id"]
            turn_result = await client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": SMOKE_PROMPT}],
                },
            )
            turn_id: str = turn_result["turn"]["id"]
            completed = await client.wait_for_notification("turn/completed", turn_id=turn_id)
            usage_updates = [
                message["params"]
                for message in client.notifications
                if message.get("method") == "thread/tokenUsage/updated"
                and (message.get("params") or {}).get("turnId") == turn_id
            ]
            usage = usage_updates[-1]["tokenUsage"] if usage_updates else None
            items = (completed.get("turn") or {}).get("items") or []
            if len(items) != 1 or items[0].get("type") != "agentMessage":
                raise RuntimeError(f"Codex inert probe unexpectedly used an item: {items}")
            if items[0].get("text", "").strip() != EXPECTED_REPLY:
                raise RuntimeError(f"Codex inert probe returned an unexpected reply: {items}")
            instruction_sources = thread_result.get("instructionSources") or []
            if instruction_sources:
                raise RuntimeError(
                    "Codex inert probe unexpectedly loaded instruction sources: "
                    f"{instruction_sources}"
                )
            return {
                "cli_version": command_output("codex", "--version"),
                "auth": {
                    "type": account_value.get("type"),
                    "plan_type": account_value.get("planType"),
                    "requires_openai_auth": account.get("requiresOpenaiAuth"),
                },
                "effective": {
                    "model": thread_result.get("model"),
                    "model_provider": thread_result.get("modelProvider"),
                    "reasoning_effort": thread_result.get("reasoningEffort"),
                    "service_tier": thread_result.get("serviceTier"),
                    "approval_policy": thread_result.get("approvalPolicy"),
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "instruction_sources": instruction_sources,
                    "model_context_window": (usage or {}).get("modelContextWindow"),
                },
                "config": selected_codex_config(config),
                "terminal_status": (completed.get("turn") or {}).get("status"),
                "trace": str(trace.path.relative_to(ROOT)),
            }
    finally:
        trace.close()


def claude_auth_status() -> dict[str, Any]:
    status: dict[str, Any] = json.loads(command_output("claude", "auth", "status", "--json"))
    sanitized = {
        key: status.get(key) for key in ("loggedIn", "authMethod", "apiProvider", "apiKeySource")
    }
    if not sanitized["loggedIn"]:
        raise RuntimeError("Claude Code has no login when API-key variables are absent")
    if sanitized["apiProvider"] != "firstParty":
        raise RuntimeError(f"Claude Code is not using the first-party provider: {sanitized}")
    if sanitized["authMethod"] == "api_key" or sanitized["apiKeySource"] is not None:
        raise RuntimeError(f"Claude Code is not using subscription authentication: {sanitized}")
    return sanitized


async def probe_claude(stamp: str, smoke_workspace: Path) -> dict[str, Any]:
    auth = claude_auth_status()
    trace = Trace(TRACES / f"{stamp}-claude-environment.jsonl")
    options = ClaudeAgentOptions(
        tools=[],
        allowed_tools=[],
        disallowed_tools=[
            "Bash",
            "Read",
            "Glob",
            "Grep",
            "Write",
            "Edit",
            "NotebookEdit",
            "WebFetch",
            "WebSearch",
        ],
        permission_mode="dontAsk",
        cwd=smoke_workspace,
        setting_sources=[],
        max_turns=3,
        env=os.environ.copy(),
    )
    init_model: str | None = None
    assistant_model: str | None = None
    result: ResultMessage | None = None
    try:
        async with ClaudeSDKClient(options=options) as client:
            trace.write("client.query", {"prompt": SMOKE_PROMPT})
            await client.query(SMOKE_PROMPT)
            async for message in client.receive_response():
                trace.write("server.receive", message)
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    init_model = message.data.get("model")
                elif isinstance(message, AssistantMessage):
                    assistant_model = message.model
                elif isinstance(message, ResultMessage):
                    result = message
            context_usage = await client.get_context_usage()
            trace.write("client.get_context_usage", context_usage)
    finally:
        trace.close()
    if result is None:
        raise RuntimeError("Claude SDK stream ended without a ResultMessage")
    if result.is_error:
        raise RuntimeError(f"Claude SDK smoke query failed: {result.errors or result.result}")
    if (result.result or "").strip() != EXPECTED_REPLY:
        raise RuntimeError(
            f"Claude SDK inert probe returned an unexpected reply: {result.result!r}"
        )
    if result.permission_denials:
        raise RuntimeError(
            f"Claude SDK inert probe attempted denied tools: {result.permission_denials}"
        )
    return {
        "sdk_version": importlib.metadata.version("claude-agent-sdk"),
        "bundled_cli_version": CLAUDE_BUNDLED_CLI_VERSION,
        "standalone_cli_version": command_output("claude", "--version"),
        "auth": auth,
        "effective": {
            "model": context_usage.get("model") or init_model or assistant_model,
            "init_model": init_model,
            "assistant_model": assistant_model,
            "context_tokens": context_usage.get("totalTokens"),
            "max_tokens": context_usage.get("maxTokens"),
            "raw_max_tokens": context_usage.get("rawMaxTokens"),
            "auto_compact_enabled": context_usage.get("isAutoCompactEnabled"),
            "auto_compact_threshold": context_usage.get("autoCompactThreshold"),
        },
        "terminal": {
            "subtype": result.subtype,
            "terminal_reason": result.terminal_reason,
            "is_error": result.is_error,
        },
        "trace": str(trace.path.relative_to(ROOT)),
    }


def config_fingerprints() -> dict[str, str | None]:
    candidates = (
        Path.home() / ".codex" / "config.toml",
        Path.home() / ".claude" / "settings.json",
        REPO / ".codex" / "config.toml",
        REPO / ".claude" / "settings.json",
        REPO / ".claude" / "settings.local.json",
    )
    return {str(path): sha256(path) if path.is_file() else None for path in candidates}


def load_schema_manifest() -> dict[str, Any]:
    if not SCHEMA_MANIFEST.is_file():
        raise SystemExit("local/schema-manifest.json is missing; run ./run-safe prepare.py first")
    manifest: dict[str, Any] = json.loads(SCHEMA_MANIFEST.read_text())
    return manifest


def markdown(report: dict[str, Any]) -> str:
    codex = report["codex"]
    claude = report["claude"]
    bundles = report["schemas"]["bundles"]
    codex_auth = codex["auth"]
    claude_auth = claude["auth"]

    def literal(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"))

    codex_versions = (
        f"`{codex['cli_version']}`; stable v2 `{bundles['stable_v2']['sha256']}`; "
        f"experimental v2 `{bundles['experimental_v2']['sha256']}`"
    )
    codex_auth_text = f"account type `{codex_auth['type']}`, plan `{codex_auth['plan_type']}`"
    codex_model = f"`{codex['effective']['model']}` ({codex['effective']['model_provider']})"
    codex_compaction = (
        "configured limit "
        f"`{literal(codex['config']['model_auto_compact_token_limit'])}`, "
        f"scope `{literal(codex['config']['model_auto_compact_token_limit_scope'])}`"
    )
    codex_row = " | ".join(
        (
            "Codex",
            codex_versions,
            codex_auth_text,
            codex_model,
            f"`{codex['effective']['model_context_window']}`",
            codex_compaction,
        )
    )
    claude_versions = (
        f"SDK `{claude['sdk_version']}`; bundled CLI `{claude['bundled_cli_version']}`; "
        f"standalone `{claude['standalone_cli_version']}`"
    )
    claude_auth_text = (
        f"`{claude_auth['authMethod']}` via `{claude_auth['apiProvider']}`; "
        f"API-key source `{literal(claude_auth['apiKeySource'])}`"
    )
    claude_window = (
        f"effective `{claude['effective']['max_tokens']}`, "
        f"raw `{claude['effective']['raw_max_tokens']}`"
    )
    claude_compaction = (
        f"enabled `{literal(claude['effective']['auto_compact_enabled'])}`, "
        f"threshold `{literal(claude['effective']['auto_compact_threshold'])}`"
    )
    claude_row = " | ".join(
        (
            "Claude Code",
            claude_versions,
            claude_auth_text,
            f"`{claude['effective']['model']}`",
            claude_window,
            claude_compaction,
        )
    )
    table_header = " | ".join(
        (
            "Harness",
            "Versions and generated protocol",
            "Subscription auth",
            "Effective model",
            "Context window",
            "Automatic compaction",
        )
    )
    return f"""# Dual-Harness environment

Sanitized setup evidence for
[Prepare an isolated dual-harness experiment](https://github.com/mcnewcp/my-team/issues/77).

## Reproduction identity

- Captured at: `{report["captured_at"]}`
- Prototype commit: `{report["prototype_commit"]}`
- Host platform: `{report["platform"]}`
- Python: `{report["python"]}`
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`
- Persistent Harness configuration changed: **no** (all watched settings fingerprints were
  unchanged; the Codex thread was ephemeral and both permission envelopes were read-only)

## Harnesses

| {table_header} |
| --- | --- | --- | --- | ---: | --- |
| {codex_row} |
| {claude_row} |

Codex effective thread settings were approval policy `{codex["effective"]["approval_policy"]}`,
sandbox `read-only`, and ephemeral persistence. Its configured model/context fields were
`{json.dumps(codex["config"], sort_keys=True)}`; `null` means the Harness default remained in
force. The Codex thread loaded no instruction sources. The Claude SDK used its bundled CLI with no
setting sources or tools available.

## Smoke observation

- Codex completed the inert no-tool query with terminal status
  `{codex["terminal_status"]}` and emitted a context-window observation.
- Claude Code completed the same inert no-tool query with result subtype
  `{claude["terminal"]["subtype"]}` and returned `get_context_usage()` after the turn.
- These observations prove setup and effective settings only. They do not resolve occupancy
  cadence, concurrent Claude queries, interruption, Handoff, fresh-session continuation, or real
  skill dispatch.

## Local-only artifacts

- Codex trace: `{codex["trace"]}` (`{report["trace_sha256"]["codex"]}`)
- Claude trace: `{claude["trace"]}` (`{report["trace_sha256"]["claude"]}`)
- Generated schemas: `local/schemas/`

The traces and generated schemas are intentionally ignored by git.
"""


async def run(selected: str) -> int:
    require_keyless_environment()
    schema_manifest = load_schema_manifest()
    before = config_fingerprints()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    partial: dict[str, Any] = {
        "captured_at": now(),
        "prototype_commit": command_output("git", "rev-parse", "HEAD"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "api_key_environment": {name: "absent" for name in FORBIDDEN_ENV},
        "schemas": schema_manifest,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="context-chaining-environment-") as directory:
            smoke_workspace = Path(directory)
            if selected in ("both", "codex"):
                partial["codex"] = await probe_codex(stamp, smoke_workspace)
            if selected in ("both", "claude"):
                partial["claude"] = await probe_claude(stamp, smoke_workspace)
    except Exception as error:
        partial["error"] = str(error)
        LOCAL.mkdir(exist_ok=True)
        partial_path = LOCAL / "environment-partial.json"
        partial_path.write_text(json.dumps(partial, indent=2, default=str) + "\n")
        print(f"probe stopped: {error}", file=sys.stderr)
        print(f"partial observations: {partial_path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    after = config_fingerprints()
    if before != after:
        raise RuntimeError("a watched persistent Harness configuration file changed during probe")
    partial["persistent_config_changed"] = False
    if selected != "both":
        partial_path = LOCAL / "environment-partial.json"
        partial_path.write_text(json.dumps(partial, indent=2, default=str) + "\n")
        print(json.dumps(partial, indent=2, default=str))
        print(f"partial observations: {partial_path.relative_to(ROOT)}")
        return 0
    partial["trace_sha256"] = {
        "codex": sha256(ROOT / partial["codex"]["trace"]),
        "claude": sha256(ROOT / partial["claude"]["trace"]),
    }
    EVIDENCE.write_text(markdown(partial))
    print(markdown(partial))
    print(f"wrote {EVIDENCE.relative_to(ROOT)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("both", "codex", "claude"), default="both")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.only)))


if __name__ == "__main__":
    main()
