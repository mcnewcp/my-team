# The Claude Code headless contract

Research for ticket #3. Decides whether the `my-team` orchestrator can hold the context
budget itself, or whether the agent must self-monitor.

**Tested against:** `claude --version` → `2.1.233 (Claude Code)`, macOS (Darwin 25.5.0),
binary at `/Users/coymcnew/.local/bin/claude`.
**Python SDK version referenced:** `claude-agent-sdk` 0.2.139 (PyPI, as of 2026-08-15).

Every claim below is either (a) an observed command output, pasted verbatim, or (b) cited
to a primary doc URL. Anything inferred rather than observed is marked **UNVERIFIED**.

---

## Headline answers

**1. Yes — the orchestrator can hold the context budget itself.** Two independent
mechanisms, both available from the raw CLI with no SDK:

- A **`get_context_usage` control request** over `--input-format stream-json` returns a
  fully structured context-window breakdown mid-session, including
  `totalTokens`, `maxTokens`, `percentage`, and `autoCompactThreshold`. This is the exact
  number the state machine needs. Observed wire shape in [§2](#2-context-budget-observability-the-load-bearing-answer).
- Every `assistant` message in `--output-format stream-json` carries `message.usage`.
  `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` **is** the current
  context size, for free, on every request. Cross-checked to within rounding against
  `/context` in [§2.3](#23-cross-check-the-arithmetic-is-correct).

The v0.1 "crude cap" **can be a real context-budget number** from day one. It does not have
to be a turn count or a wall-clock guess, and the agent does not have to self-report.

**2. SDK vs CLI: start with the CLI (`claude -p`), driven over `--input-format stream-json`
as a bidirectional protocol — not as one-shot `subprocess.run()`.** Recommendation and cost
in [§8](#8-the-sdk-question-recommendation).

The decisive fact: `ClaudeSDKClient.get_context_usage()`, `interrupt()`, and
`set_permission_mode()` are **not SDK-native capabilities**. They are thin wrappers that
emit `control_request` JSON lines on the subprocess's stdin. The SDK's own source proves
this, and I drove the same protocol by hand against the raw CLI successfully. So the CLI
loses nothing structural. What the SDK buys is typed messages, the `can_use_tool` callback,
in-process hooks, and not having to maintain the framing yourself.

---

## 1. The `stream-json` event shape (observed)

Command:

```bash
claude -p "Read note.txt and reply with only its contents." \
  --session-id "$SID" --model sonnet --allowedTools "Read" \
  --permission-mode acceptEdits --output-format stream-json --verbose
```

Exit code 0. Eight NDJSON lines. Event sequence and top-level keys:

```
line 0: type=system   subtype=init
line 1: type=system   subtype=thinking_tokens
line 2: type=system   subtype=thinking_tokens
line 3: type=assistant
line 4: type=assistant
line 5: type=user                              (tool_result)
line 6: type=assistant
line 7: type=result   subtype=success
```

### 1.1 `system/init`

Observed (long arrays elided):

```json
{
  "type": "system",
  "subtype": "init",
  "cwd": "/private/tmp/.../hdtest",
  "session_id": "7d418a9a-5235-4956-82fb-007ff43d3551",
  "tools": "<list len=25>",
  "mcp_servers": [],
  "model": "claude-sonnet-5",
  "permissionMode": "acceptEdits",
  "slash_commands": "<list len=46>",
  "terminal_slash_commands": ["doctor", "color"],
  "apiKeySource": "ANTHROPIC_API_KEY",
  "claude_code_version": "2.1.233",
  "output_style": "default",
  "agents": "<list len=5>",
  "skills": "<list len=17>",
  "plugins": "<list len=1>",
  "capabilities": [
    "interrupt_receipt_v1",
    "interrupt_cancel_queued_v1",
    "msg_lifecycle_v1"
  ],
  "uuid": "573240a3-7d2f-4232-8fa4-6757b46d44c1",
  "memory_paths": { "auto": "/Users/coymcnew/.claude/projects/.../memory/" },
  "messaging_socket_path": "/tmp/cc-socks/13639.sock",
  "fast_mode_state": "off",
  "fast_mode_disabled_reason": "sdk_opt_in_required"
}
```

`capabilities` is the documented feature-detection handle: *"an optional `capabilities`
array of strings naming the protocol behaviors this Claude Code version implements, such as
`interrupt_receipt_v1` or `interrupt_cancel_queued_v1`. Check it to feature-detect instead
of comparing version strings, and ignore values you don't recognize. The field requires
Claude Code v2.1.205 or later"*
— <https://code.claude.com/docs/en/headless>

**Use this.** It is the sanctioned way for the orchestrator to check that interruption is
supported before relying on it.

### 1.2 `assistant` — carries per-request usage

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-sonnet-5",
    "id": "msg_011Ce4yXc9sRn3bNXHccjchQ",
    "type": "message",
    "role": "assistant",
    "content": [ { "type": "thinking", "thinking": "", "signature": "..." } ],
    "stop_reason": null,
    "usage": {
      "input_tokens": 2,
      "cache_creation_input_tokens": 33100,
      "cache_read_input_tokens": 0,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 33100,
        "ephemeral_1h_input_tokens": 0
      },
      "output_tokens": 2,
      "service_tier": "standard",
      "inference_geo": "global"
    },
    "context_management": null
  },
  "parent_tool_use_id": null,
  "session_id": "7d418a9a-5235-4956-82fb-007ff43d3551",
  "uuid": "8bcdcc18-3efa-4c80-94eb-12d5709b671d",
  "timestamp": "2026-08-15T18:04:03.268Z",
  "request_id": "req_011Ce4yXbXAYmuYjcBUppasm"
}
```

Note `parent_tool_use_id: null` marks the main loop; subagent messages carry the spawning
tool call's ID (<https://code.claude.com/docs/en/headless>).

### 1.3 `system/thinking_tokens` — a decoy, do not use

```json
{ "type": "system", "subtype": "thinking_tokens",
  "estimated_tokens": 71, "estimated_tokens_delta": 21,
  "uuid": "...", "session_id": "..." }
