# M2 — absolute-occupancy interruption

## Decision this evidence informs

[Can both Harnesses stop at an arbitrary absolute occupancy?](https://github.com/mcnewcp/my-team/issues/79):
whether each Harness can apply an absolute Smart-zone count to the accepted M1 occupancy signal,
interrupt an active turn, and reach a clean, observable terminal boundary before a Handoff turn.

## Reproduction identity

- Captured from `2026-08-26T13:22:37.983187-05:00` through
  `2026-08-26T13:30:55.541706-05:00`.
- The run began from prototype base commit
  `13fb666f44372bc1748f4fdc8f7679ebd79265c0`; the exact unmodified runner used for the run was
  captured immediately afterward at `a87755892cd506a325c0edf6f97ddb11b88ec4b6`.
- Host platform: `macOS-26.5.2-arm64-arm-64bit-Mach-O`; Python `3.13.5`.
- Configured Smart-zone trip count: `50,000` absolute tokens.
- Workload: `35,400` read-only bytes per occupancy cycle from the same six fixed M1 files;
  model-side tools disabled.
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`.
- Persistent Harness configuration changed: **no**.
- Codex `0.149.1` stable v2 schema SHA-256:
  `9b3de71a5a2ffc980b792a18aa8f8dec3f85f48829560222a0264fe494b679a9`; experimental v2:
  `6f76cce25156d405f1da54f205751e38f7b9eb42246ac0742b9958dd60275350`.

| Harness | Harness / SDK versions | Subscription-auth evidence | Effective model | Context window | Automatic compaction |
| --- | --- | --- | --- | ---: | --- |
| Codex | `codex-cli 0.149.1` | account type `chatgpt`, plan `plus` | `gpt-5.6-sol`, reasoning `xhigh` | `258,400` | configured limit and scope both `null`; Harness defaults remained in force |
| Claude Code | SDK `0.2.144`; bundled CLI `2.1.239`; standalone `2.1.246` | `claude.ai` via `firstParty`; API-key source `null` | `claude-opus-5[1m]` | effective and raw `1,000,000` | enabled `true`, threshold `967,000` |

The Claude SDK used its bundled CLI `2.1.239`; the newer standalone CLI is recorded only as host
environment information.

## Procedure

```text
cd prototypes/context-chaining
./run-safe interrupt.py --target 50000 --max-cycles 12
```

Each Harness opened a fresh ephemeral session in the same empty temporary directory. Completed
read-heavy turns grew current context until the accepted direct signal crossed the configured
count. The threshold path then differed only where the observed control surfaces required it:

- Codex checked the last completed-turn `last.totalTokens`, started the next turn, sent
  `turn/interrupt`, treated the empty response as acknowledgement only, and kept consuming events
  until the matching `turn/completed`.
- Claude started the interrupt-target query, queried live
  `get_context_usage().totalTokens`, called `interrupt()`, then drained `receive_response()`
  through its terminal `ResultMessage`.

Every request, response, notification, timestamp, and full payload was appended to ignored local
JSONL. No Handoff prompt, Handoff artifact, successor session, skill dispatch, or tool path was
added.

A sharp compaction drop retained M1's predeclared definition: both at least `10,000` tokens and at
least `20%` of the prior direct observation.

## Expected observation

M2 passes mechanically only if each accepted direct signal crosses `50,000` without a prior
compaction drop, an active turn is interrupted, and the Harness produces its documented terminal
boundary after—not instead of—the interrupt acknowledgement. Codex must report the matching
`turn/completed` with status `interrupted`. Claude must drain exactly one terminal `ResultMessage`
whose terminal reason is `aborted_streaming` or `aborted_tools`.

## Observations

### Codex

| Cycle | `last.totalTokens` |
| ---: | ---: |
| 1 | `20,758` |
| 2 | `31,199` |
| 3 | `40,461` |
| 4 | `49,699` |
| 5 | `58,775` |

- The threshold correctly remained inactive at `49,699`, then crossed on cycle 5 at `58,775`:
  `8,775` tokens of overshoot at the observed completed-turn cadence.
- No compaction-shaped drop occurred before the crossing. The observed model window was
  `258,400` tokens.
- The interrupt-target `turn/start` response was `inProgress`. The client immediately sent
  `turn/interrupt`; its empty acknowledgement arrived `2.703 ms` later.
- The matching `turn/completed` arrived `0.091 ms` after acknowledgement with status
  `interrupted` and no emitted items. The acknowledgement was not mistaken for terminal state.

For this no-tool, one-model-request-per-turn workload, Codex exposed the usable occupancy update at
completed-turn cadence. The demonstrated policy therefore observes a crossing, starts the next
turn, and interrupts that active turn. It does not prove a tighter in-flight sampling cadence for
a tool-using production Action.

### Claude Code

| Cycle | `get_context_usage().totalTokens` |
| ---: | ---: |
| 1 | `12,734` |
| 2 | `26,776` |
| 3 | `40,780` |
| 4 | `54,794` |

- The direct signal crossed on cycle 4 at `54,794`: `4,794` tokens of overshoot. No
  compaction-shaped drop occurred.
- After the interrupt-target query started, a live control request returned the same `54,794`
  current-context count in `187.219 ms`, still above the configured target.
- `interrupt()` acknowledged in `1.407 ms`. The terminal result arrived `13.086 ms` later with
  `terminal_reason=aborted_streaming`, `subtype=error_during_execution`, and `is_error=true`.
  That error-shaped subtype is Claude's observed representation of the requested cancellation,
  not an unrequested Harness failure.
- The interrupted stream drained `SystemMessage`, `UserMessage`, then exactly one `ResultMessage`;
  `receive_response()` stopped at that terminal result. It remained the same session as the
  warm-up turns and reported no permission denials.

## Trace inventory

Raw JSONL remains local and untracked.

| Harness | Local path | SHA-256 | Sanitization notes |
| --- | --- | --- | --- |
| Codex | `local/traces/20260826-132237-983172-codex-interruption.jsonl` | `339b3a91184f2b0fc1c98fac5448b9bb517331035c16a8a31f9cb0ad22698460` | none; full raw payload is local only |
| Claude Code | `local/traces/20260826-132237-983172-claude-interruption.jsonl` | `028d564494d6ca98c88dc377c2ccf98c7aa51f07c08ad8f555652dd13e4edf22` | none; full raw payload is local only |

## Result

- Outcome: **pass mechanically; proceed to Product Owner review**.
- Evidence-backed finding: at an arbitrary configured `50,000`-token Smart-zone count, both
  Harnesses used the accepted normalized current-context signal to interrupt an active turn and
  expose a distinct, clean terminal boundary before any automatic compaction.
- Harness-specific constraint: Codex's demonstrated trigger granularity is a completed-turn
  occupancy update; Claude supports a live occupancy re-check after the interrupt-target query
  starts.
- Remaining uncertainty: this run does not exercise the desired `200,000`-token interruption
  point itself, a tool-using Action's occupancy cadence or process cleanup, a same-session Handoff
  turn, actual next-response separation, fresh-session continuation, or real skill dispatch. M1
  separately established that both tested Harness/model combinations cross `200,000` before
  compaction.

## Consequences for the map

If the Product Owner accepts M2, the interruption boundary is sufficient to proceed to the
same-session Handoff milestone. The v0.1 proposal must preserve the two Harness-specific trigger
paths and describe Codex overshoot in terms of observable turn cadence rather than promise
token-by-token interruption. No new recovery ticket is needed from this passing run, and the map's
failure-recovery fog remains ungraduated.
