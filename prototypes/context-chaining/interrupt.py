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
    PermissionResultAllow,
    PermissionResultDeny,
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

INTERRUPTION_SUMMARY = LOCAL / "interruption-summary.json"
HANDOFF_SUMMARY = LOCAL / "handoff-summary.json"
HANDOFFS = LOCAL / "handoffs"
INTERRUPT_PROMPT = """You are the interrupt target in a read-only Harness mechanics test. Do not
use tools, read files, run commands, access the network, or change any state. Begin writing a
numbered list of short observations about why current context occupancy differs from cumulative
billing usage. Continue adding distinct observations until the Harness interrupts you.
"""
CLAUDE_INTERRUPTED_REASONS = {"aborted_streaming", "aborted_tools"}


def handoff_content(stamp: str, harness: str) -> str:
    return f"HANDOFF: same-session placeholder {stamp}-{harness}\n"


def handoff_prompt(path: Path, content: str) -> str:
    return f"Write exactly {json.dumps(content)} to {path}, then reply exactly HANDOFF_WRITTEN."


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


async def wait_for_codex_terminal(
    client: CodexAppServer,
    *,
    turn_id: str,
    cycle: int,
    cumulative_last_total: int,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    while True:
        if client.notifications:
            message = client.notifications.pop(0)
        else:
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
        if "method" in message and "id" not in message:
            continue
        raise RuntimeError(f"unexpected Codex app-server message: {message}")


async def receive_completed_codex_turn(
    client: CodexAppServer,
    *,
    turn_id: str,
    cycle: int,
    cumulative_last_total: int,
    completed_item_types: list[str] | None = None,
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
        elif method == "item/completed" and observed_turn_id(message) == turn_id:
            if completed_item_types is not None:
                item_type = (params.get("item") or {}).get("type")
                if isinstance(item_type, str):
                    completed_item_types.append(item_type)
        elif "method" in message and "id" not in message:
            continue
        else:
            raise RuntimeError(f"unexpected Codex app-server message: {message}")


async def run_codex(
    stamp: str,
    workspace: Path,
    *,
    target: int,
    max_cycles: int,
    include_handoff: bool,
    handoff_path: Path,
) -> dict[str, Any]:
    milestone = "handoff" if include_handoff else "interruption"
    trace = Trace(TRACES / f"{stamp}-codex-{milestone}.jsonl")
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
                    "capabilities": {"experimentalApi": include_handoff},
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
            interrupt_usage: list[dict[str, Any]] = []
            terminal_cleanup: dict[str, Any] | None = None
            handoff: dict[str, Any] | None = None
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
                interrupt_usage, cumulative_last_total, completed = await wait_for_codex_terminal(
                    client,
                    turn_id=turn_id,
                    cycle=len(observations) + 1,
                    cumulative_last_total=cumulative_last_total,
                )
                for observation in interrupt_usage:
                    observation["phase"] = "interrupt"
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
                    "usage_observations": interrupt_usage,
                }

                if include_handoff and completed_turn.get("status") == "interrupted":
                    cleanup_started_at = now()
                    terminals_before = await client.request(
                        "thread/backgroundTerminals/list",
                        {"threadId": thread_id},
                    )
                    clean_response = await client.request(
                        "thread/backgroundTerminals/clean",
                        {"threadId": thread_id},
                    )
                    terminals_after = await client.request(
                        "thread/backgroundTerminals/list",
                        {"threadId": thread_id},
                    )
                    cleanup_completed_at = now()
                    terminal_cleanup = {
                        "experimental_api_enabled": True,
                        "started_after_interrupt_terminal": cleanup_started_at >= terminal_at,
                        "started_at": cleanup_started_at,
                        "terminals_before": terminals_before.get("data") or [],
                        "clean_response": clean_response,
                        "terminals_after": terminals_after.get("data") or [],
                        "completed_at": cleanup_completed_at,
                    }

                    content = handoff_content(stamp, "codex")
                    prompt = handoff_prompt(handoff_path, content)
                    before_observation = (interrupt_usage or observations)[-1]
                    handoff_started_at = now()
                    handoff_turn_result = await client.request(
                        "turn/start",
                        {
                            "threadId": thread_id,
                            "cwd": str(handoff_path.parent),
                            "approvalPolicy": "never",
                            "sandboxPolicy": {
                                "type": "workspaceWrite",
                                "writableRoots": [str(handoff_path.parent)],
                                "networkAccess": False,
                                "excludeSlashTmp": True,
                                "excludeTmpdirEnvVar": True,
                            },
                            "input": [{"type": "text", "text": prompt}],
                        },
                    )
                    handoff_turn = handoff_turn_result["turn"]
                    handoff_turn_id = handoff_turn["id"]
                    completed_item_types: list[str] = []
                    (
                        handoff_updates,
                        cumulative_last_total,
                        handoff_completed,
                    ) = await receive_completed_codex_turn(
                        client,
                        turn_id=handoff_turn_id,
                        cycle=len(observations) + 2,
                        cumulative_last_total=cumulative_last_total,
                        completed_item_types=completed_item_types,
                    )
                    for observation in handoff_updates:
                        observation["phase"] = "handoff"
                    handoff_terminal_at = now()
                    handoff_completed_turn = handoff_completed.get("turn") or {}
                    items = handoff_completed_turn.get("items") or []
                    after_observation = handoff_updates[-1] if handoff_updates else None
                    observed_content = (
                        handoff_path.read_text(encoding="utf-8") if handoff_path.is_file() else None
                    )
                    before_tokens = int(before_observation["last_total_tokens"])
                    after_tokens = (
                        int(after_observation["last_total_tokens"])
                        if after_observation is not None
                        else None
                    )
                    context_window = before_observation.get("model_context_window")
                    handoff = {
                        "prompt": prompt,
                        "prompt_is_one_line": "\n" not in prompt,
                        "original_thread_id": thread_id,
                        "handoff_thread_id": thread_id,
                        "same_session_as_interrupted": True,
                        "thread_start_request_count": 1,
                        "fresh_session_started": False,
                        "turn_id": handoff_turn_id,
                        "start_response_status": handoff_turn.get("status"),
                        "started_after_cleanup": handoff_started_at >= cleanup_completed_at,
                        "started_at": handoff_started_at,
                        "terminal_at": handoff_terminal_at,
                        "terminal_event": "turn/completed",
                        "terminal_status": handoff_completed_turn.get("status"),
                        "terminal_item_types": [item.get("type") for item in items],
                        "protocol_completed_item_types": completed_item_types,
                        "write_item_observed": any(
                            item_type in {"fileChange", "commandExecution"}
                            for item_type in completed_item_types
                        ),
                        "usage_observations": handoff_updates,
                        "occupancy_before_tokens": before_tokens,
                        "occupancy_after_tokens": after_tokens,
                        "headroom_consumed_tokens": (
                            after_tokens - before_tokens if after_tokens is not None else None
                        ),
                        "remaining_context_tokens": (
                            int(context_window) - after_tokens
                            if context_window is not None and after_tokens is not None
                            else None
                        ),
                        "document_path": str(handoff_path.relative_to(ROOT)),
                        "document_expected": content,
                        "document_observed": observed_content,
                        "document_matches": observed_content == content,
                        "document_sha256": sha256(handoff_path) if handoff_path.is_file() else None,
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
                "terminal_cleanup": terminal_cleanup,
                "handoff": handoff,
                "trace": str(trace_path.relative_to(ROOT)),
            }
    finally:
        trace.close()


def claude_options(
    workspace: Path,
    *,
    include_handoff: bool,
    handoff_directory: Path,
    can_use_tool: Any | None,
) -> ClaudeAgentOptions:
    disallowed_tools = [
        "Bash",
        "Read",
        "Glob",
        "Grep",
        "Edit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
    ]
    if not include_handoff:
        disallowed_tools.append("Write")
    return ClaudeAgentOptions(
        tools=["Write"] if include_handoff else [],
        allowed_tools=[],
        disallowed_tools=disallowed_tools,
        permission_mode="default" if include_handoff else "dontAsk",
        cwd=workspace,
        add_dirs=[handoff_directory] if include_handoff else [],
        setting_sources=[],
        max_turns=3,
        can_use_tool=can_use_tool,
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
    stamp: str,
    workspace: Path,
    *,
    target: int,
    max_cycles: int,
    include_handoff: bool,
    handoff_path: Path,
) -> dict[str, Any]:
    auth = claude_auth_status()
    milestone = "handoff" if include_handoff else "interruption"
    trace = Trace(TRACES / f"{stamp}-claude-{milestone}.jsonl")
    observations: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    permission_events: list[dict[str, Any]] = []
    phase = {"name": "warmup"}
    cumulative_billed_input = 0
    previous_direct: int | None = None
    init_model: str | None = None
    assistant_model: str | None = None
    session_id: str | None = None

    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], _context: Any
    ) -> PermissionResultAllow | PermissionResultDeny:
        raw_path = tool_input.get("file_path")
        candidate = Path(str(raw_path)) if raw_path is not None else None
        if candidate is not None and not candidate.is_absolute():
            candidate = workspace / candidate
        path_matches = candidate is not None and candidate.resolve() == handoff_path.resolve()
        allowed = phase["name"] == "handoff" and tool_name == "Write" and path_matches
        event = {
            "at": now(),
            "phase": phase["name"],
            "tool_name": tool_name,
            "path_matches": path_matches,
            "decision": "allow" if allowed else "deny",
        }
        permission_events.append(event)
        trace.write(
            "client.can_use_tool",
            {**event, "tool_input": tool_input},
        )
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="only the exact M3 Handoff write is permitted",
            interrupt=True,
        )

    try:
        async with ClaudeSDKClient(
            options=claude_options(
                workspace,
                include_handoff=include_handoff,
                handoff_directory=handoff_path.parent,
                can_use_tool=can_use_tool if include_handoff else None,
            )
        ) as client:
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
            handoff: dict[str, Any] | None = None
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

                if include_handoff and result.terminal_reason in CLAUDE_INTERRUPTED_REASONS:
                    before_usage = await client.get_context_usage()
                    before_observed_at = now()
                    trace.write("client.get_context_usage.before_handoff", before_usage)
                    content = handoff_content(stamp, "claude")
                    prompt = handoff_prompt(handoff_path, content)
                    phase["name"] = "handoff"
                    handoff_started_at = now()
                    trace.write("client.query.handoff", {"prompt": prompt})
                    await client.query(prompt)
                    (
                        handoff_result,
                        handoff_message_types,
                        _,
                        handoff_assistant_model,
                    ) = await drain_claude_response(
                        client,
                        trace,
                        source="server.receive.handoff",
                    )
                    assistant_model = handoff_assistant_model or assistant_model
                    handoff_terminal_at = now()
                    after_usage = await client.get_context_usage()
                    after_observed_at = now()
                    trace.write("client.get_context_usage.after_handoff", after_usage)
                    phase["name"] = "complete"
                    observed_content = (
                        handoff_path.read_text(encoding="utf-8") if handoff_path.is_file() else None
                    )
                    before_tokens = int(before_usage["totalTokens"])
                    after_tokens = int(after_usage["totalTokens"])
                    context_window = after_usage.get("maxTokens")
                    handoff = {
                        "prompt": prompt,
                        "prompt_is_one_line": "\n" not in prompt,
                        "original_session_id": session_id,
                        "interrupted_session_id": result.session_id,
                        "handoff_session_id": handoff_result.session_id,
                        "same_session_as_interrupted": (
                            handoff_result.session_id == result.session_id == session_id
                        ),
                        "client_connection_count": 1,
                        "fresh_session_started": handoff_result.session_id != session_id,
                        "started_after_interrupted_drain": handoff_started_at >= terminal_at,
                        "started_at": handoff_started_at,
                        "terminal_at": handoff_terminal_at,
                        "terminal_event": "ResultMessage",
                        "terminal_reason": handoff_result.terminal_reason,
                        "terminal_subtype": handoff_result.subtype,
                        "terminal_is_error": handoff_result.is_error,
                        "permission_denials": handoff_result.permission_denials or [],
                        "drained_message_types": handoff_message_types,
                        "drained_result_count": handoff_message_types.count("ResultMessage"),
                        "response": handoff_result.result,
                        "permission_events": permission_events,
                        "write_permission_observed": any(
                            event["phase"] == "handoff"
                            and event["tool_name"] == "Write"
                            and event["path_matches"]
                            and event["decision"] == "allow"
                            for event in permission_events
                        ),
                        "occupancy_before_observed_at": before_observed_at,
                        "occupancy_after_observed_at": after_observed_at,
                        "occupancy_before_tokens": before_tokens,
                        "occupancy_after_tokens": after_tokens,
                        "headroom_consumed_tokens": after_tokens - before_tokens,
                        "remaining_context_tokens": (
                            int(context_window) - after_tokens
                            if context_window is not None
                            else None
                        ),
                        "document_path": str(handoff_path.relative_to(ROOT)),
                        "document_expected": content,
                        "document_observed": observed_content,
                        "document_matches": observed_content == content,
                        "document_sha256": sha256(handoff_path) if handoff_path.is_file() else None,
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
                    "tools": ["Write"] if include_handoff else [],
                    "setting_sources": [],
                },
                "observations": observations,
                "threshold_crossing": crossing,
                "compactions": compactions,
                "compaction_before_target": bool(compactions and crossing is None),
                "interrupt": interrupt,
                "handoff": handoff,
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