```

This counts **thinking-block tokens only**, not context. It is not a context-budget signal.

### 1.4 `result` — the terminal event

```json
{
  "is_error": false,
  "duration_api_ms": 6235,
  "num_turns": 2,
  "stop_reason": "end_turn",
  "session_id": "7d418a9a-5235-4956-82fb-007ff43d3551",
  "total_cost_usd": 0.13741274999999997,
  "usage": {
    "input_tokens": 4,
    "cache_creation_input_tokens": 33285,
    "cache_read_input_tokens": 33100,
    "output_tokens": 137,
    "output_tokens_details": { "thinking_tokens": 14 },
    "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
    "iterations": [ { "input_tokens": 2, "output_tokens": 5,
                      "cache_read_input_tokens": 33100,
                      "cache_creation_input_tokens": 185, "type": "message" } ],
    "speed": "standard"
  },
  "modelUsage": {
    "claude-haiku-4-5-20251001": {
      "inputTokens": 527, "outputTokens": 14,
      "costUSD": 0.000597, "contextWindow": 200000,
      "maxOutputTokens": 32000, "canonicalModel": "claude-haiku-4-5",
      "provider": "firstParty"
    },
    "claude-sonnet-5": {
      "inputTokens": 4, "outputTokens": 137,
      "cacheReadInputTokens": 33100, "cacheCreationInputTokens": 33285,
      "costUSD": 0.13681574999999996, "contextWindow": 1000000,
      "maxOutputTokens": 64000, "canonicalModel": "claude-sonnet-5",
      "provider": "firstParty"
    }
  },
  "permission_denials": [],
  "terminal_reason": "completed",
  "subtype": "success",
  "api_error_status": null,
  "result": "hello world",
  "ttft_ms": 1932,
  "type": "result",
  "duration_ms": 4378,
  "uuid": "9f96b6d0-f1d4-4db5-b981-bb2260781edc"
}
```

Two fields matter beyond the documented set:

- **`modelUsage[<model>].contextWindow`** — the model's raw window (1,000,000 for
  `claude-sonnet-5` here). Not mentioned on the cost-tracking doc page, but observed
  reliably in every run.
- **`terminal_reason`** — an undocumented but highly legible termination discriminator.
  Observed values across my runs: `completed`, `aborted_streaming`, `max_turns`,
  `api_error`. **UNVERIFIED** that this is the exhaustive set; I have no primary source for
  this field at all. Treat `subtype` as the contract and `terminal_reason` as a bonus.

### 1.5 `--output-format json` returns *only* the result object

Verified: `--output-format json` emits a single JSON object identical in shape to the
`result` line above — no per-assistant-message usage. **If you want live context
observability, you must use `stream-json`.** `json` is a strictly weaker channel.

---

## 2. Context-budget observability (the load-bearing answer)

### 2.1 `get_context_usage` as a control request — works on the raw CLI

This is the single highest-value finding of the ticket.

The Python SDK's `ClaudeSDKClient.get_context_usage()` is implemented as one line
(<https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py>):

```python
    async def get_context_usage(self) -> dict[str, Any]:
        """Get a breakdown of current context window usage by category."""
        return await self._send_control_request({"subtype": "get_context_usage"})
```

So it is a wire-protocol feature of the CLI, not an SDK feature. I drove it directly
against `claude -p --input-format stream-json --output-format stream-json` with no SDK
installed.

**What you send on stdin** (one NDJSON line):

```json
{"type":"control_request","request_id":"ctx-1","request":{"subtype":"get_context_usage"}}
```

**What comes back on stdout** (observed, `categories` shown in full, large arrays elided):

```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "ctx-1",
    "response": {
      "totalTokens": 32973,
      "maxTokens": 967000,
      "rawMaxTokens": 967000,
      "percentage": 3,
      "model": "claude-sonnet-5",
      "isAutoCompactEnabled": true,
      "autoCompactThreshold": 934000,
      "autocompactSource": "model-default",
      "categories": [
        { "name": "System prompt",            "tokens": 8630,   "color": "promptBorder" },
        { "name": "System tools",             "tokens": 19441,  "color": "inactive" },
        { "name": "System tools (deferred)",  "tokens": 12981,  "color": "inactive",
          "isDeferred": true },
        { "name": "Skills",                   "tokens": 1816,   "color": "warning" },
        { "name": "Messages",                 "tokens": 3086,
          "color": "purple_FOR_SUBAGENTS_ONLY" },
        { "name": "Autocompact buffer",       "tokens": 33000,  "color": "inactive" },
        { "name": "Free space",               "tokens": 901027, "color": "promptBorder" }
      ],
      "messageBreakdown": {
        "toolCallTokens": 0, "toolResultTokens": 0, "attachmentTokens": 0,
        "assistantMessageTokens": 0, "userMessageTokens": 0,
        "redirectedContextTokens": 0, "unattributedTokens": 8,
        "toolCallsByType": [], "attachmentsByType": []
      },
      "apiUsage": null,
      "memoryFiles": [ ... ], "mcpTools": [ ... ], "agents": [ ... ],
      "skills": [ ... ], "slashCommands": [ ... ], "gridRows": [ ... ]
    }
  }
}
```

**The field that carries the number the orchestrator wants:**

| Field | Observed | Meaning |
|---|---|---|
| `totalTokens` | `32973` | tokens currently in the context window |
| `maxTokens` | `967000` | effective max (raw window minus autocompact buffer) |
| `rawMaxTokens` | `967000` | raw model context window |
| `percentage` | `3` | percent of window used, 0–100 |
| `autoCompactThreshold` | `934000` | **the token count at which auto-compaction fires** |
| `isAutoCompactEnabled` | `true` | whether compaction is armed for this session |

`autoCompactThreshold` is the real budget ceiling. A handoff trigger set below it is a
handoff the orchestrator controls; above it, Claude Code compacts first and the orchestrator
is reacting to a summary rather than driving the handoff.

I called this **before any turn ran** and **again after a turn**, on a live session, and it
answered both times without disturbing the conversation. It is a free, side-effect-free
poll.

The corresponding SDK type documents the same fields
(<https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py>):

```python
class ContextUsageResponse(TypedDict):
    """Response from `ClaudeSDKClient.get_context_usage()`.

    Provides a breakdown of current context window usage by category,
    matching the data shown by the `/context` command in the CLI.
    """
    categories: list[ContextUsageCategory]
    totalTokens: int
    """Total tokens currently in the context window."""
    maxTokens: int
    """Effective maximum tokens (may be reduced by autocompact buffer)."""
    rawMaxTokens: int
    """Raw model context window size."""
    percentage: float
    """Percentage of context window used (0-100)."""
    model: str
    isAutoCompactEnabled: bool
    memoryFiles: list[dict[str, Any]]
    mcpTools: list[dict[str, Any]]
    agents: list[dict[str, Any]]
