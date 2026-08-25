# Milestone <ID> — <name>

## Decision this evidence informs

<Link the Wayfinder ticket and state the decision, not merely the activity performed.>

## Reproduction identity

- Captured at: `<ISO-8601 timestamp with offset>`
- Prototype commit: `<full git SHA>`
- Host platform: `<OS and architecture>`
- Python: `<version>`
- Smart-zone trip count: `<positive absolute token count>`
- Workload cycles: `<count>`
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`

| Harness | Harness / SDK versions | Subscription-auth evidence | Effective model | Context window | Automatic compaction |
| --- | --- | --- | --- | ---: | --- |
| Codex | `<CLI and schema version/digest>` | `<sanitized account type and plan>` | `<thread/start model>` | `<observed modelContextWindow>` | `<effective/configured limit and scope>` |
| Claude Code | `<SDK, bundled CLI, standalone CLI>` | `<sanitized auth status>` | `<init/context-usage model>` | `<effective and raw max>` | `<enabled and threshold>` |

Persistent user configuration changed: **no**.

## Procedure

```text
<Exact commands, with secrets omitted.>
```

## Expected observation

<What would pass, fail, or trip the kill gate before looking at the result.>

## Observations

### Codex

<Timestamped observations. Distinguish request acknowledgement from terminal notification.>

### Claude Code

<Timestamped observations. Distinguish interrupt return from the drained ResultMessage.>

## Trace inventory

Raw JSONL remains local and untracked.

| Harness | Local path | SHA-256 | Sanitization notes |
| --- | --- | --- | --- |
| Codex | `local/traces/<file>.jsonl` | `<digest>` | `<none; local only>` |
| Claude Code | `local/traces/<file>.jsonl` | `<digest>` | `<none; local only>` |

## Result

- Outcome: `<pass / fail / inconclusive>`
- Evidence-backed finding: <one precise statement>
- Remaining uncertainty: <what this run did not establish>
- Kill-gate decision: `<proceed / stop and revisit the map>`

## Consequences for the map

<Tickets or fog made sharper by this result. Do not propose production implementation here.>
