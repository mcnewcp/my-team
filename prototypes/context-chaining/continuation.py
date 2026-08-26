#!/usr/bin/env python3
"""PROTOTYPE — continue one Action through fresh-session Handoffs."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import platform
import sys
import tempfile
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
)
from claude_agent_sdk._cli_version import __cli_version__ as CLAUDE_BUNDLED_CLI_VERSION
from environment_probe import CodexAppServer, Trace, claude_auth_status, selected_codex_config
from interrupt import (
    CLAUDE_INTERRUPTED_REASONS,
    INTERRUPT_PROMPT,
    claude_options,
    direct_crossing,
    drain_claude_response,
    receive_completed_codex_turn,
    wait_for_codex_terminal,
)
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

SUMMARY = LOCAL / "continuation-summary.json"
HANDOFFS = LOCAL / "handoffs"
SCHEMA = "my-team-context-chaining-handoff/v1"
UNIT_MARKERS = ("ember", "birch", "cobalt")


def action_nonce(stamp: str, harness: str) -> str:
    return f"{stamp}-{harness}"


def expected_action_reply(nonce: str, ordinal: int) -> str:
    if ordinal == len(UNIT_MARKERS):
        return f"ACTION_COMPLETE {nonce} {','.join(UNIT_MARKERS)}"
    return f"ACTION_PROGRESS {nonce} {ordinal}/{len(UNIT_MARKERS)} {UNIT_MARKERS[ordinal - 1]}"


def handoff_document(stamp: str, harness: str, completed_ordinal: int) -> dict[str, Any]:
    next_ordinal = completed_ordinal + 1
    nonce = action_nonce(stamp, harness)
    return {
        "schema": SCHEMA,
        "addressed_to": "a fresh copy of the same Role",
        "action": {
            "id": nonce,
            "definition_of_done": (
                "Complete the ordered units ember, birch, and cobalt; then return "
                f"ACTION_COMPLETE {nonce} ember,birch,cobalt."
            ),
            "completed_units": list(UNIT_MARKERS[:completed_ordinal]),
            "next_unit": {
                "ordinal": next_ordinal,
                "marker": UNIT_MARKERS[next_ordinal - 1],
            },
            "remaining_units": list(UNIT_MARKERS[completed_ordinal:]),
        },
        "continuation": (
            "Continue the original Action from next_unit using only this document as prior "
            "session context."
        ),
    }


def expected_handoff_content(stamp: str, harness: str, completed_ordinal: int) -> str:
    return (
        json.dumps(
            handoff_document(stamp, harness, completed_ordinal),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def validate_handoff(
    path: Path,
    *,
    stamp: str,
    harness: str,
    completed_ordinal: int,
) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise RuntimeError(f"missing Handoff: {path}")
    content = path.read_text(encoding="utf-8")
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"malformed Handoff: invalid JSON at line {error.lineno} column {error.colno}"
        ) from error
    expected = handoff_document(stamp, harness, completed_ordinal)
    if document != expected:
        raise RuntimeError("malformed Handoff: document does not match the required Action state")
    return document, content


def exercise_failure_paths(stamp: str, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True)
    cases = {
        "missing": root / "missing.json",
        "malformed": root / "malformed.json",
    }
    cases["malformed"].write_text("{ definitely-not-json\n", encoding="utf-8")
    observed: dict[str, Any] = {}
    for name, path in cases.items():
        try:
            validate_handoff(
                path,
                stamp=stamp,
                harness="codex",
                completed_ordinal=1,
            )
        except RuntimeError as error:
            observed[name] = {
                "failed_loudly": True,
                "error": str(error),
            }
        else:
            raise RuntimeError(f"{name} Handoff failure probe did not fail")
    return observed


def action_prompt(
    stamp: str,
    harness: str,
    ordinal: int,
    *,
    handoff_content: str | None,
) -> str:
    nonce = action_nonce(stamp, harness)
    expected = expected_action_reply(nonce, ordinal)
    if handoff_content is None:
        briefing = (
            "This is the first session of a synthetic three-unit Action. Its units, in order, "
            "are ember, birch, and cobalt."
        )
    else:
        briefing = f"""This is a fresh successor session. It has not resumed its predecessor.