def handoff_passed(name: str, evidence: dict[str, Any]) -> bool:
    handoff = evidence.get("handoff") or {}
    common = (
        handoff.get("prompt_is_one_line") is True
        and handoff.get("same_session_as_interrupted") is True
        and handoff.get("fresh_session_started") is False
        and handoff.get("document_matches") is True
        and isinstance(handoff.get("headroom_consumed_tokens"), int)
        and handoff["headroom_consumed_tokens"] > 0
        and isinstance(handoff.get("remaining_context_tokens"), int)
        and handoff["remaining_context_tokens"] > 0
    )
    if not common:
        return False
    if name == "codex":
        cleanup = evidence.get("terminal_cleanup") or {}
        return (
            cleanup.get("experimental_api_enabled") is True
            and cleanup.get("started_after_interrupt_terminal") is True
            and cleanup.get("terminals_after") == []
            and handoff.get("started_after_cleanup") is True
            and handoff.get("terminal_event") == "turn/completed"
            and handoff.get("terminal_status") == "completed"
            and handoff.get("write_item_observed") is True
            and handoff.get("thread_start_request_count") == 1
        )
    return (
        handoff.get("started_after_interrupted_drain") is True
        and handoff.get("terminal_event") == "ResultMessage"
        and handoff.get("terminal_is_error") is False
        and handoff.get("drained_result_count") == 1
        and handoff.get("write_permission_observed") is True
        and handoff.get("client_connection_count") == 1
        and not handoff.get("permission_denials")
    )


