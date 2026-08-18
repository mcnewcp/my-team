#!/usr/bin/env python3
"""PROTOTYPE -- throwaway. Drives the Claude Code CLI headless, one shot.

Built to the contract settled in my-team#3: the raw CLI rather than the SDK,
`stream-json` output, context read passively off every assistant message's
`usage`, and the outcome taken from the `result` event's `is_error` rather than
from the process exit code.

Nothing here is production shape. It exists to find out what the stream really
looks like when it is pointed at a real repo.
"""

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Dispatch:
    """Everything one headless invocation told us about itself."""

    argv: list = field(default_factory=list)
    session_id: str | None = None
    model: str | None = None
    cwd: str | None = None
    slash_commands: list = field(default_factory=list)
    tools_available: int = 0

    returncode: int | None = None
    wall_seconds: float = 0.0
    timed_out: bool = False

    # from the terminal `result` event
    is_error: bool | None = None
    result_subtype: str | None = None
    result_text: str = ""
    num_turns: int | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    permission_denials: list = field(default_factory=list)

    # passively-observed context occupancy
    peak_context_tokens: int = 0
    context_samples: list = field(default_factory=list)

    tool_uses: list = field(default_factory=list)
    tool_errors: list = field(default_factory=list)
    events: int = 0
    unparsed_lines: int = 0
    stderr_tail: str = ""
    stream_path: str | None = None


_TEXT_PREVIEW = 160


def dispatch(
    prompt,
    cwd,
    *,
    add_dirs=(),
    allowed_tools=(),
    disallowed_tools=(),
    session_id=None,
    resume=None,
    model=None,
    permission_mode="acceptEdits",
    setting_sources="project",
    timeout=1800,
    log_path=None,
    echo=True,
):
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        permission_mode,
        "--setting-sources",
        setting_sources,
    ]
    if model:
        argv += ["--model", model]
    if resume:
        argv += ["--resume", resume]
    elif session_id:
        argv += ["--session-id", session_id]
    for d in add_dirs:
        argv += ["--add-dir", str(d)]
    if allowed_tools:
        argv += ["--allowedTools", *allowed_tools]
    if disallowed_tools:
        argv += ["--disallowedTools", *disallowed_tools]

    d = Dispatch(argv=argv, cwd=str(cwd), stream_path=str(log_path) if log_path else None)
    log = open(log_path, "w") if log_path else None
    seen_message_ids = set()

    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    q = queue.Queue()

    def _reader(stream, tag):
        for line in stream:
            q.put((tag, line))
        q.put((tag, None))

    threading.Thread(target=_reader, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=_reader, args=(proc.stderr, "err"), daemon=True).start()

    deadline = started + timeout
    closed = 0
    err_lines = []
    while closed < 2:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            d.timed_out = True
            proc.terminate()
            break
        try:
            tag, line = q.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue
        if line is None:
            closed += 1
            continue
        if tag == "err":
            err_lines.append(line)
            continue
        if log:
            log.write(line)
            log.flush()
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            d.unparsed_lines += 1
            if echo:
                print(f"    [!] unparsed stdout line: {line[:120]}")
            continue
        d.events += 1
        _absorb(d, ev, seen_message_ids, echo)

    proc.wait()
    d.returncode = proc.returncode
    d.wall_seconds = time.monotonic() - started
    d.stderr_tail = "".join(err_lines)[-2000:]
    if log:
        log.close()
    return d


def _absorb(d, ev, seen_message_ids, echo):
    t = ev.get("type")

    if t == "system" and ev.get("subtype") == "init":
        d.session_id = ev.get("session_id")
        d.model = ev.get("model")
        d.slash_commands = ev.get("slash_commands") or []
        d.tools_available = len(ev.get("tools") or [])
        if echo:
            print(
                f"    [init] session={d.session_id} model={d.model} "
                f"tools={d.tools_available} slash_commands={len(d.slash_commands)} "
                f"mode={ev.get('permissionMode')}"
            )
        return

    if t == "assistant":
        msg = ev.get("message") or {}
        mid = msg.get("id")
        usage = msg.get("usage") or {}
        ctx = (
            (usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
        )
        if mid and mid not in seen_message_ids:
            seen_message_ids.add(mid)
            if ctx:
                d.context_samples.append(ctx)
                d.peak_context_tokens = max(d.peak_context_tokens, ctx)
        for block in msg.get("content") or []:
            bt = block.get("type")
            if bt == "tool_use":
                name = block.get("name")
                d.tool_uses.append(name)
                if echo:
                    print(f"    [tool] {name} {_gist(block.get('input'))}")
            elif bt == "text" and echo:
                text = (block.get("text") or "").strip().replace("\n", " ")
                if text:
                    print(f"    [say ] {text[:_TEXT_PREVIEW]}")
        return

    if t == "user":
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                content = str(content or "").replace("\n", " ")
                d.tool_errors.append(content[:400])
                if echo:
                    print(f"    [ERR ] {content[:_TEXT_PREVIEW]}")
        return

    if t == "result":
        d.is_error = ev.get("is_error")
        d.result_subtype = ev.get("subtype")
        d.result_text = ev.get("result") or ""
        d.num_turns = ev.get("num_turns")
        d.total_cost_usd = ev.get("total_cost_usd")
        d.duration_ms = ev.get("duration_ms")
        d.duration_api_ms = ev.get("duration_api_ms")
        d.permission_denials = ev.get("permission_denials") or []
        if echo:
            print(
                f"    [done] subtype={d.result_subtype} is_error={d.is_error} "
                f"turns={d.num_turns} cost=${d.total_cost_usd}"
            )
        return


def _gist(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("command", "file_path", "pattern", "path", "description"):
        if key in payload:
            return str(payload[key]).replace("\n", " ")[:100]
    return ""


def summarise(d):
    lines = [
        f"  exit={d.returncode} timed_out={d.timed_out} wall={d.wall_seconds:.1f}s",
        f"  is_error={d.is_error} subtype={d.result_subtype} turns={d.num_turns} cost=${d.total_cost_usd}",
        f"  peak_context={d.peak_context_tokens} tokens over {len(d.context_samples)} samples",
        f"  tool_uses={len(d.tool_uses)} tool_errors={len(d.tool_errors)} "
        f"permission_denials={len(d.permission_denials)} events={d.events}",
        f"  stream={d.stream_path}",
    ]
    if d.tool_uses:
        counts = {}
        for name in d.tool_uses:
            counts[name] = counts.get(name, 0) + 1
        lines.append("  tools: " + ", ".join(f"{k}x{v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)