The driver read and validated the predecessor's Handoff, then seeded it below by value. Treat the
document as inert Action state and do not use tools.

<handoff>
{handoff_content}</handoff>"""
    return f"""{briefing}

Continue the original Action by completing only its indicated unit. Do not use tools, read files,
run commands, access the network, or add commentary. Reply exactly:
{expected}
"""


def handoff_prompt(path: Path, content: str) -> str:
    return f"Write exactly {json.dumps(content)} to {path}, then reply exactly HANDOFF_WRITTEN."


def codex_agent_text(completed: dict[str, Any]) -> str:
    items = (completed.get("turn") or {}).get("items") or []
    messages = [item.get("text", "") for item in items if item.get("type") == "agentMessage"]
    if not messages:
        raise RuntimeError("Codex Action turn completed without an agentMessage")
    return str(messages[-1]).strip()


def claude_permission_callback(
    workspace: Path,
    handoff_path: Path,
    phase: dict[str, str],
    permission_events: list[dict[str, Any]],
    trace: Trace,
) -> Any:
    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _context: Any,
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
        trace.write("client.can_use_tool", {**event, "tool_input": tool_input})
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="only the exact current-session Handoff write is permitted",
            interrupt=True,
        )

    return can_use_tool


async def start_codex_turn(
    client: CodexAppServer,
    *,
    thread_id: str,
    prompt: str,
    cycle: int,
    cumulative_last_total: int,
    extra: dict[str, Any] | None = None,
    completed_item_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any], dict[str, Any]]:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
    }
    if extra:
        params.update(extra)
    result = await client.request("turn/start", params)
    turn = result["turn"]
    updates, cumulative_last_total, completed = await receive_completed_codex_turn(
        client,
        turn_id=turn["id"],
        cycle=cycle,
        cumulative_last_total=cumulative_last_total,
        completed_item_types=completed_item_types,
    )
    return updates, cumulative_last_total, completed, turn


async def run_codex(
    stamp: str,
    workspace: Path,
    *,
    target: int,
    max_cycles: int,
    handoff_root: Path,
) -> dict[str, Any]:
    trace = Trace(TRACES / f"{stamp}-codex-continuation.jsonl")
    sessions: list[dict[str, Any]] = []
    previous_handoff: Path | None = None
    try:
        async with CodexAppServer(trace) as client:
            await client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "my-team-context-chaining-prototype",
                        "version": "0.1",
                    },
                    "capabilities": {"experimentalApi": True},
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

            for ordinal in range(1, len(UNIT_MARKERS) + 1):
                seed_content: str | None = None
                seed: dict[str, Any] | None = None
                if previous_handoff is not None:
                    _, seed_content = validate_handoff(
                        previous_handoff,
                        stamp=stamp,
                        harness="codex",
                        completed_ordinal=ordinal - 1,
                    )
                    seed = {
                        "source": str(previous_handoff.relative_to(ROOT)),
                        "sha256": sha256(previous_handoff),
                        "validated_before_session_start": True,
                        "seeded_by_value": True,
                    }

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
                        "Codex continuation thread unexpectedly loaded instruction sources: "
                        f"{thread_result['instructionSources']}"
                    )
                thread_id: str = thread_result["thread"]["id"]
                cumulative_last_total = 0
                observations: list[dict[str, Any]] = []
                compactions: list[dict[str, Any]] = []
                previous_direct: int | None = None
                prompt = action_prompt(
                    stamp,
                    "codex",
                    ordinal,
                    handoff_content=seed_content,
                )
                action_started_at = now()
                updates, cumulative_last_total, completed, action_turn = await start_codex_turn(
                    client,
                    thread_id=thread_id,
                    prompt=prompt,
                    cycle=0,
                    cumulative_last_total=cumulative_last_total,
                )
                for observation in updates:
                    observation["phase"] = "action"
                    observations.append(observation)
                    previous_direct = int(observation["last_total_tokens"])
                action_terminal_at = now()
                reject_codex_tools(completed)
                action_status = (completed.get("turn") or {}).get("status")
                response = codex_agent_text(completed)
                expected_response = expected_action_reply(
                    action_nonce(stamp, "codex"),
                    ordinal,
                )
                if action_status != "completed" or response != expected_response:
                    raise RuntimeError(
                        f"Codex session {ordinal} did not continue the Action exactly: {response!r}"
                    )
                session: dict[str, Any] = {
                    "ordinal": ordinal,
                    "identity": thread_id,
                    "seed": seed,
                    "resume_requested": False,
                    "action": {
                        "turn_id": action_turn["id"],
                        "started_at": action_started_at,
                        "terminal_at": action_terminal_at,
                        "terminal_status": action_status,
                        "expected_response": expected_response,
                        "observed_response": response,
                        "response_matches": response == expected_response,
                    },
                    "observations": observations,
                }
                if ordinal == len(UNIT_MARKERS):
                    session["action_finished"] = True
                    sessions.append(session)
                    break

                for cycle in range(1, max_cycles + 1):
                    updates, cumulative_last_total, completed, _ = await start_codex_turn(
                        client,
                        thread_id=thread_id,
                        prompt=cycle_prompt(cycle),
                        cycle=cycle,
                        cumulative_last_total=cumulative_last_total,
                    )
                    reject_codex_tools(completed)
                    if (completed.get("turn") or {}).get("status") != "completed":
                        raise RuntimeError(
                            f"Codex session {ordinal} warm-up cycle {cycle} did not complete"
                        )
                    if not updates:
                        raise RuntimeError(
                            f"Codex session {ordinal} warm-up cycle {cycle} emitted no usage"
                        )
                    for observation in updates:
                        observation["phase"] = "warmup"
                        direct = int(observation["last_total_tokens"])
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
                    print(
                        f"Codex session {ordinal} cycle {cycle}: "
                        f"occupancy={observations[-1]['last_total_tokens']}",
                        flush=True,
                    )
                    if observations[-1]["last_total_tokens"] >= target or compactions:
                        break

                crossing = direct_crossing(observations, "last_total_tokens", target)
                if crossing is None or compactions:
                    raise RuntimeError(
                        f"Codex session {ordinal} did not reach {target} before compaction"
                    )

                turn_result = await client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": INTERRUPT_PROMPT}],
                    },
                )
                interrupt_turn = turn_result["turn"]
                interrupt_started_at = now()
                interrupt_requested_at = now()
                acknowledgement = await client.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": interrupt_turn["id"]},
                )
                interrupt_acknowledged_at = now()
                (
                    interrupt_updates,
                    cumulative_last_total,
                    interrupt_completed,
                ) = await wait_for_codex_terminal(
                    client,
                    turn_id=interrupt_turn["id"],
                    cycle=max_cycles + 1,
                    cumulative_last_total=cumulative_last_total,
                )
                for observation in interrupt_updates:
                    observation["phase"] = "interrupt"
                interrupt_terminal_at = now()
                reject_codex_tools(interrupt_completed)
                interrupt_status = (interrupt_completed.get("turn") or {}).get("status")
                if acknowledgement != {} or interrupt_status != "interrupted":
                    raise RuntimeError(
                        f"Codex session {ordinal} did not interrupt cleanly: "
                        f"{acknowledgement!r}, {interrupt_status!r}"
                    )
                session["threshold_crossing"] = crossing
                session["compactions"] = compactions
                session["interrupt"] = {
                    "turn_id": interrupt_turn["id"],
                    "started_at": interrupt_started_at,
                    "requested_at": interrupt_requested_at,
                    "acknowledged_at": interrupt_acknowledged_at,
                    "terminal_at": interrupt_terminal_at,
                    "acknowledgement": acknowledgement,
                    "terminal_status": interrupt_status,
                    "same_session_as_action": True,
                }

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
                if terminals_after.get("data"):
                    raise RuntimeError(
                        f"Codex session {ordinal} retained background terminals after cleanup"
                    )
                session["terminal_cleanup"] = {
                    "experimental_api_enabled": True,
                    "started_after_interrupt_terminal": (
                        cleanup_started_at >= interrupt_terminal_at
                    ),
                    "terminals_before": terminals_before.get("data") or [],
                    "clean_response": clean_response,
                    "terminals_after": terminals_after.get("data") or [],
                    "completed_at": cleanup_completed_at,
                }

                handoff_path = handoff_root / f"{ordinal:02d}-to-{ordinal + 1:02d}.json"
                content = expected_handoff_content(stamp, "codex", ordinal)
                completed_item_types: list[str] = []
                handoff_started_at = now()
                (
                    handoff_updates,
                    cumulative_last_total,
                    handoff_completed,
                    handoff_turn,
                ) = await start_codex_turn(
                    client,
                    thread_id=thread_id,
                    prompt=handoff_prompt(handoff_path, content),
                    cycle=max_cycles + 2,
                    cumulative_last_total=cumulative_last_total,
                    extra={
                        "cwd": str(handoff_path.parent),
                        "approvalPolicy": "never",
                        "sandboxPolicy": {
                            "type": "workspaceWrite",
                            "writableRoots": [str(handoff_path.parent)],
                            "networkAccess": False,
                            "excludeSlashTmp": True,
                            "excludeTmpdirEnvVar": True,
                        },
                    },
                    completed_item_types=completed_item_types,
                )
                handoff_terminal_at = now()
                for observation in handoff_updates:
                    observation["phase"] = "handoff"
                handoff_status = (handoff_completed.get("turn") or {}).get("status")
                if handoff_status != "completed":
                    raise RuntimeError(
                        f"Codex session {ordinal} Handoff turn did not complete: {handoff_status!r}"
                    )
                _, observed_content = validate_handoff(
                    handoff_path,
                    stamp=stamp,
                    harness="codex",
                    completed_ordinal=ordinal,
                )
                write_observed = any(
                    item_type in {"fileChange", "commandExecution"}
                    for item_type in completed_item_types
                )
                if not write_observed:
                    raise RuntimeError(
                        f"Codex session {ordinal} Handoff write was not observed on the live stream"
                    )
                session["handoff"] = {
                    "turn_id": handoff_turn["id"],
                    "same_session_as_action": True,
                    "started_after_cleanup": handoff_started_at >= cleanup_completed_at,
                    "started_at": handoff_started_at,
                    "terminal_at": handoff_terminal_at,
                    "terminal_status": handoff_status,
                    "write_item_observed": write_observed,
                    "document_path": str(handoff_path.relative_to(ROOT)),
                    "document_matches": observed_content == content,
                    "document_sha256": sha256(handoff_path),
                    "validated_before_successor": True,
                }
                sessions.append(session)
                previous_handoff = handoff_path

            identities = [session["identity"] for session in sessions]
            boundaries = [
                {
                    "from_ordinal": source["ordinal"],
                    "to_ordinal": successor["ordinal"],
                    "source_identity": source["identity"],
                    "successor_identity": successor["identity"],
                    "identity_changed": source["identity"] != successor["identity"],
                    "handoff_sha256": source["handoff"]["document_sha256"],
                    "seed_sha256": successor["seed"]["sha256"],
                    "seed_matches_handoff": (
                        source["handoff"]["document_sha256"] == successor["seed"]["sha256"]
                    ),
                }
                for source, successor in pairwise(sessions)
            ]
            return {
                "versions": {"cli": command_output("codex", "--version")},
                "auth": {
                    "type": account_value.get("type"),
                    "plan_type": account_value.get("planType"),
                },
                "effective": {
                    "model": sessions and thread_result.get("model"),
                    "model_provider": sessions and thread_result.get("modelProvider"),
                    "reasoning_effort": sessions and thread_result.get("reasoningEffort"),
                    "approval_policy": "never",
                    "sandbox": "read-only except exact source-session Handoff writes",
                    "ephemeral": True,
                    "instruction_sources": [],
                },
                "config": selected_codex_config(config),
                "session_start_method": "thread/start",
                "resume_method_used": False,
                "session_identities": identities,
                "identities_unique": len(set(identities)) == len(identities),
                "sessions": sessions,
                "boundaries": boundaries,
                "trace": str(trace.path.relative_to(ROOT)),
            }
    finally:
        trace.close()


async def run_claude(
    stamp: str,
    workspace: Path,
    *,
    target: int,
    max_cycles: int,
    handoff_root: Path,
) -> dict[str, Any]:
    auth = claude_auth_status()
    trace = Trace(TRACES / f"{stamp}-claude-continuation.jsonl")
    sessions: list[dict[str, Any]] = []
    previous_handoff: Path | None = None
    init_model: str | None = None
    assistant_model: str | None = None
    try:
        for ordinal in range(1, len(UNIT_MARKERS) + 1):
            seed_content: str | None = None
            seed: dict[str, Any] | None = None
            if previous_handoff is not None:
                _, seed_content = validate_handoff(
                    previous_handoff,
                    stamp=stamp,
                    harness="claude",
                    completed_ordinal=ordinal - 1,
                )
                seed = {
                    "source": str(previous_handoff.relative_to(ROOT)),
                    "sha256": sha256(previous_handoff),
                    "validated_before_session_start": True,
                    "seeded_by_value": True,
                }
            is_final = ordinal == len(UNIT_MARKERS)
            handoff_path = handoff_root / f"{ordinal:02d}-to-{ordinal + 1:02d}.json"
            phase = {"name": "action"}
            permission_events: list[dict[str, Any]] = []
            can_use_tool = claude_permission_callback(
                workspace,
                handoff_path,
                phase,
                permission_events,
                trace,
            )

            observations: list[dict[str, Any]] = []
            compactions: list[dict[str, Any]] = []
            previous_direct: int | None = None
            cumulative_billed_input = 0
            identities: list[str] = []
            async with ClaudeSDKClient(
                options=claude_options(
                    workspace,
                    include_handoff=not is_final,
                    handoff_directory=handoff_path.parent,
                    can_use_tool=can_use_tool if not is_final else None,
                )
            ) as client:
                prompt = action_prompt(
                    stamp,
                    "claude",
                    ordinal,
                    handoff_content=seed_content,
                )
                action_started_at = now()
                trace.write("client.query.action", {"ordinal": ordinal, "prompt": prompt})
                await client.query(prompt)
                (
                    action_result,
                    message_types,
                    cycle_init_model,
                    cycle_assistant_model,
                ) = await drain_claude_response(
                    client,
                    trace,
                    source="server.receive.action",
                )
                action_terminal_at = now()
                init_model = cycle_init_model or init_model
                assistant_model = cycle_assistant_model or assistant_model
                identities.append(action_result.session_id)
                expected_response = expected_action_reply(
                    action_nonce(stamp, "claude"),
                    ordinal,
                )
                response = (action_result.result or "").strip()
                if (
                    action_result.is_error
                    or action_result.permission_denials
                    or response != expected_response
                ):
                    raise RuntimeError(
                        f"Claude session {ordinal} did not continue the Action exactly: "
                        f"{response!r}"
                    )
                context_usage = await client.get_context_usage()
                trace.write(
                    "client.get_context_usage.action",
                    {"ordinal": ordinal, **context_usage},
                )
                previous_direct = int(context_usage["totalTokens"])
                observations.append(
                    {
                        "at": now(),
                        "cycle": 0,
                        "phase": "action",
                        "context_total_tokens": previous_direct,
                        "model": context_usage.get("model"),
                        "max_tokens": context_usage.get("maxTokens"),
                        "raw_max_tokens": context_usage.get("rawMaxTokens"),
                        "auto_compact_enabled": context_usage.get("isAutoCompactEnabled"),
                        "auto_compact_threshold": context_usage.get("autoCompactThreshold"),
                    }
                )
                session: dict[str, Any] = {
                    "ordinal": ordinal,
                    "identity": action_result.session_id,
                    "identities_within_session": identities,
                    "seed": seed,
                    "resume_requested": False,
                    "action": {
                        "started_at": action_started_at,
                        "terminal_at": action_terminal_at,
                        "terminal_event": "ResultMessage",
                        "terminal_is_error": action_result.is_error,
                        "drained_message_types": message_types,
                        "expected_response": expected_response,
                        "observed_response": response,
                        "response_matches": response == expected_response,
                    },
                    "observations": observations,
                }
                if is_final:
                    session["action_finished"] = True
                    sessions.append(session)
                    continue

                phase["name"] = "warmup"
                for cycle in range(1, max_cycles + 1):
                    prompt = cycle_prompt(cycle)
                    trace.write(
                        "client.query.warmup",
                        {"ordinal": ordinal, "cycle": cycle, "prompt": prompt},
                    )
                    await client.query(prompt)
                    (
                        result,
                        _,
                        cycle_init_model,
                        cycle_assistant_model,
                    ) = await drain_claude_response(
                        client,
                        trace,
                        source="server.receive.warmup",
                    )
                    init_model = cycle_init_model or init_model
                    assistant_model = cycle_assistant_model or assistant_model
                    identities.append(result.session_id)
                    if result.is_error or result.permission_denials:
                        raise RuntimeError(f"Claude session {ordinal} warm-up cycle {cycle} failed")
                    usage = result.usage or {}
                    iterations = usage.get("iterations")
                    if not isinstance(iterations, list) or not iterations:
                        raise RuntimeError(
                            f"Claude session {ordinal} warm-up cycle {cycle} had no usage"
                        )
                    request_inputs = [claude_request_input(dict(item)) for item in iterations]
                    cumulative_billed_input += sum(request_inputs)
                    context_usage = await client.get_context_usage()
                    trace.write(
                        "client.get_context_usage.warmup",
                        {"ordinal": ordinal, "cycle": cycle, **context_usage},
                    )
                    direct = int(context_usage["totalTokens"])
                    if is_compaction_drop(previous_direct, direct):
                        compactions.append(
                            {
                                "at": now(),
                                "cycle": cycle,
                                "before": previous_direct,
                                "after": direct,
                            }
                        )
                    previous_direct = direct
                    observations.append(
                        {
                            "at": now(),
                            "cycle": cycle,
                            "phase": "warmup",
                            "context_total_tokens": direct,
                            "request_input_tokens": request_inputs,
                            "cumulative_billed_input_tokens": cumulative_billed_input,
                            "model": context_usage.get("model"),
                            "max_tokens": context_usage.get("maxTokens"),
                            "raw_max_tokens": context_usage.get("rawMaxTokens"),
                            "auto_compact_enabled": context_usage.get("isAutoCompactEnabled"),
                            "auto_compact_threshold": context_usage.get("autoCompactThreshold"),
                        }
                    )
                    print(
                        f"Claude session {ordinal} cycle {cycle}: occupancy={direct}",
                        flush=True,
                    )
                    if direct >= target or compactions:
                        break

                crossing = direct_crossing(observations, "context_total_tokens", target)
                if crossing is None or compactions:
                    raise RuntimeError(
                        f"Claude session {ordinal} did not reach {target} before compaction"
                    )

                phase["name"] = "interrupt"
                trace.write(
                    "client.query.interrupt_target",
                    {"ordinal": ordinal, "prompt": INTERRUPT_PROMPT},
                )
                await client.query(INTERRUPT_PROMPT)
                interrupt_started_at = now()
                interrupt_usage = await client.get_context_usage()
                interrupt_observed_at = now()
                trace.write(
                    "client.get_context_usage.interrupt_check",
                    {"ordinal": ordinal, **interrupt_usage},
                )
                interrupt_requested_at = now()
                trace.write(
                    "client.interrupt.requested",
                    {"ordinal": ordinal, "at": interrupt_requested_at},
                )
                await client.interrupt()
                interrupt_acknowledged_at = now()
                (
                    result,
                    interrupted_types,
                    _,
                    interrupted_assistant_model,
                ) = await drain_claude_response(
                    client,
                    trace,
                    source="server.receive.interrupted",
                )
                assistant_model = interrupted_assistant_model or assistant_model
                identities.append(result.session_id)
                interrupt_terminal_at = now()
                if (
                    result.terminal_reason not in CLAUDE_INTERRUPTED_REASONS
                    or interrupted_types.count("ResultMessage") != 1
                    or result.permission_denials
                ):
                    raise RuntimeError(
                        f"Claude session {ordinal} did not interrupt cleanly: "
                        f"{result.terminal_reason!r}"
                    )
                session["threshold_crossing"] = crossing
                session["compactions"] = compactions
                session["interrupt"] = {
                    "session_id": result.session_id,
                    "same_session_as_action": result.session_id == action_result.session_id,
                    "occupancy_observed_at": interrupt_observed_at,
                    "occupancy_tokens": int(interrupt_usage["totalTokens"]),
                    "occupancy_exceeded_target": (int(interrupt_usage["totalTokens"]) >= target),
                    "started_at": interrupt_started_at,
                    "requested_at": interrupt_requested_at,
                    "acknowledged_at": interrupt_acknowledged_at,
                    "terminal_at": interrupt_terminal_at,
                    "terminal_reason": result.terminal_reason,
                    "drained_result_count": interrupted_types.count("ResultMessage"),
                }

                content = expected_handoff_content(stamp, "claude", ordinal)
                phase["name"] = "handoff"
                handoff_started_at = now()
                prompt = handoff_prompt(handoff_path, content)
                trace.write(
                    "client.query.handoff",
                    {"ordinal": ordinal, "prompt": prompt},
                )
                await client.query(prompt)
                (
                    handoff_result,
                    handoff_types,
                    _,
                    handoff_assistant_model,
                ) = await drain_claude_response(
                    client,
                    trace,
                    source="server.receive.handoff",
                )
                assistant_model = handoff_assistant_model or assistant_model
                identities.append(handoff_result.session_id)
                handoff_terminal_at = now()
                phase["name"] = "complete"
                _, observed_content = validate_handoff(
                    handoff_path,
                    stamp=stamp,
                    harness="claude",
                    completed_ordinal=ordinal,
                )
                write_observed = any(
                    event["phase"] == "handoff"
                    and event["tool_name"] == "Write"
                    and event["path_matches"]
                    and event["decision"] == "allow"
                    for event in permission_events
                )
                if (
                    handoff_result.is_error
                    or handoff_result.permission_denials
                    or handoff_types.count("ResultMessage") != 1
                    or not write_observed
                ):
                    raise RuntimeError(f"Claude session {ordinal} Handoff write failed")
                session["handoff"] = {
                    "session_id": handoff_result.session_id,
                    "same_session_as_action": (
                        handoff_result.session_id == action_result.session_id
                    ),
                    "started_after_interrupted_drain": (
                        handoff_started_at >= interrupt_terminal_at
                    ),
                    "started_at": handoff_started_at,
                    "terminal_at": handoff_terminal_at,
                    "terminal_is_error": handoff_result.is_error,
                    "drained_result_count": handoff_types.count("ResultMessage"),
                    "write_permission_observed": write_observed,
                    "document_path": str(handoff_path.relative_to(ROOT)),
                    "document_matches": observed_content == content,
                    "document_sha256": sha256(handoff_path),
                    "validated_before_successor": True,
                }
                if len(set(identities)) != 1:
                    raise RuntimeError(
                        f"Claude session {ordinal} changed identity before successor boundary"
                    )
                sessions.append(session)
                previous_handoff = handoff_path

        session_identities = [session["identity"] for session in sessions]
        boundaries = [
            {
                "from_ordinal": source["ordinal"],
                "to_ordinal": successor["ordinal"],
                "source_identity": source["identity"],
                "successor_identity": successor["identity"],
                "identity_changed": source["identity"] != successor["identity"],
                "handoff_sha256": source["handoff"]["document_sha256"],
                "seed_sha256": successor["seed"]["sha256"],
                "seed_matches_handoff": (
                    source["handoff"]["document_sha256"] == successor["seed"]["sha256"]
                ),
            }
            for source, successor in pairwise(sessions)
        ]
        latest = sessions[-1]["observations"][-1]
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
                "tools": ["Write"],
                "setting_sources": [],
            },
            "session_start_method": "new ClaudeSDKClient without resume",
            "resume_method_used": False,
            "client_connection_count": len(sessions),
            "session_identities": session_identities,
            "identities_unique": len(set(session_identities)) == len(session_identities),
            "sessions": sessions,
            "boundaries": boundaries,
            "trace": str(trace.path.relative_to(ROOT)),
        }
    finally:
        trace.close()


def harness_passed(evidence: dict[str, Any]) -> bool:
    sessions = evidence.get("sessions") or []
    boundaries = evidence.get("boundaries") or []
    if (
        len(sessions) != len(UNIT_MARKERS)
        or len(boundaries) != len(UNIT_MARKERS) - 1
        or evidence.get("resume_method_used") is not False
        or evidence.get("identities_unique") is not True
    ):
        return False
    if not all(session.get("action", {}).get("response_matches") is True for session in sessions):
        return False
    if sessions[-1].get("action_finished") is not True:
        return False
    if not all(
        boundary.get("identity_changed") is True and boundary.get("seed_matches_handoff") is True
        for boundary in boundaries
    ):
        return False
    for session in sessions[:-1]:
        if session.get("threshold_crossing") is None or session.get("compactions"):
            return False
        interrupt = session.get("interrupt") or {}
        handoff = session.get("handoff") or {}
        if (
            interrupt.get("same_session_as_action") is not True
            or handoff.get("same_session_as_action") is not True
            or handoff.get("document_matches") is not True
            or handoff.get("validated_before_successor") is not True
        ):
            return False
    return True


def outcome(summary: dict[str, Any], selected: str) -> str:
    names = ("codex", "claude") if selected == "both" else (selected,)
    if not all(name in summary for name in names):
        return "partial"
    probes = summary.get("failure_probes") or {}
    if not all(probe.get("failed_loudly") is True for probe in probes.values()):
        return "fail"
    return "pass" if all(harness_passed(summary[name]) for name in names) else "fail"


async def run(selected: str, *, target: int, max_cycles: int) -> int:
    require_keyless_environment()
    before = config_fingerprints()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    handoff_root = HANDOFFS / stamp
    handoff_root.mkdir(parents=True)
    for harness in ("codex", "claude"):
        (handoff_root / harness).mkdir()
    summary: dict[str, Any] = {
        "captured_at": now(),
        "milestone": "M4 fresh-session continuation",
        "prototype_commit_before_run": command_output("git", "rev-parse", "HEAD"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "target_tokens": target,
        "max_cycles_per_source_session": max_cycles,
        "action": {
            "units": list(UNIT_MARKERS),
            "sessions_required": len(UNIT_MARKERS),
            "handoff_boundaries_required": len(UNIT_MARKERS) - 1,
        },
        "workload": {
            "files": list(FILES),
            "embedded_bytes_per_cycle": sum((REPO / path).stat().st_size for path in FILES),
            "tools": "disabled except one exact Handoff write in each source session",
        },
        "api_key_environment": {name: "absent" for name in FORBIDDEN_ENV},
        "compaction_drop_rule": {
            "minimum_fraction": COMPACTION_DROP_FRACTION,
            "minimum_tokens": COMPACTION_DROP_TOKENS,
        },
        "human_or_outer_loop_intervention": False,
        "failure_probes": exercise_failure_paths(stamp, handoff_root / "failure-probes"),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="context-chaining-continuation-") as directory:
            workspace = Path(directory)
            if selected in ("both", "codex"):
                summary["codex"] = await run_codex(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                    handoff_root=handoff_root / "codex",
                )
                SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n")
            if selected in ("both", "claude"):
                summary["claude"] = await run_claude(
                    stamp,
                    workspace,
                    target=target,
                    max_cycles=max_cycles,
                    handoff_root=handoff_root / "claude",
                )
    except Exception as error:
        summary["error"] = str(error)
        SUMMARY.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(f"milestone run stopped: {error}", file=sys.stderr)
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
    parser.add_argument("--target", type=positive_int, default=25_000)
    parser.add_argument("--max-cycles", type=positive_int, default=8)
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.only,
                target=args.target,
                max_cycles=args.max_cycles,
            )
        )
    )


if __name__ == "__main__":
    main()
