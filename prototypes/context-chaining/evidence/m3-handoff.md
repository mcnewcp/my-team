# M3 — same-session Handoff

## Decision this evidence informs

[Can an interrupted session still write a useful Handoff?](https://github.com/mcnewcp/my-team/issues/80):
whether each Harness can drain an occupancy-triggered interrupted turn, retain the original
session, write one additional nonce-bearing placeholder Handoff, and expose the context headroom
that turn consumes without accidentally starting a successor session.

## Reproduction identity

- Captured from `2026-08-26T15:03:24.396212-05:00` through
  `2026-08-26T15:07:18.993975-05:00`.
- The run began from prototype base commit
  `b258097bbad00517ccbc7ebc7b91a6a02244b445`; the exact runner used for the run is captured at
  `9e0d86c348b007a2a066c7deffeb8861f9946ea7`.
- The raw trace exposed a false-negative Codex write assertion. The corrected future runner is
  captured at `604bacc55ea3309cddb35f0d5f5b44e95cf424d5`; the correction does not alter or replay this
  run.
- Host platform: `macOS-26.5.2-arm64-arm-64bit-Mach-O`; Python `3.13.5`.
- Configured Smart-zone trip count: `50,000` absolute tokens.
- Workload: `35,400` read-only bytes per occupancy cycle from the same six fixed M1/M2 files;
  model-side tools disabled until the explicit Handoff turn.
- The Product Owner explicitly approved transmitting those six repository files to both model
  services before the run.
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`.
- Persistent Harness configuration changed: **no**.
- Codex `0.149.1` stable v2 schema SHA-256:
  `9b3de71a5a2ffc980b792a18aa8f8dec3f85f48829560222a0264fe494b679a9`; experimental v2:
  `6f76cce25156d405f1da54f205751e38f7b9eb42246ac0742b9958dd60275350`.

| Harness | Harness / SDK versions | Subscription-auth evidence | Effective model | Context window | Automatic compaction |
| --- | --- | --- | --- | ---: | --- |
| Codex | `codex-cli 0.149.1` | account type `chatgpt`, plan `plus` | `gpt-5.6-sol`, reasoning `xhigh` | `258,400` | configured limit and scope both `null`; Harness defaults remained in force |
| Claude Code | SDK `0.2.144`; bundled CLI `2.1.239`; standalone CLI `2.1.246` | `claude.ai` via `firstParty`; API-key source `null` | `claude-opus-5[1m]` | effective and raw `1,000,000` | enabled `true`, threshold `967,000` |

The Claude SDK used its bundled CLI `2.1.239`; the newer standalone CLI is recorded only as host
environment information.

## Procedure

```text
cd prototypes/context-chaining
./run-safe interrupt.py --handoff --target 50000 --max-cycles 12
```

Each Harness opened one fresh ephemeral source session in the same empty temporary directory.
Completed read-heavy turns grew current context until the accepted direct signal crossed the
configured count. The runner then executed the accepted M2 interrupt-to-terminal sequence and
drained the interrupted turn completely before consuming a Handoff response.

For Codex, the runner enabled `experimentalApi`, called
`thread/backgroundTerminals/list`, `/clean`, and `/list` after the matching interrupted
`turn/completed`, then started the Handoff turn on the original thread. Only that turn received a
workspace-write sandbox rooted at its ignored Handoff directory. For Claude, the same connected
`ClaudeSDKClient` issued the next query; a permission callback denied every tool request except one
`Write` to the exact ignored Handoff path during the Handoff phase.

Both one-line prompts required exact nonce-bearing content and the exact response
`HANDOFF_WRITTEN`. Every protocol event, control response, timestamp, and full payload was appended
to ignored local JSONL. The runner did not create, resume, or seed any successor session.

## Expected observation

M3 passes mechanically only if each accepted occupancy signal crosses `50,000` without a prior
compaction drop; the interrupted turn reaches and is drained through its Harness-specific terminal
event; the next turn writes the exact current-run Handoff on the same session; post-Handoff
occupancy is greater than pre-Handoff occupancy while remaining below the context window; and the
trace contains no second thread or session identity.

Codex must additionally complete its experimental background-terminal list/clean/list sequence
after the interrupted terminal event and before the Handoff turn. A successful file on disk is not
alone sufficient: the protocol must attribute a completed write-capable item to the Handoff turn.

## Observations

### Codex

| Observation | Tokens |
| --- | ---: |
| Smart-zone crossing / before Handoff | `58,592` |
| After Handoff | `61,722` |
| Handoff headroom consumed | `3,130` |
| Remaining context headroom | `196,678` |

- Current context crossed on cycle 5, `8,592` tokens beyond the configured count at the observed
  completed-turn cadence. No compaction-shaped drop occurred.
- The interrupt-target turn started `inProgress`; `turn/interrupt` acknowledged with `{}`; the
  matching `turn/completed` then reported `interrupted`. Only after that terminal event did the
  runner call background-terminal list/clean/list. Both lists were empty and the clean response
  was `{}`.
- The raw trace contains exactly one `thread/start` request and one `thread/started` identity. The
  Handoff `turn/start` names that same thread, so no fresh or resumed thread entered the path.
- The Handoff turn reported `completed`. Its live event stream attributed completed
  `userMessage`, `reasoning`, `commandExecution`, and `agentMessage` items to that turn; the
  `commandExecution` completed successfully. The ignored file exactly matched the nonce-bearing
  expected content and had SHA-256
  `8f1b4b0b56c84d511808c44fedc99e97d00a38902de721486a54f9ab8dbdb49d`.
- The initial derived summary marked Codex failed because its final `turn/completed` snapshot
  retained only the `agentMessage`, even though the preceding live `item/completed` event retained
  the successful `commandExecution`. The corrected runner observes completed item types from the
  live stream. This report derives the verdict from the preserved raw events; it does not rewrite
  or rerun them.

### Claude Code

| Observation | Tokens |
| --- | ---: |
| Smart-zone crossing / before Handoff | `55,436` |
| After Handoff | `57,340` |
| Handoff headroom consumed | `1,904` |
| Remaining context headroom | `942,660` |

- Current context crossed on cycle 4, `5,436` tokens beyond the configured count. No
  compaction-shaped drop occurred.
- The live occupancy re-check remained at `55,436`; `interrupt()` acknowledged; the interrupted
  stream then drained through exactly one `ResultMessage` with
  `terminal_reason=aborted_streaming` before the Handoff query began.
- Every server message carrying a session identity used the same single value. The Handoff
  `ResultMessage` identity matched both the warm-up and interrupted results, so no fresh or resumed
  session entered the path.
- The permission callback observed exactly one request: `Write`, during the Handoff phase, with
  the exact expected path; it allowed that request. The Handoff result reported `success`, returned
  `HANDOFF_WRITTEN`, had no permission denials, and drained through exactly one `ResultMessage`.
- The ignored file exactly matched the nonce-bearing expected content and had SHA-256
  `417f4f3fdad66d81663b7e76ac58095dd31c041759f3fbaa2872c6f5eda823fc`.

## Trace inventory

Raw JSONL and Handoff files remain local and untracked.

| Harness | Local path | SHA-256 | Sanitization notes |
| --- | --- | --- | --- |
| Codex | `local/traces/20260826-150324-396042-codex-handoff.jsonl` | `e974c287a3a87553bfdb5f795378944f37bfd124886d2d1cea8e3372a6e33f22` | none; full raw payload is local only |
| Claude Code | `local/traces/20260826-150324-396042-claude-handoff.jsonl` | `59429471e377b610b113c270c585e50974f655dd6c0e162bfcf60c41455b5662` | none; full raw payload is local only |

## Result

- Outcome: **pass mechanically; proceed to Product Owner review**.
- Evidence-backed finding: after an occupancy-triggered interrupted turn, both tested Harnesses
  retained the original session for one additional useful turn, wrote the exact placeholder
  Handoff, and exposed ample positive remaining context headroom without starting a successor.
- Harness-specific constraint: Codex's demonstrated pre-Handoff cleanup depends on its
  experimental background-terminal API. Claude needed the interrupted `ResultMessage` drained
  before its next query and allowed only the exact Handoff `Write` through its permission callback.
- Measured placeholder cost at the tested settings: Codex `3,130` current-context tokens; Claude
  `1,904`. These are observed mechanics, not a general estimate for a context-complete Handoff.
- Remaining uncertainty: this run does not establish Handoff quality, Handoff cost at the desired
  `200,000`-token default, fresh-session seeding or autonomous continuation, repeated chaining,
  missing/malformed-Handoff handling, or real payload-skill dispatch.

## Consequences for the map

If the Product Owner accepts M3, the same-session Handoff boundary is sufficient to proceed to
[Can a Handoff autonomously continue in a fresh session?](https://github.com/mcnewcp/my-team/issues/81).
No recovery ticket is needed from this passing run, and the map's failure-recovery fog remains
ungraduated. Do not start fresh-session continuation before this evidence is accepted.
