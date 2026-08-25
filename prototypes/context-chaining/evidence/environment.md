# Dual-Harness environment

Sanitized setup evidence for
[Prepare an isolated dual-harness experiment](https://github.com/mcnewcp/my-team/issues/77).

## Reproduction identity

- Captured at: `2026-08-25T09:11:08.895517-05:00`
- Prototype commit: `92b01a914b0babfef58aee57bd84e15d625d6825`
- Host platform: `macOS-26.5.2-arm64-arm-64bit-Mach-O`
- Python: `3.13.5`
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`
- Persistent Harness configuration changed: **no** (all watched settings fingerprints were
  unchanged; the Codex thread was ephemeral and both permission envelopes were read-only)

## Harnesses

| Harness | Versions and generated protocol | Subscription auth | Effective model | Context window | Automatic compaction |
| --- | --- | --- | --- | ---: | --- |
| Codex | `codex-cli 0.149.0`; stable v2 `9b3de71a5a2ffc980b792a18aa8f8dec3f85f48829560222a0264fe494b679a9`; experimental v2 `6f76cce25156d405f1da54f205751e38f7b9eb42246ac0742b9958dd60275350` | account type `chatgpt`, plan `plus` | `gpt-5.6-sol` (openai) | `258400` | configured limit `null`, scope `null` |
| Claude Code | SDK `0.2.144`; bundled CLI `2.1.239`; standalone `2.1.243 (Claude Code)` | `claude.ai` via `firstParty`; API-key source `null` | `claude-opus-5[1m]` | effective `1000000`, raw `1000000` | enabled `true`, threshold `967000` |

Codex effective thread settings were approval policy `never`,
sandbox `read-only`, and ephemeral persistence. Its configured model/context fields were
`{"custom_compact_prompt": false, "model": "gpt-5.6-sol", "model_auto_compact_token_limit": null, "model_auto_compact_token_limit_scope": null, "model_context_window": null, "model_provider": null, "model_reasoning_effort": "xhigh"}`; `null` means the Harness default remained in
force. The Codex thread loaded no instruction sources. The Claude SDK used its bundled CLI with no
setting sources or tools available.

## Smoke observation

- Codex completed the inert no-tool query with terminal status
  `completed` and emitted a context-window observation.
- Claude Code completed the same inert no-tool query with result subtype
  `success` and returned `get_context_usage()` after the turn.
- These observations prove setup and effective settings only. They do not resolve occupancy
  cadence, concurrent Claude queries, interruption, Handoff, fresh-session continuation, or real
  skill dispatch.

## Local-only artifacts

- Codex trace: `local/traces/20260825-091108-895499-codex-environment.jsonl` (`fcfaaf60c4da7f4a8ecb0e721962809d1c6ba3ea825e9ad3da44231a10372e78`)
- Claude trace: `local/traces/20260825-091108-895499-claude-environment.jsonl` (`695f4a146fbafd380f33fb650538310e76143ed8e35645f16f771b4b9bef3ba4`)
- Generated schemas: `local/schemas/`

The traces and generated schemas are intentionally ignored by git.