```

`autoCompactThreshold`, `autocompactSource`, `messageBreakdown`, `apiUsage`, `skills`,
`slashCommands`, and `gridRows` appear in the observed payload but are **not** in the
published `ContextUsageResponse` TypedDict. **UNVERIFIED** whether they are stable —
treat the six fields in the table above as the contract and the rest as opportunistic.

> **Caveat that matters:** this requires holding the CLI process open with
> `--input-format stream-json`. A one-shot `claude -p "prompt"` that exits cannot be polled.
> This is the reason the substrate recommendation is "stream-json protocol", not
> "`subprocess.run`".

### 2.2 The zero-cost alternative: per-assistant-message usage

If the orchestrator does not want to hold a bidirectional pipe, it can still compute the
context size from the ordinary `stream-json` output stream, with no extra request:

```
context_tokens = message.usage.input_tokens
               + message.usage.cache_creation_input_tokens
               + message.usage.cache_read_input_tokens
```

against `result.modelUsage[<model>].contextWindow` for the denominator.

The docs confirm the input/cache halves are trustworthy per-step, and warn that only
*output* tokens are a placeholder:

> *"The deduplicated per-step values are accurate for input and cache tokens. Per-step
> `output_tokens` is a placeholder"* — <https://code.claude.com/docs/en/agent-sdk/cost-tracking>

> *"When Claude uses multiple tools in one turn, all messages in that turn share the same
> ID, so deduplicate by ID to avoid double-counting."* — same page

Deduplicate on `message.id`. Observed duplication in a real run confirms the warning:

```
assistant prompt_tokens = 32833
assistant prompt_tokens = 32833      <- same message.id
assistant prompt_tokens = 33000
assistant prompt_tokens = 33000      <- same message.id
assistant prompt_tokens = 33000
assistant prompt_tokens = 33359
```

Since the orchestrator wants a *maximum* (the high-water mark of context), `max()` over
these values is naturally dedup-immune.

### 2.3 Cross-check: the arithmetic is correct

Same session, two independent measurements:

- Max prompt tokens computed from the stream: **33,359**
- `/context` run against that session reports: **`Tokens: 33.4k / 967k (3%)`**

They agree. The formula is sound.

Note `967k` vs `contextWindow: 1000000`: `/context` and `maxTokens` report the raw window
*minus* the 33,000-token autocompact buffer. If you use `contextWindow` from `modelUsage` as
the denominator, subtract the buffer yourself, or prefer `maxTokens` from
`get_context_usage`.

### 2.4 Third path: `/context` as a prompt

`claude -p "/context" --resume "$SID" --output-format json` works and returns a Markdown
table in `result`:

```
## Context Usage

**Model:** claude-sonnet-5
**Tokens:** 33.2k / 967k (3%)

### Estimated usage by category