def outcome(summary: dict[str, Any], selected: str, *, include_handoff: bool) -> str:
    names = ("codex", "claude") if selected == "both" else (selected,)
    if not all(name in summary for name in names):
        return "partial"
    passed = all(harness_passed(name, summary[name]) for name in names)
    if include_handoff:
        passed = passed and all(handoff_passed(name, summary[name]) for name in names)
    return "pass" if passed else "fail"


async def run(selected: str, *, target: int, max_cycles: int, include_handoff: bool) -> int:
    require_keyless_environment()
    before = config_fingerprints()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    summary_path = HANDOFF_SUMMARY if include_handoff else INTERRUPTION_SUMMARY
    handoff_root = HANDOFFS / stamp
    if include_handoff:
        handoff_root.mkdir(parents=True)
        for harness_name in ("codex", "claude"):
            (handoff_root / harness_name).mkdir()
    summary: dict[str, Any] = {
        "captured_at": now(),
        "milestone": "M3 same-session Handoff" if include_handoff else "M2 interruption",
        "prototype_commit_before_run": command_output("git", "rev-parse", "HEAD"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "target_tokens": target,
        "max_cycles": max_cycles,
        "workload": {
            "files": list(FILES),
            "embedded_bytes_per_cycle": sum((REPO / path).stat().st_size for path in FILES),
            "tools": (
                "disabled during warm-up and interruption; one exact Handoff write permitted"
                if include_handoff
                else "disabled"
            ),
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
        with tempfile.TemporaryDirectory(
            prefix=(
                "context-chaining-handoff-" if include_handoff else "context-chaining-interruption-"
            )
        ) as directory:
            workspace = Path(directory)
            if selected in ("both", "codex"):
                summary["codex"] = await run_codex(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                    include_handoff=include_handoff,
                    handoff_path=handoff_root / "codex" / "handoff.md",
                )
                summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
            if selected in ("both", "claude"):
                summary["claude"] = await run_claude(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                    include_handoff=include_handoff,
                    handoff_path=handoff_root / "claude" / "handoff.md",
                )
    except Exception as error:
        summary["error"] = str(error)
        summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(f"milestone run stopped: {error}", file=sys.stderr)
        print(f"partial observations: {summary_path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    after = config_fingerprints()
    if before != after:
        raise RuntimeError("a watched persistent Harness configuration file changed during run")
    summary["persistent_config_changed"] = False
    for name in ("codex", "claude"):
        harness = summary.get(name)
        if harness:
            harness["trace_sha256"] = sha256(ROOT / harness["trace"])
    summary["outcome"] = outcome(summary, selected, include_handoff=include_handoff)
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"outcome: {summary['outcome']}")
    print(f"observations: {summary_path.relative_to(ROOT)}")
    return 0 if summary["outcome"] in ("pass", "partial") else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("both", "codex", "claude"), default="both")
    parser.add_argument("--target", type=positive_int, default=200_000)
    parser.add_argument("--max-cycles", type=positive_int, default=40)
    parser.add_argument("--handoff", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.only,
                target=args.target,
                max_cycles=args.max_cycles,
                include_handoff=args.handoff,
            )
        )
    )


if __name__ == "__main__":
    main()
