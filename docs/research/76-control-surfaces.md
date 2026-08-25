# Current Codex and Claude control surfaces for autonomous context chaining

Research for [What do the current Codex and Claude control surfaces actually promise?](https://github.com/mcnewcp/my-team/issues/76), captured 2026-08-24.

## Answer

Both Harnesses expose enough control surface to attempt the planned chain: keep one session alive, observe context usage, interrupt a running turn, wait for its terminal event, run a same-session Handoff turn, then seed a fresh session. Neither has a first-class Handoff primitive; a Handoff is an ordinary prompt and file-writing turn whose artifact is then supplied to a newly created session.

The sharp edges differ:

- Codex's installed stable v2 schema has the necessary thread, turn, skill, usage, and interruption methods. It does **not** define what `tokenUsage.last` means strongly enough to equate it with current context occupancy, and background-terminal cleanup is available only in the experimental schema.
- Claude's current Agent SDK packages expose a direct current-context query (`get_context_usage()` / `getContextUsage()`), along with a documented interrupt-and-drain sequence. The current HTML Python reference has not caught up with the context-query method in the published package, so live mid-turn behavior still needs observation.
- The Claude Agent SDK documentation tells integrators to use an API key or supported cloud-provider credentials and says claude.ai login/rate limits may not be offered to third parties without prior approval. It does not promise that the map's required subscription-auth path is supported. No credential was set or used during this research. [Claude Agent SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart)

## Version baseline

### Codex artifact

The installed executable reported `codex-cli 0.149.0` and resolved to `/Users/coymcnew/.codex/packages/standalone/current/bin/codex`. Its SHA-256 was `f4a74117b8142cda581c95ff753abf4508b5636d89682c1ed77e4a9249af8963`.

I generated two schema bundles directly from that binary:

```text
codex app-server generate-json-schema --out /tmp/codex-schema-0.149.0
codex app-server generate-json-schema --experimental --out /tmp/codex-schema-0.149.0-exp
```

The stable `codex_app_server_protocol.v2.schemas.json` SHA-256 was `9b3de71a5a2ffc980b792a18aa8f8dec3f85f48829560222a0264fe494b679a9`; the experimental bundle SHA-256 was `6f76cce25156d405f1da54f205751e38f7b9eb42246ac0742b9958dd60275350`. The schema title is `CodexAppServerProtocolV2`; it carries no independent semantic version, so its exact version is the generating CLI version plus digest. OpenAI explicitly says generated artifacts are specific to the CLI version that produced them. [Official Codex App Server documentation](https://developers.openai.com/codex/app-server)

The stable bundle is authoritative below. Experimental-only methods are called out separately. This distinction matters because app-server itself is documented as experimental and unsupported for production, and `experimentalApi` gates an additional set of methods and fields. [Official Codex App Server documentation](https://developers.openai.com/codex/app-server)

### Claude artifacts

- Installed standalone Claude Code: `2.1.243` at `/Users/coymcnew/.local/share/claude/versions/2.1.243`.
- Current Python package: `claude-agent-sdk 0.2.144`, published 2026-08-21. The official macOS arm64 wheel has SHA-256 `a69da08f88518695630cf88155ad5888e9c2f322b05ef4e96bb4e5460b815544` and its `_cli_version.py` pins bundled Claude Code `2.1.239`. [Official PyPI metadata](https://pypi.org/pypi/claude-agent-sdk/json), [exact `0.2.144` source artifact](https://files.pythonhosted.org/packages/73/e0/00d873adf589a4ba7899bc7e6ab5306fa55c8e9f4a2313a6f5fef95a473b/claude_agent_sdk-0.2.144.tar.gz)
- Current TypeScript package: `@anthropic-ai/claude-agent-sdk 0.3.243`; its live registry package metadata pins Claude Code `2.1.243`. [Official npm registry metadata](https://registry.npmjs.org/%40anthropic-ai%2Fclaude-agent-sdk/latest), [exact `0.3.243` package artifact](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.243.tgz)
- The official Agent SDK pages were fetched 2026-08-24. They publish no page or documentation-set version. The note therefore dates every documentation claim and ties package-level claims to the versions above. [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)

The next prototype ticket specifies Python, so the detailed Claude surface below uses Python `0.2.144`. Letting that wheel choose its default binary tests Claude Code `2.1.239`, not the separately installed `2.1.243`; using `ClaudeAgentOptions(cli_path=...)` would intentionally change that baseline. The SDK docs confirm that platform wheels bundle a native CLI and allow a separately installed executable when needed. [Claude Agent SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart)

## Smallest control surfaces

| Need | Codex 0.149.0 | Claude Python SDK 0.2.144 | What is actually established |
| --- | --- | --- | --- |
| Persistent session | `thread/start` creates a thread; subsequent `turn/start {threadId, input}` calls add turns. `thread/resume {threadId}` reloads a persisted thread. | Keep one `ClaudeSDKClient` connected; each `client.query()` continues its session and `receive_response()` drains that query. Across processes, capture `ResultMessage.session_id` and pass `ClaudeAgentOptions(resume=id)`. | Both represent conversation persistence, not a guarantee about live filesystem/process state. Claude explicitly says sessions persist conversation, not filesystem. [Claude sessions](https://code.claude.com/docs/en/agent-sdk/sessions) |
| Skill discovery and invocation | `skills/list` discovers skills. A `turn/start` input can include text containing `$<name>` plus a stable `{type:"skill", name, path}` input item; the item is the recommended deterministic instruction injection. | Filesystem settings discover `.claude/skills/<name>/SKILL.md`. `ClaudeAgentOptions(skills=[...])` scopes enabled skills; a prompt containing `/<name>` directly dispatches one. Default setting sources load user, project, and local sources. | These are the real skill-resolution paths. Whether the specific symlinked `mt-review` and `mt-judge` payloads resolve, receive the expected permissions, and finish correctly remains empirical. [Codex App Server skills](https://developers.openai.com/codex/app-server), [Claude Agent SDK skills](https://code.claude.com/docs/en/agent-sdk/skills) |
| Live context usage | Subscribe to `thread/tokenUsage/updated`. Its payload requires `threadId`, `turnId`, and `tokenUsage`; `tokenUsage` contains `last`, `total`, and nullable `modelContextWindow`. Both usage breakdowns contain `inputTokens`, `cachedInputTokens`, `outputTokens`, `reasoningOutputTokens`, and `totalTokens` (plus a defaulted cache-write field). | Published package API `await client.get_context_usage()` returns `totalTokens`, effective `maxTokens`, raw `rawMaxTokens`, `percentage`, `model`, `isAutoCompactEnabled`, optional `autoCompactThreshold`, and category/detail breakdowns. The TypeScript package has `getContextUsage()`. | Codex's schema gives field shapes but no semantic description that makes `last` current occupancy or promises notification cadence. Claude's package calls `totalTokens` the tokens currently in the context window, but the current HTML Python reference does not list this method. Both live paths require the M1 experiment. [Codex generated schema](#codex-artifact), [Python `0.2.144` artifact](https://files.pythonhosted.org/packages/73/e0/00d873adf589a4ba7899bc7e6ab5306fa55c8e9f4a2313a6f5fef95a473b/claude_agent_sdk-0.2.144.tar.gz), [TypeScript `0.3.243` artifact](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.243.tgz) |
| Usage fallback | A persisted rollout may be inspected only as a fallback; no stable schema promise makes its on-disk layout an API. | `AssistantMessage.usage` supplies per-step request usage; total request input is `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. `ResultMessage.usage` is per turn in streaming-input mode, while `model_usage` is cumulative across turns. | Request usage is not automatically current context occupancy. Deduplicate assistant messages by message ID and empirically validate any cache arithmetic before using it as the Smart-zone signal. [Claude cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), [Claude Messages usage reference](https://platform.claude.com/docs/en/api/typescript/messages) |
| Interrupt a turn | Send `turn/interrupt {threadId, turnId}`. Its successful response is `{}` only. | Call `await client.interrupt()` on `ClaudeSDKClient`; standalone `query()` does not support interrupts. | An interrupt acknowledgement is not a terminal event in either Harness. [Codex generated schema](#codex-artifact), [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python) |
| Synchronize on terminal state | Continue consuming notifications until `turn/completed` for the same thread/turn. `turn.status` is `completed`, `interrupted`, or `failed`; after successful interruption it must be `interrupted`. | Drain `client.receive_response()` through its `ResultMessage`. Interrupted results use `terminal_reason` `aborted_streaming` or `aborted_tools`. The SDK explicitly warns that the interrupt leaves already-produced messages, including the interrupted result, in the buffer. | The terminal signal, rather than the interrupt call's return, is the boundary before a Handoff turn. Claude documents the drain rule directly; Codex expresses it in the response/notification schema. [Codex App Server lifecycle](https://developers.openai.com/codex/app-server), [Python interrupt example](https://code.claude.com/docs/en/agent-sdk/python) |
| Synchronize background terminals | Stable command items expose `processId` when available, lifecycle through `item/started` and `item/completed`, output deltas, and `item/commandExecution/terminalInteraction`; none is a stable whole-thread cleanup operation. Experimental `thread/backgroundTerminals/list`, `/clean`, and `/terminate` provide list/stop controls and require `experimentalApi`. | The turn-level rule remains drain-to-`ResultMessage`. Current SDK messages also expose background-task lifecycle, but the docs do not promise that every process launched by a completed/interrupted turn is gone. | Codex cannot meet the map's explicit "clean background terminals" step using only its stable schema. The prototype must either opt into the experimental cleanup methods or demonstrate that no background process survives. Claude process survival also requires observation for the chosen workload. [Codex App Server API overview](https://developers.openai.com/codex/app-server), [Python SDK message reference](https://code.claude.com/docs/en/agent-sdk/python) |
| Same-session Handoff turn | After the matching `turn/completed`, call `turn/start` again with the same `threadId` and a prompt that writes the Handoff. | After draining the interrupted result, call `client.query()` again on the same connected client and drain its response. | This is ordinary multi-turn behavior, not a Handoff-specific contract. The experiment must verify the file was written, the original session identity stayed unchanged, and sufficient context headroom remained. [Codex App Server lifecycle](https://developers.openai.com/codex/app-server), [Claude sessions](https://code.claude.com/docs/en/agent-sdk/sessions) |
| Fresh successor session | Call `thread/start`, not `thread/resume` or `thread/fork`, and then `turn/start` with the Handoff seed. Compare returned `thread.id`/`sessionId` with the source. | Start a new `query()` with neither `resume` nor `continue_conversation`, or create a new `ClaudeSDKClient` without resume options. Capture the new `ResultMessage.session_id`. | A fresh session does not inherit old context. The application must inject the Handoff content/path and prove the new identifier differs. [Codex App Server threads](https://developers.openai.com/codex/app-server), [Claude sessions](https://code.claude.com/docs/en/agent-sdk/sessions) |

## Documented facts versus required evidence

### Safe to design against at the recorded versions

- Codex stable v2 has `thread/start`, `thread/resume`, `turn/start`, `turn/interrupt`, `skills/list`, the `skill` input union member, `thread/tokenUsage/updated`, and `turn/completed`.
- Codex `turn/interrupt` requires both thread and turn IDs and returns an empty acknowledgement; `turn/completed` is the terminal observation.
- Claude Python's persistent client supports multiple same-context `query()` calls, explicit interruption, and a result-draining iterator.
- Claude interrupted output must be drained before consuming the next query's response.
- Claude sessions can be resumed by captured ID, while a default standalone `query()` starts fresh.
- Both Harnesses have explicit real-skill dispatch syntax and filesystem discovery.
- Claude Python package `0.2.144` and TypeScript package `0.3.243` publish direct context-usage control methods; the Python return type explicitly separates current usage, effective limit, raw limit, and autocompaction metadata.

### Must remain empirical in the prototype

1. **Codex occupancy meaning and cadence.** Determine whether `tokenUsage.last` tracks current pre-compaction context, whether cache tokens are already included in its totals, how often notifications arrive, and whether a notification can be used quickly enough to interrupt near an arbitrary absolute threshold.
2. **Claude context-query liveness.** Verify `get_context_usage()` works concurrently with an active turn under Python `0.2.144` and bundled CLI `2.1.239` (or record a deliberate different `cli_path`), and observe its refresh cadence and behavior across compaction.
3. **Fallback arithmetic.** If Claude's direct query is unusable, confirm that `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` plausibly tracks current occupancy rather than cumulative billing usage for this Harness/model combination.
4. **Compaction races and headroom.** Observe whether automatic compaction happens before the configured trip point and whether enough context remains for a useful Handoff turn.
5. **Interrupt completion.** Confirm Codex emits the matching `turn/completed` with `interrupted`, and Claude emits a drained `ResultMessage` with an aborted terminal reason, without confusing either with the successor response.
6. **Terminal cleanup.** Decide whether the Codex prototype accepts the experimental background-terminal API; either way, demonstrate no terminal survives into the Handoff turn. Do the equivalent observation for Claude because turn completion alone does not promise process cleanup.
7. **Session identity.** Demonstrate same identity for the Handoff turn and a different identity for the successor, rather than inferring it from which API was called.
8. **Real payload skills.** Invoke `mt-review` and `mt-judge` through filesystem discovery and native dispatch; observe permissions, tool events, GitHub identity, and terminal outcomes.
9. **Authentication.** Confirm the exact prototype can use existing subscription authentication without either API-key environment variable. This is a map constraint, not a behavior promised by the Claude Agent SDK docs, and should not be generalized to a third-party product entitlement.
10. **Handoff semantics.** Confirm the original session writes a valid Handoff and the fresh successor uses it to continue autonomously. Neither Harness API validates that application-level contract.

## Consequences for the next tickets

- [Issue 78](https://github.com/mcnewcp/my-team/issues/78) should try a direct usage surface on both Harnesses. For Claude, call `get_context_usage()` first and measure streamed cache-token arithmetic as a cross-check and fallback, rather than assuming either signal is normalized occupancy.
- Codex M1 should log the complete `ThreadTokenUsage` notification and explicitly compare `last` and `total`; the schema alone does not select either as normalized occupancy.
- Interruption code should be shaped as `request interrupt -> keep draining -> observe matching terminal`, never `request interrupt -> immediately start Handoff`.
- The Codex background-terminal step is an explicit experimental dependency. Record capability opt-in and generated experimental-schema digest if the prototype uses it.
- Version reports must distinguish Claude's SDK package version from the bundled Claude Code version. With the current Python wheel those are `0.2.144` and `2.1.239`, even though standalone Claude Code is `2.1.243`.
- [Issue 77](https://github.com/mcnewcp/my-team/issues/77) owns subscription-auth verification. The Agent SDK's documented authentication paths cannot substitute for that experiment, and no later milestone should silently infer subscription compatibility from SDK success with another credential type.

## Primary sources

- [OpenAI: Codex App Server](https://developers.openai.com/codex/app-server)
- Installed Codex `0.149.0` generated stable and experimental JSON Schemas, commands and SHA-256 digests recorded under [Codex artifact](#codex-artifact)
- [Anthropic: Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Anthropic: Python Agent SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Anthropic: Work with sessions](https://code.claude.com/docs/en/agent-sdk/sessions)
- [Anthropic: Extend agents with skills](https://code.claude.com/docs/en/agent-sdk/skills)
- [Anthropic: Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking)
- [Anthropic: Agent SDK quickstart and authentication boundary](https://code.claude.com/docs/en/agent-sdk/quickstart)
- [Official Python package metadata and artifacts](https://pypi.org/pypi/claude-agent-sdk/json)
- [Official TypeScript package registry metadata](https://registry.npmjs.org/%40anthropic-ai%2Fclaude-agent-sdk/latest)
- [Exact Python `0.2.144` source artifact](https://files.pythonhosted.org/packages/73/e0/00d873adf589a4ba7899bc7e6ab5306fa55c8e9f4a2313a6f5fef95a473b/claude_agent_sdk-0.2.144.tar.gz)
- [Exact TypeScript `0.3.243` package artifact](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.243.tgz)