| Category | Tokens | Percentage |
|----------|--------|------------|
| System prompt | 8.6k | 0.9% |
| System tools | 19.4k | 2.0% |
| System tools (deferred) | 13k | 1.3% |
| Skills | 1.8k | 0.2% |
| Messages | 3.3k | 0.3% |
| Free space | 900.8k | 93.2% |
| Autocompact buffer | 33k | 3.4% |
```

Exit code 0. **Do not build on this.** It is Markdown prose requiring regex parsing, it
rounds to 0.1k, and it costs a full process start plus session load. It is a useful
debugging affordance and nothing more. The control request returns the same data as JSON.

Slash commands in `-p` are documented:

> *"User-invoked skills and custom commands work in `-p` mode: include `/skill-name` in the
> prompt string and Claude Code expands it before running. Built-in commands that only run
> in the terminal interface, such as `/login`, aren't available in `-p` mode."*
> — <https://code.claude.com/docs/en/headless>

This is what makes a `/handoff` skill viable as a prompt in either the interrupt path or the
resume path.

### 2.5 Compaction is observable

> *"When the context window approaches its limit, the SDK automatically compacts the
> conversation... The SDK emits a message with `type: "system"` and
> `subtype: "compact_boundary"` in the stream when this happens"*
> — <https://code.claude.com/docs/en/agent-sdk/agent-loop>

So `system/compact_boundary` is a backstop signal: if the orchestrator ever sees it, its
budget cap was set too high and compaction beat it to the handoff. I did **not** trigger
compaction empirically (it would require filling ~934k tokens), so the exact field
contents of that event are **UNVERIFIED** here.

`PreCompact` is also available as a hook, with a `trigger` field of `manual` or `auto`
(<https://code.claude.com/docs/en/agent-sdk/agent-loop>). In-process hooks are an SDK
affordance; from the CLI they would be settings-configured subprocess hooks.

---

## 3. Exit codes

**Is the exit code trustworthy enough to distinguish "finished the work" from "died
partway"? Partly — and the part it gets wrong is the dangerous one.**

Documented baseline:

> *"Claude Code exits with code 0 on success and a non-zero code when the run fails, so your
> scripts can branch on the exit status. If you pass an invalid flag, Claude Code reports the
> error to stderr before the run starts. When a failure happens inside the run, such as
> missing authentication, Claude Code prints the failure as the result on stdout."*
> — <https://code.claude.com/docs/en/headless>

> *"If you stop a `claude -p` run with SIGTERM, for example from `kill`, a process
> supervisor, or an SDK host closing the session, Claude Code aborts the in-progress turn,
> terminates the process tree of any running Bash command, runs `SessionEnd` hooks, and
> exits with code 143."* — same page

There is **no published exit-code table** beyond this. Everything else below is observed.

| Scenario | Exit | `subtype` | `is_error` | `terminal_reason` |
|---|---|---|---|---|
| Normal completion | `0` | `success` | `false` | `completed` |
| Unknown CLI flag | `1` | *(no JSON emitted)* | — | — |
| `--resume` unknown session | `1` | *(no JSON emitted)* | — | — |
| Invalid model | `1` | `success` ⚠️ | `true` | `api_error` |
| `--max-turns` exhausted | `1` | `error_max_turns` | `true` | `max_turns` |
| SIGTERM mid-run | `143` | `error_during_execution` | `true` | `aborted_streaming` |
| Tool blocked, agent gave up | `0` ⚠️ | `success` | `false` | `completed` |

Observed stderr for the two pre-flight failures:

```
No conversation found with session ID: 00000000-0000-4000-8000-000000000000
error: unknown option '--bogus-flag'
[claude-code:unrecognized_model] {"model":"not-a-real-model-xyz","query_source":"sdk"}
```

### 3.1 Two traps

**Trap 1: `subtype` can be `success` while `is_error` is `true`.** The invalid-model run
produced `subtype: "success"`, `is_error: true`, `api_error_status: 404`, and a `result`
string that is an English apology:

```json
{ "type": "result", "subtype": "success", "is_error": true,
  "terminal_reason": "api_error", "api_error_status": 404, "num_turns": 1,
  "result": "There's an issue with the selected model (not-a-real-model-xyz). It may not exist or you may not have access to it. Run --model to pick a different model." }
```

**Branch on `is_error` first, then `subtype`. Never on `subtype` alone.**

**Trap 2 — the one that actually threatens "completion is verified by observation":**
when a tool the agent needs is unavailable, the run **succeeds**. Observed:

```
$ claude -p "Run the bash command: echo DENIED_TEST. Use the Bash tool." \
    --disallowedTools "Bash" --output-format json
EXIT=0
subtype: "success"   is_error: false   terminal_reason: "completed"
permission_denials: []
result: "I don't have a Bash tool available in this session — my tool set here is
         Agent, Edit, Glob, Grep, Read, ... none of which execute arbitrary shell
         commands. I can't ..."
```

Exit 0, `is_error: false`, `permission_denials: []`, and the failure exists **only as
English prose in `result`**. This is precisely the case the settled constraint exists to
defend against. The exit code says "finished the work"; nothing was done.

**Consequence for the orchestrator: the exit code is a necessary but never sufficient
signal.** It reliably catches crashes, kills, and limits. It does not catch "the agent
politely declined." Only observing the repo — the branch, the commit, the PR, the diff —
distinguishes those. This is direct empirical support for the settled constraint.

I did not manage to populate `permission_denials` in any run (`--permission-mode dontAsk`
with `--tools "Bash,Read"` allowed `echo` and returned `permission_denials: []`). **UNVERIFIED**
what populates that array; do not depend on it as the denial signal.

### 3.2 The reliable "died partway" detector

Independent of exit code: **in `stream-json`, a run that completes always emits a final
`type: "result"` line.** Absence of that line, or `is_error: true` on it, means the run did
not finish. Under SIGTERM the CLI still managed to emit one (§4.2), but a hard `SIGKILL` or
a crashed pipe would not. **UNVERIFIED** for SIGKILL — not tested.

Documented corroboration for both halves:

> *"The `result` field holds the final text output and is only present on the `success`
> variant, so always check the subtype before reading it."*

> *"After a session crash, the final result is an `error_during_execution` whose cost fields
> may be zeroed and whose `stop_reason` is `null`, and the process exits after emitting it."*
> — <https://code.claude.com/docs/en/agent-sdk/agent-loop>

Documented `subtype` values (authoritative list, same page): `success`, `error_max_turns`,
`error_max_budget_usd`, `error_during_execution`, `error_max_structured_output_retries`.

### 3.3 `--max-turns` exists but is missing from `--help`

`claude --help` on 2.1.233 does **not** list `--max-turns` (`grep -c "max-turns"` → `0`),
but the docs do:

> *"`--max-turns` — Limit the number of agentic turns (print mode only). Exits with an error
> when the limit is reached."* — <https://code.claude.com/docs/en/cli-reference>

Empirically it works on 2.1.233:

```
$ claude -p "..." --max-turns 1 --output-format json
EXIT=1
subtype: "error_max_turns"   is_error: true
terminal_reason: "max_turns"  stop_reason: "tool_use"  num_turns: 2
result: None
```

`--max-budget-usd` **is** in `--help` and is documented. Both are viable crude caps — but
per §2, the orchestrator no longer needs a *crude* one.

---

## 4. Interruption vs kill-and-resume

**Both paths work. Both were verified end to end. Kill-and-resume is simpler; interrupt is
cheaper.**

### 4.1 Interruption — verified working

Driving `claude -p --input-format stream-json --output-format stream-json` from a Python
parent, I sent a long task, interrupted it mid-turn, and then sent a follow-up prompt on the
same process.

Sent on stdin:

```json
{"type":"control_request","request_id":"req-int-1","request":{"subtype":"interrupt"}}
```

Received on stdout:

```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "req-int-1",
    "response": { "still_queued": [] }
  }
}
```

The interrupted turn then terminated with its own `result`:

```json
{ "type": "result", "subtype": "error_during_execution", "is_error": true,
  "terminal_reason": "aborted_streaming", "stop_reason": null, "num_turns": 2,
  "session_id": "fe54878d-c433-4a16-b615-185fd8b0d696",
  "errors": ["[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null"],
  "result": null }
