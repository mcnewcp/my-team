#!/usr/bin/env python3
"""PROTOTYPE — trip an absolute occupancy count and interrupt both Harnesses."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
from datetime import datetime
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
from environment_probe import CodexAppServer, Trace, claude_auth_status, selected_codex_config
from occupancy import (
    COMPACTION_DROP_FRACTION,
    COMPACTION_DROP_TOKENS,
    FILES,
    FORBIDDEN_ENV,
    LOCAL,
    REPO,
    ROOT,
    TRACES,
    claude_request_input,
    codex_usage_observation,
    command_output,
    config_fingerprints,
    cycle_prompt,
    is_compaction_drop,
    now,
    positive_int,
    reject_codex_tools,
    require_keyless_environment,
    sha256,
)

SUMMARY = LOCAL / "interruption-summary.json"
INTERRUPT_PROMPT = """You are the interrupt target in a read-only Harness mechanics test. Do not
use tools, read files, run commands, access the network, or change any state. Begin writing a
numbered list of short observations about why current context occupancy differs from cumulative
billing usage. Continue adding distinct observations until the Harness interrupts you.
"""
CLAUDE_INTERRUPTED_REASONS = {"aborted_streaming", "aborted_tools"}


def direct_crossing(
    observations: list[dict[str, Any]], field: str, target: int
) -> dict[str, Any] | None:
    for observation in observations:
        value = observation.get(field)
        if isinstance(value, int) and value >= target:
            return {
                "at": observation["at"],
                "cycle": observation["cycle"],
                "value": value,
                "overshoot_tokens": value - target,
            }
    return None


def observed_turn_id(message: dict[str, Any]) -> str | None:
    params: dict[str, Any] = message.get("params") or {}
    return params.get("turnId") or (params.get("turn") or {}).get("id")


async def wait_for_codex_terminal(client: CodexAppServer, *, turn_id: str) -> dict[str, Any]:
    while True:
        if client.notifications:
            message = client.notifications.pop(0)
        else:
            message = await client.receive()
        if message.get("method") == "turn/completed" and observed_turn_id(message) == turn_id:
            params: dict[str, Any] = message.get("params") or {}
            return params
        if "method" in message and "id" not in message:
            continue
        raise RuntimeError(f"unexpected Codex app-server message: {message}")


async def receive_completed_codex_turn(
    client: CodexAppServer,
    *,
    turn_id: str,
    cycle: int,
    cumulative_last_total: int,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    while True:
        message = await client.receive()
        method = message.get("method")
        params: dict[str, Any] = message.get("params") or {}
        if method == "thread/tokenUsage/updated" and observed_turn_id(message) == turn_id:
            observation, cumulative_last_total = codex_usage_observation(
                params,
                cycle=cycle,
                cumulative_last_total=cumulative_last_total,
            )
            observations.append(observation)
        elif method == "turn/completed" and observed_turn_id(message) == turn_id:
            return observations, cumulative_last_total, params
        elif "method" in message and "id" not in message:
            continue
        else:
            raise RuntimeError(f"unexpected Codex app-server message: {message}")


async def run_codex(stamp: str, workspace: Path, *, target: int, max_cycles: int) -> dict[str, Any]:
    trace = Trace(TRACES / f"{stamp}-codex-interruption.jsonl")
    observations: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    cumulative_last_total = 0
    previous_direct: int | None = None
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
                    "cwd": str(workspace),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "baseInstructions": "",
                    "developerInstructions": "",
                },
            )
            if thread_result.get("instructionSources"):
                raise RuntimeError(
                    "Codex interruption thread unexpectedly loaded instruction sources: "
                    f"{thread_result['instructionSources']}"
                )
            thread_id: str = thread_result["thread"]["id"]

            for cycle in range(1, max_cycles + 1):
                turn_result = await client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": cycle_prompt(cycle)}],
                    },
                )
                turn_id: str = turn_result["turn"]["id"]
                updates, cumulative_last_total, completed = await receive_completed_codex_turn(
                    client,
                    turn_id=turn_id,
                    cycle=cycle,
                    cumulative_last_total=cumulative_last_total,
                )
                reject_codex_tools(completed)
                terminal_status = (completed.get("turn") or {}).get("status")
                if terminal_status != "completed":
                    raise RuntimeError(f"Codex warm-up cycle {cycle} did not complete: {completed}")
                if not updates:
                    raise RuntimeError(
                        f"Codex warm-up cycle {cycle} emitted no token-usage observation"
                    )
                for observation in updates:
                    direct = observation["last_total_tokens"]
                    if is_compaction_drop(previous_direct, direct):
                        compactions.append(
                            {
                                "at": observation["at"],
                                "cycle": cycle,
                                "before": previous_direct,
                                "after": direct,
                            }
                        )
                    previous_direct = direct
                    observations.append(observation)
                latest = observations[-1]
                print(
                    f"Codex cycle {cycle}: occupancy={latest['last_total_tokens']}",
                    flush=True,
                )
                if latest["last_total_tokens"] >= target or compactions:
                    break

            crossing = direct_crossing(observations, "last_total_tokens", target)
            interrupt: dict[str, Any] | None = None
            if crossing is not None and not compactions:
                turn_result = await client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": INTERRUPT_PROMPT}],
                    },
                )
                turn = turn_result["turn"]
                turn_id = turn["id"]
                started_at = now()
                requested_at = now()
                acknowledgement = await client.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": turn_id},
                )
                acknowledged_at = now()
                completed = await wait_for_codex_terminal(client, turn_id=turn_id)
                terminal_at = now()
                reject_codex_tools(completed)
                completed_turn = completed.get("turn") or {}
                interrupt = {
                    "turn_id": turn_id,
                    "start_response_status": turn.get("status"),
                    "started_at": started_at,
                    "requested_at": requested_at,
                    "acknowledged_at": acknowledged_at,
                    "acknowledgement": acknowledgement,
                    "terminal_at": terminal_at,
                    "terminal_event": "turn/completed",
                    "terminal_status": completed_turn.get("status"),
                    "terminal_item_types": [
                        item.get("type") for item in (completed_turn.get("items") or [])
                    ],
                }

            trace_path = trace.path
            return {
                "versions": {"cli": command_output("codex", "--version")},
                "auth": {
                    "type": account_value.get("type"),
                    "plan_type": account_value.get("planType"),
                },
                "effective": {
                    "model": thread_result.get("model"),
                    "model_provider": thread_result.get("modelProvider"),
                    "reasoning_effort": thread_result.get("reasoningEffort"),
                    "context_window": observations[-1].get("model_context_window"),
                    "approval_policy": thread_result.get("approvalPolicy"),
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "instruction_sources": thread_result.get("instructionSources") or [],
                },
                "config": selected_codex_config(config),
                "observations": observations,
                "threshold_crossing": crossing,
                "compactions": compactions,
                "compaction_before_target": bool(compactions and crossing is None),
                "interrupt": interrupt,
                "trace": str(trace_path.relative_to(ROOT)),
            }
    finally:
        trace.close()


def claude_options(workspace: Path) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
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
        cwd=workspace,
        setting_sources=[],
        max_turns=3,
        env=os.environ.copy(),
    )


async def drain_claude_response(
    client: ClaudeSDKClient, trace: Trace, *, source: str
) -> tuple[ResultMessage, list[str], str | None, str | None]:
    result: ResultMessage | None = None
    message_types: list[str] = []
    init_model: str | None = None
    assistant_model: str | None = None
    async for message in client.receive_response():
        trace.write(source, message)
        message_types.append(type(message).__name__)
        if isinstance(message, SystemMessage) and message.subtype == "init":
            init_model = message.data.get("model")
        elif isinstance(message, AssistantMessage):
            assistant_model = message.model
        elif isinstance(message, ResultMessage):
            result = message
    if result is None:
        raise RuntimeError("Claude response ended without a ResultMessage")
    return result, message_types, init_model, assistant_model


async def run_claude(
    stamp: str, workspace: Path, *, target: int, max_cycles: int
) -> dict[str, Any]:
    auth = claude_auth_status()
    trace = Trace(TRACES / f"{stamp}-claude-interruption.jsonl")
    observations: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    cumulative_billed_input = 0
    previous_direct: int | None = None
    init_model: str | None = None
    assistant_model: str | None = None
    session_id: str | None = None
    try:
        async with ClaudeSDKClient(options=claude_options(workspace)) as client:
            for cycle in range(1, max_cycles + 1):
                prompt = cycle_prompt(cycle)
                trace.write("client.query", {"cycle": cycle, "prompt": prompt})
                await client.query(prompt)
                result, _, cycle_init_model, cycle_assistant_model = await drain_claude_response(
                    client,
                    trace,
                    source="server.receive",
                )
                init_model = cycle_init_model or init_model
                assistant_model = cycle_assistant_model or assistant_model
                session_id = result.session_id
                if result.is_error:
                    raise RuntimeError(
                        f"Claude warm-up cycle {cycle} failed: {result.errors or result.result}"
                    )
                if result.permission_denials:
                    raise RuntimeError(
                        f"Claude warm-up cycle {cycle} attempted denied tools: "
                        f"{result.permission_denials}"
                    )
                result_usage = result.usage or {}
                iterations = result_usage.get("iterations")
                if not isinstance(iterations, list) or not iterations:
                    raise RuntimeError(
                        f"Claude warm-up cycle {cycle} ResultMessage had no iteration usage"
                    )
                request_inputs = [claude_request_input(dict(usage)) for usage in iterations]
                cumulative_billed_input += sum(request_inputs)
                context_usage = await client.get_context_usage()
                trace.write("client.get_context_usage", {"cycle": cycle, **context_usage})
                observation = {
                    "at": now(),
                    "cycle": cycle,
                    "context_total_tokens": int(context_usage["totalTokens"]),
                    "request_input_tokens": request_inputs,
                    "cumulative_billed_input_tokens": cumulative_billed_input,
                    "model": context_usage.get("model"),
                    "max_tokens": context_usage.get("maxTokens"),
                    "raw_max_tokens": context_usage.get("rawMaxTokens"),
                    "auto_compact_enabled": context_usage.get("isAutoCompactEnabled"),
                    "auto_compact_threshold": context_usage.get("autoCompactThreshold"),
                }
                direct = observation["context_total_tokens"]
                if is_compaction_drop(previous_direct, direct):
                    compactions.append(
                        {
                            "at": observation["at"],
                            "cycle": cycle,
                            "before": previous_direct,
                            "after": direct,
                        }
                    )
                previous_direct = direct
                observations.append(observation)
                print(f"Claude cycle {cycle}: occupancy={direct}", flush=True)
                if direct >= target or compactions:
                    break

            crossing = direct_crossing(observations, "context_total_tokens", target)
            interrupt: dict[str, Any] | None = None
            if crossing is not None and not compactions:
                trace.write("client.query.interrupt_target", {"prompt": INTERRUPT_PROMPT})
                await client.query(INTERRUPT_PROMPT)
                started_at = now()
                interrupt_usage = await client.get_context_usage()
                observed_at = now()
                trace.write("client.get_context_usage.interrupt_check", interrupt_usage)
                requested_at = now()
                trace.write("client.interrupt.requested", {"at": requested_at})
                await client.interrupt()
                acknowledged_at = now()
                trace.write("client.interrupt.acknowledged", {"at": acknowledged_at})
                result, message_types, _, interrupted_assistant_model = await drain_claude_response(
                    client,
                    trace,
                    source="server.receive.interrupted",
                )
                assistant_model = interrupted_assistant_model or assistant_model
                terminal_at = now()
                interrupt = {
                    "session_id": result.session_id,
                    "same_session_as_warmup": result.session_id == session_id,
                    "started_at": started_at,
                    "occupancy_observed_at": observed_at,
                    "occupancy_tokens": int(interrupt_usage["totalTokens"]),
                    "occupancy_exceeded_target": int(interrupt_usage["totalTokens"]) >= target,
                    "requested_at": requested_at,
                    "acknowledged_at": acknowledged_at,
                    "terminal_at": terminal_at,
                    "terminal_event": "ResultMessage",
                    "terminal_reason": result.terminal_reason,
                    "terminal_subtype": result.subtype,
                    "terminal_is_error": result.is_error,
                    "permission_denials": result.permission_denials or [],
                    "drained_message_types": message_types,
                    "drained_result_count": message_types.count("ResultMessage"),
                    "receive_response_stopped_after_terminal": True,
                }

            trace_path = trace.path
            latest = observations[-1]
            return {
                "versions": {
                    "sdk": importlib.metadata.version("claude-agent-sdk"),
                    "bundled_cli": CLAUDE_BUNDLED_CLI_VERSION,
                    "standalone_cli": command_output("claude", "--version"),
                },
                "auth": auth,
                "effective": {
                    "model": latest.get("model") or init_model or assistant_model,
                    "init_model": init_model,
                    "assistant_model": assistant_model,
                    "context_window": latest.get("max_tokens"),
                    "raw_context_window": latest.get("raw_max_tokens"),
                    "auto_compact_enabled": latest.get("auto_compact_enabled"),
                    "auto_compact_threshold": latest.get("auto_compact_threshold"),
                    "tools": [],
                    "setting_sources": [],
                },
                "observations": observations,
                "threshold_crossing": crossing,
                "compactions": compactions,
                "compaction_before_target": bool(compactions and crossing is None),
                "interrupt": interrupt,
                "trace": str(trace_path.relative_to(ROOT)),
            }
    finally:
        trace.close()


def harness_passed(name: str, evidence: dict[str, Any]) -> bool:
    interrupt = evidence.get("interrupt") or {}
    if evidence.get("threshold_crossing") is None or evidence.get("compaction_before_target"):
        return False
    if name == "codex":
        return (
            interrupt.get("start_response_status") == "inProgress"
            and interrupt.get("acknowledgement") == {}
            and interrupt.get("terminal_event") == "turn/completed"
            and interrupt.get("terminal_status") == "interrupted"
        )
    return (
        interrupt.get("occupancy_exceeded_target") is True
        and interrupt.get("terminal_event") == "ResultMessage"
        and interrupt.get("terminal_reason") in CLAUDE_INTERRUPTED_REASONS
        and interrupt.get("drained_result_count") == 1
        and not interrupt.get("permission_denials")
    )


def outcome(summary: dict[str, Any], selected: str) -> str:
    names = ("codex", "claude") if selected == "both" else (selected,)
    if not all(name in summary for name in names):
        return "partial"
    return "pass" if all(harness_passed(name, summary[name]) for name in names) else "fail"


async def run(selected: str, *, target: int, max_cycles: int) -> int:
    require_keyless_environment()
    before = config_fingerprints()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    summary: dict[str, Any] = {
        "captured_at": now(),
        "prototype_commit_before_run": command_output("git", "rev-parse", "HEAD"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "target_tokens": target,
        "max_cycles": max_cycles,
        "workload": {
            "files": list(FILES),
            "embedded_bytes_per_cycle": sum((REPO / path).stat().st_size for path in FILES),
            "tools": "disabled",
        },
        "trigger_policy": {
            "codex": "last completed-turn last.totalTokens, then interrupt the next turn",
            "claude": (
                "live get_context_usage().totalTokens after the interrupt-target query starts"
            ),
        },
        "api_key_environment": {name: "absent" for name in FORBIDDEN_ENV},
        "compaction_drop_rule": {
            "minimum_fraction": COMPACTION_DROP_FRACTION,
            "minimum_tokens": COMPACTION_DROP_TOKENS,
        },
    }
    LOCAL.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="context-chaining-interruption-") as directory:
            workspace = Path(directory)
            if selected in ("both", "codex"):
                summary["codex"] = await run_codex(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                )
                SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n")
            if selected in ("both", "claude"):
                summary["claude"] = await run_claude(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                )
    except Exception as error:
        summary["error"] = str(error)
        SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(f"interruption run stopped: {error}", file=sys.stderr)
        print(f"partial observations: {SUMMARY.relative_to(ROOT)}", file=sys.stderr)
        return 1
    after = config_fingerprints()
    if before != after:
        raise RuntimeError("a watched persistent Harness configuration file changed during run")
    summary["persistent_config_changed"] = False
    for name in ("codex", "claude"):
        harness = summary.get(name)
        if harness:
            harness["trace_sha256"] = sha256(ROOT / harness["trace"])
    summary["outcome"] = outcome(summary, selected)
    SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"outcome: {summary['outcome']}")
    print(f"observations: {SUMMARY.relative_to(ROOT)}")
    return 0 if summary["outcome"] in ("pass", "partial") else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("both", "codex", "claude"), default="both")
    parser.add_argument("--target", type=positive_int, default=200_000)
    parser.add_argument("--max-cycles", type=positive_int, default=40)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.only, target=args.target, max_cycles=args.max_cycles)))


if __name__ == "__main__":
    main()
