# The Codex non-interactive contract, and what it means for the harness seam

**Subject.** OpenAI **Codex CLI** — the `codex` command-line coding agent, open-sourced at
[github.com/openai/codex](https://github.com/openai/codex). Not the deprecated 2021 Codex
completion models. Its non-interactive entry point is `codex exec`.

**Findings reflect** repo HEAD `a95a6fe333c276623ef172f9f7825ac2790be184` (2026-08-15), which
corresponds to release line `rust-v0.148.0-alpha.19` (2026-08-15). Repo file paths below are
relative to that checkout.

**Claude Code column health warning.** Ticket #3 owns the Claude Code contract. Every Claude Code
claim in §1 was stated at the confidence available when this file was written and marked
**UNVERIFIED** where inferred rather than cited.

> ⚠️ **§1's Claude Code column has since been reconciled against #3's verified findings. Several
> cells were wrong, and one omission turned out to be a sixth irreconcilable divergence.**
> **Read [§4 Reconciliation](#4-reconciliation-against-3-verified) before using the table in §1** —
> §1 is left unedited as the original record.

---

## 1. Synthesis: the comparison

| Axis | Codex CLI (`codex exec`) | Claude Code (`claude -p`) |
|---|---|---|
| **Invocation** | `codex exec [OPTIONS] [PROMPT]`; `-` or piped stdin for prompt. Subcommands `resume`, `fork`, `review`. ([cli.rs:10-13](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L10-L13), [cli.rs:71-75](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L71-L75), [cli.rs:143-153](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L143-L153)) | `claude -p "<prompt>"` / `--print`. **UNVERIFIED** |
| **Refuses to run outside a repo** | Yes — hard exit unless `--skip-git-repo-check` or `--yolo`. ([lib.rs:798-803](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L798-L803)) | No such check. **UNVERIFIED** |
| **Exit codes** | **Binary: 0 or 1.** `exit(1)` iff a fatal error was seen; otherwise 0. ([lib.rs:1131-1134](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1131-L1134)) | 0 success / 1 error; no documented finer granularity. **UNVERIFIED** |
| **Structured output** | `--json` → JSONL on stdout. 8 typed top-level events, 9 item types. ([exec_events.rs:8-37](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L8-L37), [:105-133](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L105-L133)) | `--output-format json` / `stream-json`. **UNVERIFIED** |
| **Constrained final answer** | `--output-schema FILE` (JSON Schema) + `-o FILE`. ([cli.rs:42-44](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L42-L44), [cli.rs:62-69](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L62-L69)) | No first-class schema flag known. **UNVERIFIED** |
| **Usage telemetry** | Tokens only, on `turn.completed`: input / cached input / cache-write / output / reasoning. **No cost field.** ([exec_events.rs:49-73](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L49-L73)) | Usage **plus `total_cost_usd`** and duration. **UNVERIFIED** |
| **Session identity** | `thread_id` on the first `thread.started` event. ([exec_events.rs:39-43](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L39-L43)) | `session_id` in output. **UNVERIFIED** |
| **Session storage** | `$CODEX_HOME/sessions/rollout-<ts>-<thread_id>[_<rollout_id>].jsonl`. ([rollout/lib.rs:67-68](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/lib.rs#L67-L68), [rollout_file_name.rs:38-48](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/rollout_file_name.rs#L38-L48)) | `~/.claude/projects/<slug>/*.jsonl`. **UNVERIFIED** |
| **Resume** | `codex exec resume <ID>` / `--last` / `--all`. ([cli.rs:176-206](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L176-L206)) | `--resume <id>` / `--continue`. **UNVERIFIED** |
| **Fork a session** | **Yes** — `codex exec fork <ID>` branches into a new session. ([cli.rs:155-174](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L155-L174)) | No equivalent primitive. **UNVERIFIED** |
| **Opt out of persistence** | `--ephemeral`. ([cli.rs:30-32](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L30-L32)) | Unknown. **UNVERIFIED** |
| **Interruption** | **SIGINT only** → graceful `turn/interrupt`. No SIGTERM handler. ([lib.rs:941-947](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L941-L947), [lib.rs:1041-1056](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1041-L1056)) | Unknown signal handling. **UNVERIFIED** |
| **Turn cap / timeout** | **None.** No `--max-turns` or `--timeout` flag exists. (absent from [cli.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs) and [shared_options.rs](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs)) | `--max-turns` exists. **UNVERIFIED** |
| **Sandbox** | OS-enforced, 3 modes, default `read-only`. ([sandbox_mode_cli_arg.rs:12-18](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/sandbox_mode_cli_arg.rs#L12-L18), [config_types.rs:86-96](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/config_types.rs#L86-L96)) | Permission-mode based, tool-allowlist shaped. **UNVERIFIED** |
| **Approvals in headless** | Forced to `never` by default. ([lib.rs:406-411](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L406-L411)) | `--permission-mode` / `--dangerously-skip-permissions`. **UNVERIFIED** |
| **Project instructions** | `AGENTS.md`, concatenated project-root → cwd. **`CLAUDE.md` is never read at runtime.** ([agents_md.rs:1-16](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L1-L16), [agents_md.rs:36-39](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L36-L39)) | `CLAUDE.md`. **UNVERIFIED** |
| **Skills root** | `.agents/skills` (repo scope), cwd → repo root. ([host_roots.rs:23-24](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L23-L24), [:136-180](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L136-L180)) | `.claude/skills`. **UNVERIFIED** |
| **Skill format** | `SKILL.md`, YAML frontmatter, `name` + `description` required. Unknown keys ignored. ([parser.rs:7-32](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L7-L32)) | `SKILL.md`, same required fields. **UNVERIFIED** |
| **Official Python SDK** | `openai-codex` on PyPI, Python ≥3.10, JSON-RPC to an app-server. ([sdk/python/pyproject.toml](https://github.com/openai/codex/blob/main/sdk/python/pyproject.toml), [sdk/python/README.md](https://github.com/openai/codex/blob/main/sdk/python/README.md)) | `claude-agent-sdk`. **UNVERIFIED** |

### What the two genuinely have in common

Enough to build a real seam on — and more than expected, because the agent-skills format is now
a shared standard rather than a per-vendor invention.

1. **One-shot subprocess with a prompt argument, exiting when the work is done.** Both are
   `<binary> <flags> <prompt>` and both terminate. `tick` maps onto this natively for both.
2. **Progress on stderr, product on stdout.** Codex prints only the final agent message to stdout
   in human mode; `-o FILE` also captures it. This gives a harness-neutral "final message" concept.
3. **An opt-in JSONL event stream over stdout.** Both replace stdout with newline-delimited typed
   events under a flag. The *shape* differs; the *transport* is identical.
4. **A stable session identifier surfaced in the first events, and resume-by-id.** Both let a later
   invocation continue an earlier one, and both persist transcripts as JSONL on local disk.
5. **Token usage reported in-band at end of turn.**
6. **A tiered permission control with an explicit "I know what I'm doing" escape hatch**
   (`--dangerously-bypass-approvals-and-sandbox` / `--dangerously-skip-permissions`).
7. **Hierarchical, filesystem-discovered project instructions**, walking up from cwd, and a
   `SKILL.md` skill package with `name` + `description` frontmatter.
8. **An official first-party Python SDK** speaking a structured protocol, as an alternative to
   shelling out. Relevant: `my-team` is a Python CLI, so both harnesses offer a non-subprocess path.

### Where they diverge irreconcilably

These are the five that cannot be papered over. For each: abstract, or expose a capability check.

---

#### D1. Exit code cannot express "the agent finished, but the task failed" — **abstract it, but not via exit code**

Codex's exit status is strictly binary and reports *harness* health, not *task* outcome.
`exit(1)` fires only when `error_seen` is set, which happens on a non-retryable server error, or
a turn ending `Failed` or `Interrupted`
([lib.rs:1071-1088](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1071-L1088),
[lib.rs:1131-1134](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1131-L1134)).
A run where the model tries, fails, and says "I could not fix the test" exits **0**. Startup
failures — bad `-c` override, unreadable config, missing prompt, not-a-git-repo, a required MCP
server that won't initialize — also collapse to 1
([lib.rs:301-306](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L301-L306),
[lib.rs:798-803](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L798-L803),
[tests/suite/mcp_required_exit.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/mcp_required_exit.rs)).

Worse, **interrupted and failed are the same code**, so "the operator stopped it" is
indistinguishable from "it broke."

**Recommendation: abstract — and define the seam's outcome type independently of exit status.**
The seam should return a structured outcome (`Completed | Failed | Interrupted | HarnessError`)
derived from the *event stream*, using exit code only as a fallback when `--json` is off. Do not
let `tick` branch on `returncode`. Note this also means **`my-team` must not infer task success
from the process exiting 0** — GitHub state, not exit status, remains the source of truth, which is
consistent with the project's existing stance.

---

#### D2. Cost telemetry exists on one side only — **expose a capability check**

Codex's `Usage` is five token counters and nothing else — no dollar figure, no per-model split, no
duration ([exec_events.rs:60-73](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L60-L73)).
Claude Code reports `total_cost_usd` (**UNVERIFIED**). Codex *cannot* produce a cost without the
orchestrator holding its own price table, because a run may be authenticated against a ChatGPT
plan rather than an API key, where a per-run dollar cost is not even well-defined.

**Recommendation: expose a capability check.** Model usage as `tokens: TokenUsage` (always present)
plus `cost_usd: Optional[Decimal]` (present iff the harness reports it). Do not synthesise a cost
for Codex and do not force Claude Code's figure into a token-only shape. Any budget feature must
ask `harness.reports_cost` and degrade to token budgets otherwise.

---

#### D3. Sandboxing vs. permissioning are different security models — **expose a capability check**

This is the deepest divergence. Codex enforces at the **OS boundary**: `read-only` /
`workspace-write` / `danger-full-access`
([sandbox_mode_cli_arg.rs:12-18](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/sandbox_mode_cli_arg.rs#L12-L18)),
implemented by dedicated platform crates (`linux-sandbox`, `windows-sandbox-rs`, `bwrap`,
`sandboxing`), defaulting to `read-only`
([config_types.rs:86-96](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/config_types.rs#L86-L96)),
with writability widened by `--add-dir`
([shared_options.rs:70-72](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs#L70-L72)).
Approvals are a *separate* axis, forced to `never` under exec
([lib.rs:406-411](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L406-L411)).

Claude Code's model is a **tool-permission** model — which tools may run, with what arguments
(**UNVERIFIED**). "Which directories are writable by any process the agent spawns" and "which
tools the agent may call" are not translations of each other. A `workspace-write` sandbox has no
opinion about `WebFetch`; a tool allowlist has no opinion about a stray `rm` inside a shell script
the agent invoked.

**Recommendation: expose a capability check, with one narrow abstraction on top.**
Abstract only the coarse *intent* the orchestrator actually has — `ReadOnly` vs `EditWorkspace` vs
`Unrestricted` — and let each adapter render that into its own native mechanism. Everything finer
(specific writable roots, per-tool allowlists, network toggles) must be reachable only through a
harness-specific escape hatch and gated on a capability probe. Do **not** invent a unified
permission DSL; it would be a lossy translation in both directions.

---

#### D4. Interruption and turn-capping are not portable — **expose a capability check**

Codex handles **SIGINT only** ([lib.rs:941-947](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L941-L947)).
There is no SIGTERM handler, so a SIGTERM (what most process supervisors and `subprocess.terminate()`
send) kills it outright, mid-write. And Codex has **no `--max-turns` and no `--timeout`** at all,
whereas Claude Code has `--max-turns` (**UNVERIFIED**). Codex's only budget lever is the wall clock
and the orchestrator's own patience.

**Recommendation: abstract the *stop* action, capability-check the *budget*.**
`harness.stop()` is abstractable and should be — but its Codex implementation must send **SIGINT,
never SIGTERM**, then wait, then escalate. Turn/step budgets are not abstractable: expose
`harness.supports_turn_limit` and implement `my-team`-side wall-clock timeout as the portable
fallback. This is a real operational hazard, not a theoretical one: the naive
`Popen.terminate()` a Python orchestrator reaches for first is exactly the wrong signal for Codex.

---

#### D5. Event stream vocabulary is genuinely different — **abstract it, narrowly**

Codex emits `thread.started` / `turn.started` / `turn.completed` / `turn.failed` /
`item.{started,updated,completed}` / `error`, with items typed as `agent_message`, `reasoning`,
`command_execution`, `file_change`, `mcp_tool_call`, `collab_tool_call`, `web_search`, `todo_list`,
`error` ([exec_events.rs:8-37](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L8-L37),
[:105-133](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L105-L133)).
Claude Code's stream-json vocabulary is different in both naming and granularity (**UNVERIFIED**).
Codex additionally models a two-level thread/turn hierarchy that Claude Code does not obviously
mirror, and carries concepts (`collab_tool_call` for multi-agent spawning) with no counterpart.

**Recommendation: abstract, but keep the abstract vocabulary deliberately small.** For v0.1 `tick`
only needs: run started (with session id), final message, token usage, terminal status, and
optionally a coarse activity feed. Map to *that* and drop the rest. Resist modelling every item
type — a 1:1 union of both vocabularies is the "seam that is just one implementation with extra
indirection" failure mode. Keep the raw event accessible for escape-hatch consumers.

---

### The non-divergence worth calling out: project context needs no seam at all

`my-team` currently installs skills to `.agents/skills/` with `.claude/skills/` symlinks, and its
`CLAUDE.md` **is a symlink to `AGENTS.md`**. Both of those are, by coincidence or good instinct,
*exactly* what Codex reads natively:

- Codex's repo-scope skill root is literally `.agents/skills`
  ([host_roots.rs:23-24](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L23-L24)).
- Codex reads `AGENTS.md` and never reads `CLAUDE.md` at runtime — `CLAUDE.md` appears in the
  codebase only as a one-time *migration* source
  ([source/cla.rs:19-32](https://github.com/openai/codex/blob/main/codex-rs/external-agent-migration/src/source/cla.rs#L19-L32)).
- Codex's `SKILL.md` parser requires `name` + `description` and has **no `deny_unknown_fields`**,
  so Claude-Code-specific frontmatter keys such as `disable-model-invocation` are silently ignored
  rather than fatal ([parser.rs:7-32](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L7-L32)).
  The parser even carries a repair path written explicitly for third-party skills' prose
  descriptions ([parser.rs:56-60](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L56-L60)).

**So the skill payload `my-team` installs is fully legible to Codex today, unmodified.** The seam
should carry **no** project-context abstraction. The right design is to keep `.agents/skills/` and
`AGENTS.md` as the canonical artefacts and treat `.claude/skills/` and `CLAUDE.md` as
Claude-Code-specific *shims* — which is what the repo already does. Any future harness adapter's
context responsibility is "create the symlink farm my harness expects," not "translate content."

One caveat: Codex applies a precedence order across Repo / User / Admin / System skill scopes and
walks `.agents/skills` from cwd up to the repo root
([host_roots.rs:65-117](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L65-L117),
[:136-180](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L136-L180)),
so a user's `$HOME/.agents/skills` can collide by name with a repo skill. `my-team` should assume
its skill names are not globally unique.

### Seam shape implied by all of the above

- The seam's unit is a **run**, not a process: `run(prompt, context) -> RunOutcome`.
- `RunOutcome` carries `status`, `final_message`, `session_id`, `tokens`, `cost_usd: Optional`,
  and `raw_events`. It is derived from the event stream, **never** from the exit code.
- Capability probes, not silent no-ops, for: `reports_cost`, `supports_turn_limit`,
  `supports_fork`, `supports_os_sandbox`, `supports_output_schema`.
- Permission intent is coarse (`ReadOnly | EditWorkspace | Unrestricted`); anything finer is a
  harness-specific escape hatch.
- `stop()` is abstract; its Codex implementation is SIGINT-then-escalate.
- **No** project-context abstraction — that axis is already neutral.

---

## 2. Raw Codex detail

### 2.1 Invocation

```
codex exec [OPTIONS] [PROMPT]
codex exec [OPTIONS] <COMMAND> [ARGS]
```
([cli.rs:10-13](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L10-L13))

The prompt is a positional argument. If omitted, or given as `-`, it is read from stdin; if stdin
is piped *and* a prompt argument is present, stdin is appended as a `<stdin>` block
([cli.rs:71-75](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L71-L75)).
Piping the prompt in from a terminal with no argument and no pipe is a fatal error
([lib.rs:2026-2034](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L2026-L2034)).

Exec-specific flags ([cli.rs:14-76](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L14-L76)):

| Flag | Effect |
|---|---|
| `--json` (alias `--experimental-json`) | Print events to stdout as JSONL |
| `-o`, `--output-last-message FILE` | Write the final agent message to FILE (still printed to stdout) |
| `--output-schema FILE` | JSON Schema constraining the model's final response |
| `--ephemeral` | Do not persist session files to disk |
| `--skip-git-repo-check` | Allow running outside a Git repo |
| `--ignore-user-config` | Do not load `$CODEX_HOME/config.toml` (auth still uses `CODEX_HOME`) |
| `--ignore-rules` | Do not load user/project execpolicy `.rules` files |
| `--strict-config` | Error on unrecognised `config.toml` fields |
| `--color <always\|never\|auto>` | Colour control |

Shared flags ([shared_options.rs:10-73](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs#L10-L73)):
`-m/--model`, `-s/--sandbox`, `-C/--cd DIR`, `--add-dir DIR`, `-i/--image`, `-p/--profile`,
`--oss` / `--local-provider`, `--approve-for-me` (alias `--not-so-yolo`),
`--dangerously-bypass-approvals-and-sandbox` (alias `--yolo`), `--dangerously-bypass-hook-trust`.

Subcommands ([cli.rs:143-153](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L143-L153)):
`resume`, `fork`, `review`.

**A fully unattended run** is therefore, minimally:

```bash
codex exec --json --sandbox workspace-write -o /tmp/final.md "…prompt…"
```

Approvals are already forced off under exec (§2.5), so no approval flag is needed. Add
`--skip-git-repo-check` only if the target is not a repo — for `my-team` it always is.

Authentication reuses saved CLI auth; `CODEX_API_KEY=<key>` can be set per-invocation. OpenAI
explicitly warns against setting `OPENAI_API_KEY`/`CODEX_API_KEY` as job-level env vars in
workflows that check out repository-controlled code
([Non-interactive mode](https://developers.openai.com/codex/noninteractive)).

**`--full-auto` has been removed.** It does not appear anywhere in the current source tree
(`grep -rn 'full.auto' codex-rs docs` returns nothing at HEAD). Published docs still describe it as
deprecated-with-a-warning, so the docs lag the source here. Use `--sandbox workspace-write`.

### 2.2 Exit codes

Binary. The only success/failure decision is:

```rust
event_processor.print_final_output();
if error_seen {
    std::process::exit(1);
}
```
([lib.rs:1131-1134](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1131-L1134))

`error_seen` is set by exactly three things
([lib.rs:1071-1088](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1071-L1088),
[lib.rs:1922](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1922)):

1. A `ServerNotification::Error` for the primary thread/turn with `will_retry == false`.
2. A `TurnCompleted` whose status is `TurnStatus::Failed` **or** `TurnStatus::Interrupted`.
3. A failure inside `handle_server_request`.

The source comment is explicit about intent: *"Track whether a fatal error was reported by the
server so we can exit with a non-zero status for automation-friendly signaling"*
([lib.rs:1029-1031](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1029-L1031)).

Startup/validation failures also `exit(1)`, undifferentiated: `-c` override parse
([:301-306](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L301-L306)),
codex home ([:320-324](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L320-L324)),
execpolicy rules ([:456-465](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L456-L465)),
login restrictions ([:470-474](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L470-L474)),
`config.toml` load ([:639-651](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L639-L651)),
git-repo check ([:798-803](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L798-L803)),
output-schema read/parse ([:1927-1948](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1927-L1948)),
missing prompt ([:2026-2034](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L2026-L2034)).

Two integration tests pin the behaviour, both asserting `.code(1)`:
[server_error_exit.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/server_error_exit.rs)
(server reports `response.failed`) and
[mcp_required_exit.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/mcp_required_exit.rs)
(a `required = true` MCP server fails to initialise; also asserts the stderr message).

**There is no exit code meaning "the agent completed its turn but did not achieve the goal."**

### 2.3 Structured output and usage telemetry

Without `--json`: progress streams to **stderr**, and only the final agent message goes to
**stdout** ([Non-interactive mode](https://developers.openai.com/codex/noninteractive)), which is
what makes `codex exec … | tee` work.

With `--json`, stdout becomes JSONL. The wire type is `ThreadEvent`, tagged on `type`
([exec_events.rs:8-37](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L8-L37)):

| Event | Payload |
|---|---|
| `thread.started` | `thread_id` — "Can be used to resume the thread later" |
| `turn.started` | (empty) |
| `turn.completed` | `usage` |
| `turn.failed` | `error.message` |
| `item.started` / `item.updated` / `item.completed` | `item` |
| `error` | `message` (unrecoverable, emitted directly by the stream) |

`ThreadItemDetails` is tagged on `type` in `snake_case`
([exec_events.rs:105-133](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L105-L133)):
`agent_message`, `reasoning`, `command_execution`, `file_change`, `mcp_tool_call`,
`collab_tool_call`, `web_search`, `todo_list`, `error`.

Useful item detail for an orchestrator:

- `command_execution` carries `command`, `aggregated_output`, `exit_code: Option<i32>`, and
  `status: in_progress|completed|failed|declined`
  ([exec_events.rs:149-166](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L149-L166)).
  Note `declined` — that is how a sandbox/approval refusal surfaces.
- `file_change` carries `changes: [{path, kind: add|delete|update}]` and a status, emitted only on
  completion ([exec_events.rs:168-198](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L168-L198)).
- `agent_message.text` is "either a natural-language response or a JSON string when structured
  output is requested" ([exec_events.rs:108-110](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L108-L110)).

The types are exported for other languages via `ts_rs` (`#[derive(… TS)]` throughout
`exec_events.rs`), so the event schema is intended as a public contract, not an internal detail.

**Usage telemetry** arrives once per turn, on `turn.completed`
([exec_events.rs:49-73](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L49-L73)):

```rust
pub struct Usage {
    pub input_tokens: i64,
    pub cached_input_tokens: i64,
    pub cache_write_input_tokens: i64,
    pub output_tokens: i64,
    pub reasoning_output_tokens: i64,
}
```

No cost, no model name, no duration, no rate-limit headroom.

**Structured final answers.** `--output-schema FILE` supplies a JSON Schema for the model's final
response; combined with `-o FILE` it yields a machine-readable artefact
([Non-interactive mode](https://developers.openai.com/codex/noninteractive)). The schema file is
read and JSON-parsed at startup, and either failure exits 1
([lib.rs:1927-1948](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1927-L1948)).
This is a genuinely useful lever for `my-team`: a `tick` could demand its report back in a fixed
shape rather than parsing prose.

### 2.4 Session identity, resume, interruption

**Identity.** The first event of every run is `thread.started` with a `thread_id`
([exec_events.rs:39-43](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L39-L43)).
Codex's own docs show it as a UUID, e.g. `0199a213-81c0-7800-8aa1-bbab2a035a53`.

**Persistence.** Sessions are written as rollout JSONL under `$CODEX_HOME`:
`SESSIONS_SUBDIR = "sessions"`, `ARCHIVED_SESSIONS_SUBDIR = "archived_sessions"`
([rollout/lib.rs:67-68](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/lib.rs#L67-L68)).
Filenames are `rollout-<19-char-timestamp>-<thread_id>[_<rollout_id>].jsonl`; ordinary files encode
one id that is both thread and rollout id, and reverted threads append a distinct rollout id after
a stable thread id
([rollout_file_name.rs:10-48](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/rollout_file_name.rs#L10-L48)).
Files may be transparently compressed to `.jsonl.zst`
([compression.rs:41-64](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/compression.rs#L41-L64)) —
so anything reading them directly must handle both. `--ephemeral` skips persistence entirely
([cli.rs:30-32](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L30-L32)), which
necessarily forfeits resume.

**Resume.** `codex exec resume <SESSION_ID> [PROMPT]`, `--last` for the most recent, `--all` to
disable cwd filtering, `-i/--image` to attach images
([cli.rs:176-206](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L176-L206)).
Session id may be a UUID or a thread name; UUIDs take precedence if the string parses as one
([cli.rs:180-181](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L180-L181)).
Note the ergonomic wrinkle: with `--last` and no explicit prompt, the positional is reinterpreted
as the prompt rather than a session id
([cli.rs:227-243](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L227-L243)).

**Fork.** `codex exec fork <SESSION_ID> [PROMPT]` branches a previous session into a new one
([cli.rs:155-174](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L155-L174)).
This is a real primitive with no Claude Code counterpart I am aware of (**UNVERIFIED**), and is
interesting for `my-team`: it permits speculative ticks from a shared prefix.

**Interruption.** A single spawned task listens for `tokio::signal::ctrl_c()` and pushes to an
interrupt channel ([lib.rs:941-947](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L941-L947)):

```rust
let (interrupt_tx, mut interrupt_rx) = mpsc::unbounded_channel::<()>();
tokio::spawn(async move {
    if tokio::signal::ctrl_c().await.is_ok() {
        tracing::debug!("Keyboard interrupt");
        let _ = interrupt_tx.send(());
    }
});
```

The main loop `select!`s on that channel and issues a `turn/interrupt` request
([lib.rs:1036-1057](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1036-L1057)).
The resulting turn status is `Interrupted`, which sets `error_seen` and exits 1
([lib.rs:1078-1088](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L1078-L1088)).

**There is no SIGTERM handler.** Only `ctrl_c` is registered. On Unix, Tokio's `ctrl_c` is SIGINT.
A SIGTERM therefore takes the default disposition and terminates the process without the graceful
interrupt path. Any Python orchestrator must send `signal.SIGINT`, not `Popen.terminate()`.

**No turn or time budget.** Neither `codex exec`'s own flags
([cli.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs)) nor the shared
options ([shared_options.rs](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs))
define `--max-turns`, `--max-steps`, or `--timeout`.

### 2.5 Permissions and sandbox

Two orthogonal axes.

**Sandbox** — `-s`/`--sandbox`, three variants
([sandbox_mode_cli_arg.rs:12-18](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/sandbox_mode_cli_arg.rs#L12-L18)):
`read-only`, `workspace-write`, `danger-full-access`. `ReadOnly` is `#[default]`
([config_types.rs:86-96](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/config_types.rs#L86-L96)),
matching the docs' "by default, execution runs in read-only mode." The CLI arg deliberately mirrors
`SandboxPolicy` without its associated data; finer tuning goes through `-c` overrides or
`config.toml` ([sandbox_mode_cli_arg.rs:1-8](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/sandbox_mode_cli_arg.rs#L1-L8)).
`--add-dir` adds writable roots alongside the primary workspace
([shared_options.rs:70-72](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs#L70-L72)).

Enforcement is OS-native, per dedicated workspace crates: `linux-sandbox`, `windows-sandbox-rs`,
`bwrap`, `sandboxing`. Per OpenAI's docs, macOS uses Seatbelt, Linux/WSL2 uses bubblewrap with
Landlock/seccomp, and Windows uses a native sandbox
([Sandboxing](https://developers.openai.com/codex/sandboxing)). `workspace-write` restricts network
by default (**UNVERIFIED** — stated in docs prose, I did not locate the enforcing constant).

**Approvals** — `untrusted` / `on-request` / `never`
([approval_mode_cli_arg.rs:9-21](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/approval_mode_cli_arg.rs#L9-L21)).
Under `never`, "Execution failures are immediately returned to the model."

**Exec forces `never`.** In `ConfigOverrides`:

```rust
// Default to never ask for approvals in headless mode. Rebuild below if
// the fully resolved reviewer is AutoReview.
approval_policy: Some(AskForApproval::Never),
```
([lib.rs:406-411](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L406-L411))

The one exception is the auto-review path: if the resolved `approvals_reviewer` is `AutoReview`, the
headless override is dropped and the configured policy is preserved
([lib.rs:590-612](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L590-L612)),
which the integration tests pin
([tests/suite/approval_policy.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/approval_policy.rs)).
`--approve-for-me` sets `approvals_reviewer="auto_review"`, `approval_policy="on-request"`,
`sandbox_mode="workspace-write"` in one shot
([shared_options.rs:76-89](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs#L76-L89)) —
i.e. an agent reviews the escalations instead of a human. For `my-team` this is an interesting
middle setting, not just a binary safe/unsafe choice.

`--dangerously-bypass-approvals-and-sandbox` (alias `--yolo`) forces `DangerFullAccess`
([lib.rs:294-298](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L294-L298))
**and** implicitly skips the git-repo check, on the reasoning that the user is in an externally
sandboxed environment ([lib.rs:796-803](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L796-L803)).

There is also an **execpolicy** layer of `.rules` files, user- and project-scoped, bypassable with
`--ignore-rules` ([cli.rs:38-40](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs#L38-L40));
a failure to load them is fatal
([lib.rs:456-465](https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs#L456-L465)).
See [docs/execpolicy.md](https://github.com/openai/codex/blob/main/docs/execpolicy.md).

### 2.6 Project context discovery

**AGENTS.md.** The module doc states the algorithm precisely
([agents_md.rs:1-16](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L1-L16)):

1. Walk upwards from cwd until a `project_root_markers` entry is found; the default marker list is
   `.git`. If no marker is found, only cwd is considered; an empty marker list disables traversal.
2. Concatenate every `AGENTS.md` from project root down to cwd inclusive, in that order.
3. Never walk past the project root.

Constants: `DEFAULT_AGENTS_MD_FILENAME = "AGENTS.md"`, `LOCAL_AGENTS_MD_FILENAME =
"AGENTS.override.md"`
([agents_md.rs:36-39](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L36-L39)),
joined to user-level instructions with the separator `"\n\n--- project-doc ---\n\n"`
([agents_md.rs:41-43](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L41-L43)).
Additional filenames can be configured via `project_doc_fallback_filenames`
([agents_md.rs:4](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs#L4)) — which is
the only supported way to make Codex read a differently-named instruction file.

**CLAUDE.md is not read at runtime.** The only occurrence in the source is the external-agent
*migration* module, where it is a one-time import source alongside `.claude/` and `settings.json`,
complete with a rewrite profile that strips "claude code"/"claude" references
([source/cla.rs:19-32](https://github.com/openai/codex/blob/main/codex-rs/external-agent-migration/src/source/cla.rs#L19-L32)).

**Skills.** Repo-scope discovery joins two constants
([host_roots.rs:23-24](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L23-L24)):

```rust
const AGENTS_DIR_NAME: &str = ".agents";
const SKILLS_DIR_NAME: &str = "skills";
```

`repo_agents_skill_roots` probes `<dir>/.agents/skills` for every directory between the project
root and cwd, concurrently
([host_roots.rs:136-180](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L136-L180)),
and the nearest root wins
([host_roots_tests.rs:401-410](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots_tests.rs#L401-L410)).
Scopes, in precedence order
([host_roots.rs:65-117](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs#L65-L117)):

| Scope | Path |
|---|---|
| Repo | `.agents/skills`, cwd → repo root |
| User | `$HOME/.agents/skills` (plus deprecated `$CODEX_HOME/skills`, kept for back-compat) |
| Admin | `/etc/codex/skills` |
| System | bundled with Codex (e.g. `skill-creator`, `skill-installer`) |

Codex also loads skills from plugins, whose default skills dir is `skills/` under the plugin root
([core-plugins/loader.rs:64](https://github.com/openai/codex/blob/main/codex-rs/core-plugins/src/loader.rs#L64),
[:1081-1083](https://github.com/openai/codex/blob/main/codex-rs/core-plugins/src/loader.rs#L1081-L1083)).

**SKILL.md format** ([parser.rs:7-32](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L7-L32)):
YAML frontmatter delimited by `---`, with `name` and `description` both required after validation
(missing either is `SkillParseError::MissingField`), `model` optional, and
`metadata.short-description` optional. `MAX_NAME_LEN = 64`
([parser.rs:5](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L5)).
The struct carries **no `#[serde(deny_unknown_fields)]`** — verified by grep across
`codex-rs/skills/src/`, which returns nothing — so unrecognised keys are dropped silently.
There is also a deliberate repair path for third-party skills whose descriptions contain colons
([parser.rs:56-60](https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs#L56-L60)),
evidence that ingesting non-OpenAI-authored skills is an explicit design goal. OpenAI describes
skills as building on "the open agent skills standard"
([Skills](https://developers.openai.com/codex/skills)).

Skills are invoked explicitly with `$` in Codex, or implicitly by description matching
([Skills](https://developers.openai.com/codex/skills)).

**Applied to `my-team`.** The repo's payload lands exactly on Codex's discovery paths:
`.agents/skills/<name>/SKILL.md` with `name` + `description` frontmatter, and `AGENTS.md` at the
root with `CLAUDE.md` as a symlink to it. Codex would pick all of it up unmodified. Claude-Code-only
frontmatter in the vendored skills — e.g. `disable-model-invocation: true` in
`.agents/skills/wayfinder/SKILL.md` — is ignored rather than rejected.

### 2.7 The other programmatic surface: SDKs

`codex exec` is not the only integration point. The repo ships first-party SDKs under `sdk/`
(`python`, `typescript`, `python-runtime`). The Python package is `openai-codex`, requires Python
≥3.10, and vendors a pinned CLI binary via `openai-codex-cli-bin`
([sdk/python/pyproject.toml](https://github.com/openai/codex/blob/main/sdk/python/pyproject.toml)).
Its surface is thread/turn oriented rather than process oriented
([sdk/python/README.md](https://github.com/openai/codex/blob/main/sdk/python/README.md)):

```python
from openai_codex import Codex

with Codex() as codex:
    thread = codex.thread_start()
    result = thread.run("Explain this repository in three bullets.")
    print(result.final_response)
```

`thread.run(...)` returns a `TurnResult` carrying the final response, collected items, and token
usage — i.e. the same information as the JSONL stream, already parsed, with no exit code involved
at all.

For `my-team`, a Python orchestrator, this is worth weighing against subprocess-plus-JSONL: it
sidesteps D1 (exit codes) and D5 (event parsing) entirely for the Codex adapter, at the cost of a
dependency and a pinned CLI binary, and of the two adapters no longer being structurally
symmetrical. **Recommendation: keep v0.1 on subprocess for both** — symmetry is what stress-tests
the seam — but record the SDK as the escape hatch if event parsing becomes a maintenance burden.

---

## 3. Confidence and gaps

Verified against source at HEAD: invocation and flags, exit-code semantics, JSONL event and item
schema, usage fields, session storage layout, resume/fork, SIGINT-only interruption, absence of
turn/time limits, sandbox and approval enums and their exec defaults, AGENTS.md discovery, skills
discovery roots and frontmatter parsing.

Marked **UNVERIFIED** and needing correction against ticket #3: the entire Claude Code column.

Other gaps:

- **Network policy per sandbox mode** — asserted in docs prose; I did not locate the enforcing
  constant in `codex-rs/sandboxing`. **UNVERIFIED**
- **`--full-auto`** — absent from source at HEAD but still described in published docs. Treat the
  source as authoritative and avoid the flag. **UNVERIFIED** which release removed it.
- **Whether `resume` re-emits `thread.started` with the original `thread_id`** — strongly implied by
  the "can be used to resume the thread later" contract but not directly confirmed in a test I read.
  **UNVERIFIED**
- **Rate-limit / quota signals** — not present in the exec event stream. If `my-team` needs
  backpressure, it will have to infer it from `turn.failed` messages. **UNVERIFIED** whether a
  structured signal exists elsewhere in the app-server protocol.
- Version is a fast-moving alpha line (`0.148.0-alpha.19`, several releases per day). Re-verify
  flags before pinning behaviour.

---

## 4. Reconciliation against #3 (verified)

*Added while resolving the tickets, once [#3 Claude Code headless contract](https://github.com/mcnewcp/my-team/issues/3)
returned. Claude Code facts below are verified against `claude 2.1.233` with observed JSON; the
full evidence is in `docs/research/claude-code-headless-contract.md`. §1 above is left unedited as
the original record — **this section supersedes its Claude Code column.***

### 4.1 Corrections to §1

| Axis | §1 said | Verified truth |
|---|---|---|
| **Invocation** | `claude -p` / `--print`. UNVERIFIED | **Confirmed.** Plus `--input-format stream-json`, which opens a **bidirectional control channel** — no Codex equivalent was found. |
| **Exit codes** | 0 / 1, "no finer granularity". UNVERIFIED | **Wrong — there are three:** 0 success, 1 error, **143 on SIGTERM** (documented). Two traps: `subtype:"success"` can co-occur with `is_error:true`, so **branch on `is_error` first**; and a *blocked tool* yields **exit 0, `is_error:false`, `permission_denials:[]`**, with the failure present only as English prose. |
| **Usage telemetry** | "Usage plus `total_cost_usd` and duration". UNVERIFIED | Usage confirmed; **`total_cost_usd` remains UNVERIFIED** — #3 did not confirm it, so **D2's premise is not yet established.** See §4.2 for what #3 *did* find. |
| **Session identity** | `session_id` in output. UNVERIFIED | Confirmed, **and presettable via `--session-id`**. Codex assigns `thread_id` and you cannot choose it — an orchestration advantage for Claude Code. |
| **Session storage** | `~/.claude/projects/<slug>/*.jsonl`. UNVERIFIED | Confirmed as `~/.claude/projects/<slug>/<uuid>.jsonl`. **Cross-process *and* cross-directory resume verified** (requires ≥ 2.1.223). |
| **Resume** | `--resume <id>` / `--continue`. UNVERIFIED | Confirmed — but **use `--resume`, never `--continue`.** |
| **Interruption** | "Unknown signal handling". UNVERIFIED | **Both paths verified:** a graceful in-band interrupt via control request (process survives, context retained), *and* SIGTERM → 143. **Codex is SIGINT-only with no SIGTERM handler** — so the seam's "stop" verb maps to a different signal per harness. #3 recommends **kill-and-resume** for v0.1, which keeps ticks one-shot. |
| **Approvals in headless** | `--permission-mode` / `--dangerously-skip-permissions`. UNVERIFIED | Confirmed, with a recommendation: **`acceptEdits` plus a tight `--allowedTools` allowlist.** Not `--dangerously-skip-permissions` — the docs reserve it for sandboxes, and a target repo is not one. |
| **Skills root** | `.claude/skills`. UNVERIFIED | Confirmed — **and per [#6](https://github.com/mcnewcp/my-team/issues/6), `.claude/skills/` entries may be symlinks, while `.agents/skills` is literally Codex's own repo skill root.** One tree serves both harnesses. **This is less of a divergence than §1 implies.** |

### 4.2 D6 — live context observability: Claude Code only

**A sixth irreconcilable divergence, and §1 missed it entirely** because the Claude Code side was
not yet known. It is the one the whole context-budget design rests on.

Claude Code exposes **mid-session, side-effect-free context-window occupancy** via a
`get_context_usage` control request over `--input-format stream-json`, returning `totalTokens`,
`maxTokens`, `percentage`, and — critically — `autoCompactThreshold`, the point at which the
harness compacts on its own. The same number is also derivable passively from `usage` on every
`assistant` event. **Neither path needs the SDK.**

Codex has nothing equivalent: its `Usage` arrives only at `turn.completed`
([exec_events.rs:49-73](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs#L49-L73)) —
that is *after* the turn, which is too late to act on. There is no mid-turn query and no
compaction-threshold signal.

**Recommendation: expose a capability check, do not abstract.** Model it as
`harness.can_observe_context_budget`. Where true, the orchestrator holds the budget itself and
triggers `/handoff` **below `autoCompactThreshold`** — otherwise the harness compacts first and the
trigger never fires. Where false, fall back to the crude cap the map already accepts for v0.1
(turn count or wall-clock), and note that Codex has **no `--max-turns` or `--timeout` flag** (§1),
so even that fallback must be counted by the orchestrator rather than delegated.

This settles the map's open question in favour of **the orchestrator holding the budget; the agent
does not self-monitor.**

### 4.3 What this does to §1's recommendations

- **D1 (exit codes) — strengthened.** §1 argued the seam must derive its outcome from the event
  stream, not `returncode`. Claude Code's blocked-tool-exits-0 trap is *independent* empirical
  support from the other harness: **both** harnesses can exit 0 on a failed task. The map's
  "verify by observation" constraint is now evidenced on both sides, not assumed.
- **D2 (cost telemetry) — premise unconfirmed.** The asymmetry may not exist. Keep
  `cost_usd: Optional[Decimal]` as a shape, since it costs nothing if cost is absent everywhere,
  but **do not build a budget feature on it** — build on D6's token/context numbers instead.
- **Skills (§1 rows 37–38) — softer than stated.** #6 establishes one `.agents/skills/` tree
  symlinked into `.claude/skills/` serves both harnesses with no translation layer.
- **Interruption — now a genuine per-harness branch**, not an unknown. The seam needs a `stop`
  verb whose implementation differs (SIGTERM vs SIGINT), which is an abstraction, not a
  capability check.