```

**The process stayed alive.** I then wrote a plain user message to the same stdin:

```json
{"type":"user","message":{"role":"user","content":"Stop counting. In one short sentence, say the highest number you reached."}}
```

and got a fresh `system/init` (same `session_id`) followed by:

```json
{ "type": "result", "subtype": "success", "is_error": false,
  "terminal_reason": "completed", "stop_reason": "end_turn", "num_turns": 1,
  "session_id": "fe54878d-c433-4a16-b615-185fd8b0d696",
  "result": "I reached 23 before stopping." }
```

Final process exit code `0`. **Context was fully retained across the interrupt.** So
"interrupt, then say `/handoff` and stop" is a real, working sequence today.

Documented corroboration:

> *"A streaming input session stays alive, and you can keep sending messages, except after a
> session crash, which emits a final `error_during_execution` result and exits the process."*
> — <https://code.claude.com/docs/en/agent-sdk/agent-loop>

### 4.2 Kill-and-resume — also verified working

Sent SIGTERM to a running `claude -p` 12 seconds in:

```
EXIT_AFTER_SIGTERM=143
```

It emitted 7 stream lines including a final `result`:

```json
{ "type": "result", "subtype": "error_during_execution", "is_error": true,
  "terminal_reason": "aborted_streaming", "stop_reason": null, "num_turns": 2,
  "session_id": "6d569daa-721c-49e5-9da9-99c2053aed77",
  "total_cost_usd": 0.000617, "duration_ms": 8703,
  "usage": { "input_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0, "output_tokens": 0, ... },
  "errors": ["[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null"] }
```

Note the zeroed `usage` — matching the documented crash caveat
(<https://code.claude.com/docs/en/agent-sdk/cost-tracking>, *"Recover totals after a session
crash"*). Recover the real numbers from the assistant messages that arrived earlier.

The transcript survived on disk:

```
/Users/coymcnew/.claude/projects/-private-tmp-claude-501-...-hdtest/6d569daa-721c-49e5-9da9-99c2053aed77.jsonl
```

And resumed cleanly **from a brand-new process**:

```
$ claude -p "In one short sentence: what task were you in the middle of, and what number did you reach?" \
    --resume "6d569daa-..." --output-format json
EXIT=0
session_id: 6d569daa-721c-49e5-9da9-99c2053aed77   terminal_reason: completed
result: "I was counting from 1 to 40 with a short sentence about each number,
         and I had reached 27 (three cubed) before being interrupted."
```

**The killed session retained its partial work.** This is the "unfinished, handoff exists,
resume from it" primitive, working, with no cooperation from the agent at all.

### 4.3 Which to build on

| | Interrupt in place | Kill and `--resume` |
|---|---|---|
| Requires holding the pipe | **yes** | no |
| Orchestrator complexity | NDJSON control protocol + reader thread | `subprocess.run` twice |
| Cost of the handoff | one extra turn on a warm session | full session reload (~33k cached prompt tokens re-read) |
| Latency | seconds | seconds + startup |
| Failure mode if it goes wrong | orphaned live process | none — process already gone |
| Works with one-shot `claude -p` | no | **yes** |
| Verified on 2.1.233 | ✅ | ✅ |

**Recommendation: build the v0.1 handoff on kill-and-`--resume`.** It is strictly simpler,
it composes with the "one tick = one observation, one action, exit" primitive, and it needs
no long-lived process. The tick that observes "context over budget" can `SIGTERM`, then the
*next* tick starts `claude -p "/handoff ..." --resume <sid>` as an ordinary action. The
state machine stays stateless between ticks, which is the whole point.

Interruption is the optimization to reach for later, if and when the orchestrator already
holds the pipe for `get_context_usage` polling. **Note the tension:** §2.1's polling
requires holding the pipe, and kill-and-resume does not. If you want live polling *and*
kill-and-resume, you hold the pipe anyway — at which point interrupt is nearly free. The
resolution is §2.2: derive context from the passive output stream, keep ticks one-shot, and
you need no pipe at all.

---

## 5. Session identity and persistence

- **Addressed by UUID.** Auto-assigned per run; `--session-id <uuid>` presets it, which lets
  the orchestrator name a session *before* launching. (`claude --help`: *"Use a specific
  session ID for the conversation (must be a valid UUID)"*.) Verified: I preset session IDs
  in every test.
- **Persisted** as newline-delimited JSON at
  `~/.claude/projects/<cwd-slug-with-slashes-as-dashes>/<session-uuid>.jsonl`. Observed for
  every session created during this research, including the SIGTERM'd one.
- **A separate live-process registry** at `~/.claude/sessions/<pid>.json`, e.g.
  `{"pid":10914,"sessionId":"8cf3af15-...","cwd":"/Users/coymcnew/code/my-team","startedAt":1786798376195,"version":"2.1.233","kind":"interactive","entrypoint":"cli","messagingSocketPath":"/tmp/cc-socks/10914.sock","status":"busy",...}`.
  This is for live IPC, not history. Do not treat it as durable.
- **Cross-process resumption: yes.** Verified repeatedly — a fresh `claude -p --resume <sid>`
  from a new shell picks up full context.
- **Cross-directory resumption: yes, on this version.**
  > *"You can run the two commands from different directories: Claude Code finds the session
  > by its ID in any project on this machine. Before v2.1.223, Claude Code looked for the ID
  > only in the current project directory and its git worktrees, so you had to run both
  > commands from the same directory."* — <https://code.claude.com/docs/en/headless>

  2.1.233 ≥ 2.1.223, so this holds here. **A target repo on an older CLI would break it** —
  worth a version floor check in the orchestrator.
- **Retention: no documented TTL.** `~/.claude/.last-cleanup` exists, implying some cleanup
  process. **UNVERIFIED** how long transcripts survive. Do not assume a session resumable
  weeks later; GitHub remains the durable state, as the design already assumes.
- **`--fork-session`** branches to a new ID instead of continuing the original (use with
  `--resume`/`--continue`). **`--continue`/`-c`** resumes the most recent conversation *in
  the current directory* — convenient interactively, ambiguous under concurrency. **The
  orchestrator should always use explicit `--session-id` / `--resume`, never `--continue`.**
- **`--no-session-persistence`** disables saving entirely (print mode only). Never use it —
  it forecloses the resume path.

Missing-session resumes fail loudly (exit 1, stderr `No conversation found with session ID:
<uuid>`), which is a clean, checkable signal.

---

## 6. Permissions for unattended runs

Documented modes (<https://code.claude.com/docs/en/cli-reference>): `default`, `acceptEdits`,
`plan`, `auto`, `dontAsk`, `bypassPermissions`, and `manual` as an alias for `default`.
`claude --help` on 2.1.233 lists the accepted values as
`"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"`.

Behaviour, quoted from <https://code.claude.com/docs/en/agent-sdk/agent-loop>:

| Mode | Quoted behaviour |
|---|---|
| `default` | *"Tools not covered by allow rules trigger your `canUseTool` callback; no callback means deny"* |
| `acceptEdits` | *"Auto-approves file edits and common filesystem commands (`mkdir`, `touch`, `mv`, `cp`, etc.); other Bash commands follow default rules"* |
| `plan` | *"Claude explores and plans without editing your source files"* |
| `dontAsk` | *"Never prompts. Tools pre-approved by permission rules run; everything else is denied... You want a fixed, explicit tool surface for a headless agent and prefer a hard deny over silent reliance on `canUseTool` being absent"* |
| `auto` | *"Uses a model classifier to approve or deny permission prompts"* |
| `bypassPermissions` | *"Runs all allowed tools without asking... Can't be used when running as root on Unix. Use only in isolated environments where the agent's actions can't affect systems you care about"* |

### What is safe to grant an agent working in a target repo

**Recommendation: `--permission-mode acceptEdits` plus an explicit `--allowedTools` list.
Do not use `--dangerously-skip-permissions` / `bypassPermissions`.**

Rationale, all sourced:

- `my-team` runs **on a developer's machine, from the root of a real target repo** — the
  explicit opposite of the isolated environment the docs reserve `bypassPermissions` for.
  `claude --help` for `--dangerously-skip-permissions` reads: *"Bypass all permission checks.
  Recommended only for sandboxes with no internet access."* That condition does not hold.
- `acceptEdits` is the documented recommendation for exactly this shape:
  > *"For autonomous agents on a dev machine, `acceptEdits` auto-approves file edits and
  > common filesystem commands (`mkdir`, `touch`, `mv`, `cp`, etc.) while still gating other
  > Bash commands behind allow rules. Reserve `bypassPermissions` for CI, containers, or
  > other isolated environments."* — <https://code.claude.com/docs/en/agent-sdk/agent-loop>
- Scope Bash narrowly with prefix rules. The syntax and its sharp edge are documented:
  > *"The trailing ` *` enables prefix matching, so `Bash(git diff *)` allows any command
  > starting with `git diff`. The space before `*` is important: without it,
  > `Bash(git diff*)` would also match `git diff-index`."* — <https://code.claude.com/docs/en/headless>

  So: `--allowedTools "Read,Edit,Write,Glob,Grep,Bash(git *),Bash(gh *),Bash(npm test*)"` —
  tuned per target repo.
- `dontAsk` is the stricter alternative and is explicitly pitched at headless agents. It is
  the right choice **if** you are willing to enumerate the full tool surface up front. It
  trades autonomy for auditability. Given that `my-team` wants the agent to actually finish
  work unattended, `acceptEdits` + allowlist is the better starting point; `dontAsk` is the
  hardening step.

### Two `-p`-specific hazards worth recording

> *"Without `--bare`, Claude Code runs the hooks in a project's `.claude/settings.json` even
> in a folder you've never trusted, because a `-p` session shows no workspace trust dialog.
> It also connects the servers in the project's `.mcp.json`, because a `-p` session can't
> show the per-server approval prompt either."* — <https://code.claude.com/docs/en/headless>

And from `claude --help` on `-p`: *"The workspace trust dialog is skipped when Claude is run
in non-interactive mode... Only use this in directories you trust. Settings files that fail
validation are silently ignored in this mode."*

Since v0.1's target is `mcnewcp/personal-assistant` — the user's own repo — this is
acceptable. It becomes a real concern the moment `my-team` is pointed at a repo the user
does not control.

**`--bare` is worth evaluating.** It skips hooks, plugins, MCP, auto-memory, and CLAUDE.md
discovery, and *"is the recommended mode for scripted and SDK calls, and will become the
default for `-p` in a future release."* But note it **also skips CLAUDE.md**, which
undercuts the design's "run from the target repo root so `claude -p` picks up project context
for free." **Do not use `--bare` for v0.1** — the free project context is the point. Revisit
if reproducibility ever outweighs it.

Also relevant to a "run from target repo root" design: without `--bare`, the run costs
~33k prompt tokens of system prompt, tool schemas, and skills before any work
(observed: `System prompt` 8,630 + `System tools` 19,441 + deferred 12,981 + `Skills` 1,816).
Against a 967k effective window that is 3%, so it is not a budget problem — but it is the
floor, and it is why a resumed session is never "empty."

---

## 7. Other useful observed facts

- **`--include-partial-messages`** adds `stream_event` messages with text deltas. Documented
  jq recipe: `jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'`
  (<https://code.claude.com/docs/en/headless>). Only needed for live UI; the tick model does
  not need it.
- **`system/api_retry`** events surface retryable API failures with `attempt`, `max_retries`,
  `retry_delay_ms`, `error_status`, and an `error` category from a documented enum including
  `rate_limit`, `overloaded`, `authentication_failed`, `billing_error`
  (<https://code.claude.com/docs/en/headless>). **This is how the orchestrator sees a usage
  limit being hit** — as `system/api_retry` with `error: "rate_limit"`, not as a distinct
  exit code. **UNVERIFIED** empirically; I did not hit a rate limit during testing.
- **`--json-schema`** forces the final result to conform to a JSON Schema, delivered in a
  `structured_output` field. Potentially very useful for making agent reports machine-checkable
  rather than prose — relevant to the judge/review steps.
- **stdin is capped at 10MB**; exceeding it exits non-zero (<https://code.claude.com/docs/en/headless>).
- **Background Bash tasks** are killed ~5s after the final result; background subagents are
  waited on, capped at 10 minutes by default via `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`
  (<https://code.claude.com/docs/en/headless>).
- A stray stderr warning appears when stdin is not redirected:
  `Warning: no stdin data received in 3s, proceeding without it.` **Always pass
  `< /dev/null`** for one-shot ticks to avoid a 3s stall on every invocation.
- `system/init` reports `plugin_errors` and `mcp_server_errors` keys (omitted when empty) —
  a clean CI-style gate for "the environment loaded correctly" before trusting a run
  (<https://code.claude.com/docs/en/headless>).

---

## 8. The SDK question: recommendation

**Package facts** (PyPI, 2026-08-15): `claude-agent-sdk` 0.2.139, `requires_python >=3.10`,
runtime deps `anyio>=4.0.0`, `mcp>=1.23.0,<2.0.0`, `sniffio`, `typing-extensions`. No Node.js
dependency. Platform-specific wheels of **88–101 MB** each:

```
claude_agent_sdk-0.2.139-py3-none-macosx_11_0_arm64.whl     88.0 MB
claude_agent_sdk-0.2.139-py3-none-macosx_11_0_x86_64.whl    93.0 MB
claude_agent_sdk-0.2.139-py3-none-manylinux_2_17_aarch64.whl 97.4 MB
claude_agent_sdk-0.2.139-py3-none-manylinux_2_17_x86_64.whl  98.4 MB
claude_agent_sdk-0.2.139-py3-none-win_amd64.whl            100.7 MB
```

That size is the bundled binary:

> *"Both the TypeScript and Python SDKs bundle a native Claude Code binary, so most installs
> need no separate Claude Code install."* — <https://code.claude.com/docs/en/agent-sdk/agent-loop>

**This is the decisive trade-off for `my-team`.** The SDK ships *its own* Claude Code. The
design says `my-team` is installed and run from the root of a target repo so that `gh` infers
the repo and `claude -p` picks up project context for free — which presumes **the user's own
`claude`**, with their auth, their settings, their plugins, their model choice, their
subscription. Adopting the SDK means either running a second, bundled Claude Code that may
drift from the one the user actually uses, or overriding the bundled path to point back at
theirs. **UNVERIFIED** whether the Python SDK exposes a supported CLI-path override
(the TS SDK historically had `pathToClaudeCodeExecutable`); I did not confirm a Python
equivalent.

### What the SDK genuinely adds

1. **Typed messages** — `SystemMessage`, `AssistantMessage`, `UserMessage`, `StreamEvent`,
   `ResultMessage` — instead of hand-parsed dicts.
2. **`can_use_tool` callback** — *"Tool permission callback, invoked only when the permission
   flow falls through to a prompt"* (<https://code.claude.com/docs/en/agent-sdk/python>). A
   genuine capability the CLI has no equivalent for: a Python function consulted per tool
   call, returning `PermissionResultAllow`/`PermissionResultDeny`. If `my-team` ever wants
   programmatic veto over individual tool calls, this is the only route.
3. **In-process hooks** as Python callbacks, including `PreCompact` with its
   `trigger: Literal["manual","auto"]`, plus `PreToolUse`, `PostToolUse`,
   `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStart`, `SubagentStop`,
   `Notification`, `PermissionRequest`
   (source: `types.py` in `anthropics/claude-agent-sdk-python`). Hooks *"run in your
   application process, not inside the agent's context window, so they don't consume
   context"* (<https://code.claude.com/docs/en/agent-sdk/agent-loop>).
4. **Framing you don't maintain** — the `control_request`/`control_response` request/response
   correlation, reader task, and error mapping are written for you.
5. **Typed exceptions**, from `_errors.py`:
   `ClaudeSDKError` → `CLIConnectionError` → `CLINotFoundError`; plus `ProcessError`
   (with `.exit_code` and `.stderr`), `CLIJSONDecodeError` (`.line`, `.original_error`),
   `MessageParseError` (`.data`). `ProcessError` **does** carry the exit code:
   ```python
   class ProcessError(ClaudeSDKError):
       def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None):
           self.exit_code = exit_code
           self.stderr = stderr
   ```
6. **Runtime control** beyond `interrupt()`: `set_permission_mode()`, `set_model()`,
   `rewind_files()`, `get_mcp_status()`, `stop_task()`, `get_context_usage()` — all visible
   as methods on `ClaudeSDKClient` and all implemented as control requests.

### What it does *not* add

**Context observability.** That was the question this ticket existed to settle, and the
answer is that `get_context_usage` is a CLI wire feature (§2.1, verified against the raw CLI
with no SDK present). Likewise `interrupt` (§4.1, verified). Session resume, usage telemetry,
permission modes, `max_turns`, and `max_budget_usd` are all CLI flags.

### Recommendation

**Use the CLI for v0.1. Structure the code so the substrate can be swapped.**

Cost of this choice, stated plainly:

- You hand-write the NDJSON framing and, if you want live polling, the
  `control_request` correlation. That is perhaps 100–200 lines with a reader thread — I wrote
  a working version of it during this research in well under that.
- You parse dicts, not dataclasses. Field drift between CLI versions is your problem. Pin a
  minimum version and assert on `claude_code_version` from `system/init`.
- You forgo `can_use_tool`. Mitigation: `--permission-mode acceptEdits` plus a tight
  `--allowedTools` allowlist covers the v0.1 threat model (§6).
- Undocumented-but-observed fields (`terminal_reason`, `contextWindow`, `autoCompactThreshold`)
  carry no compatibility promise. Depend on them defensively, with fallbacks.

What you get in exchange:

- **The user's own `claude`** — their auth, settings, model, CLAUDE.md, skills. This is the
  design's stated reason for running from the target repo root, and the SDK's bundled binary
  is in direct tension with it.
- **No ~90 MB wheel** in a "thin, locally-running CLI orchestrator."
- **Ticks stay one-shot.** `subprocess.run(["claude","-p",...,"--output-format","stream-json"], stdin=DEVNULL)`,
  read the NDJSON, exit. This matches "one observation, one action, exit" exactly, and it
  needs no long-lived process, no async runtime, and no `ClaudeSDKClient` lifecycle.
- **A clean upgrade path.** Because `get_context_usage` and `interrupt` are the *same wire
  protocol* the SDK uses, moving to the SDK later is a substrate swap behind one interface,
  not a redesign.

**Revisit the SDK when** you want per-tool-call programmatic veto (`can_use_tool`), or
in-process `PreCompact`/`PreToolUse` hooks, or when maintaining the framing starts costing
more than the bundled-binary tension. Isolate all `claude` invocation behind a single module
now so that day is a swap, not a rewrite.

---

## 9. Concrete guidance for the downstream tickets

1. **Always `--output-format stream-json --verbose`.** `json` throws away per-request usage
   and every intermediate event. Redirect `stdin` from `/dev/null` on one-shot ticks.
2. **Compute the budget passively.** Per `assistant` message, take
   `input + cache_creation + cache_read`; keep the running max; divide by
   `result.modelUsage[<model>].contextWindow` **less the ~33k autocompact buffer** (or use
   `maxTokens` from `get_context_usage` if you hold a pipe). Verified accurate in §2.3.
3. **Set the handoff trigger as a fraction of `autoCompactThreshold`** (observed `934000` for
   `claude-sonnet-5`), not of the raw window. Firing above it means compaction wins and the
   orchestrator handles a summary instead of driving the handoff.
4. **Branch on `is_error` before `subtype`** (§3.1, trap 1), and treat a missing final
   `result` line as "died partway" (§3.2).
5. **Never trust exit 0 as proof of work done** (§3.1, trap 2). Observe the repo. This is the
   settled constraint, and it is empirically justified.
6. **Preset `--session-id` yourself** so the tick knows the session name before the process
   exists. Persist it in GitHub — an issue comment, a PR body — since GitHub is the sole
   source of truth and `~/.claude/projects/` has no documented retention guarantee.
7. **Use `--resume <uuid>`, never `--continue`.** `--continue` is directory-scoped and
   ambiguous under concurrency.
8. **Handoff via kill-and-resume**: `SIGTERM` (→ exit 143, session persists), then next tick
   runs `claude -p "/handoff ..." --resume <sid>`. Verified end to end in §4.2.
9. **Feature-detect via `system/init.capabilities`** before relying on interrupt
   (`interrupt_receipt_v1`), rather than comparing version strings.
10. **Assert a CLI version floor of 2.1.223** if you rely on cross-directory resume (§5).

---

## Appendix: what was verified vs. inferred

**Verified empirically on 2.1.233** (commands and outputs above): full `stream-json` event
shapes; per-message `usage`; `modelUsage.contextWindow`; `get_context_usage` control request
against the raw CLI, before and after a turn; `interrupt` control request plus same-process
follow-up; SIGTERM → 143 with a final `result` and a resumable transcript; cross-process and
cross-directory `--resume`; on-disk session layout; `--max-turns` working despite absence
from `--help`; exit codes for bad flag / bad session / bad model / max-turns / success;
`/context` as a `-p` prompt; the `is_error`-vs-`subtype` trap; the blocked-tool exit-0 trap;
`json` returning only the result object; context-arithmetic cross-check against `/context`.

**Verified from primary docs** (URLs inline): documented `subtype` enum; SIGTERM 143;
`compact_boundary`; permission-mode semantics; `--max-turns` / `--max-budget-usd` /
`--autocompact`; slash commands in `-p`; cross-directory resume since v2.1.223; per-step
`output_tokens` being a placeholder and the dedup-by-ID requirement; `api_retry` schema;
`capabilities` feature detection; SDK bundling a native binary; `ClaudeAgentOptions` session
and permission fields; SDK exception types and `ProcessError.exit_code` (from SDK source).

**Explicitly UNVERIFIED** — do not build load-bearing logic on these without checking:
- The exhaustive value set of `terminal_reason` (no primary source for the field at all).
- Stability of `autoCompactThreshold`, `autocompactSource`, `messageBreakdown`, `apiUsage`,
  `skills`, `slashCommands`, `gridRows` — present in the observed payload but absent from the
  published `ContextUsageResponse` TypedDict.
- Behaviour under `SIGKILL` (only `SIGTERM` was tested).
- What actually populates `permission_denials` — it stayed `[]` in every denial I engineered.
- Retention/TTL of `~/.claude/projects/*.jsonl` transcripts.
- `system/compact_boundary` field contents (compaction was never triggered; it would need
  ~934k tokens).
- `system/api_retry` on a real rate limit (never hit one during testing).
- Whether the **Python** SDK exposes a supported override for the bundled CLI binary path.
