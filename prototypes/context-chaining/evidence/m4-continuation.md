# M4 — fresh-session continuation

## Decision this evidence informs

[Can a Handoff autonomously continue in a fresh session?](https://github.com/mcnewcp/my-team/issues/81):
whether a driver can validate a source session's Handoff, seed it by value into a fresh successor
without resuming the context being escaped, repeat that boundary until the original Action
finishes, and fail loudly before successor creation when the Handoff is missing or malformed.

## Reproduction identity

- Captured from `2026-08-26T20:52:02.654226-05:00` through
  `2026-08-26T20:56:07.998371-05:00`.
- Exact runner commit: `eee9a700774778bea6c9c9a6e412cd6e424b8169`.
- Host platform: `macOS-26.5.2-arm64-arm-64bit-Mach-O`; Python `3.13.5`.
- Configured Smart-zone trip count: `25,000` absolute tokens per source session.
- Action shape: three ordered synthetic units (`ember`, `birch`, `cobalt`) across three sessions
  and two Handoff boundaries per Harness.
- Workload: `35,400` read-only bytes per occupancy cycle from the same six fixed M1–M3 files;
  at most eight cycles per source session, with model-side tools disabled until the exact Handoff
  write.
- The Product Owner explicitly approved transmitting the six files, synthetic Action prompts,
  nonce-bearing Handoff JSON, and local Handoff destination paths to both model services before
  the run.
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
./run-safe continuation.py --target 25000 --max-cycles 8
```

The single runner invocation performed the whole chain without a human prompt or an outer-loop
restart. Each Harness received an initial briefing for the same three-unit Action. A source
session completed its current unit, grew current context past the configured count, drained the
accepted interruption sequence, and wrote a strict nonce-bearing JSON Handoff on that same
session. The driver then read and validated the file before creating a successor.

The successor was seeded by embedding the observed Handoff content into its first prompt. Codex
used a new ephemeral `thread/start`; Claude used a newly connected `ClaudeSDKClient` with no
`resume` option. Neither path used a Harness resume API. The successor had to return an exact
nonce-bearing Action response before it could become the next source or finish the Action.

Before either live chain, the runner passed an absent path and invalid JSON through the same
validator used at the real boundaries. Both raised `RuntimeError`; the runner would not create a
successor after either error.

## Expected observation

M4 passes mechanically only if both Harnesses produce three distinct session identities; retain
one identity throughout each source session's Action, interruption, and Handoff phases; change
identity at each and only each successor boundary; and complete the exact ordered Action responses
across two validated Handoffs. Each successor's seed SHA-256 must equal its source Handoff's
SHA-256, and the final session must return the exact `ACTION_COMPLETE` proof.

Both source sessions must cross `25,000` before a compaction-shaped drop, drain the
Harness-specific interruption terminal, and write the exact Handoff before the successor starts.
Missing and malformed documents must raise before any successor creation. Any resume call, human
input, outer-loop restart, identity reuse across a boundary, identity change within a session, or
seed mismatch fails the milestone.

## Observations

Session identity values are intentionally omitted from this sanitized report. The aliases below
map one-to-one to the exact identities retained in the local summary and raw traces.

### Codex

| Session | Seed and Action response | Smart-zone / terminal observation |
| --- | --- | --- |
| C1 | Initial briefing → exact `ACTION_PROGRESS 20260826-205202-654005-codex 1/3 ember` | Crossed at `30,318` on cycle 2; `turn/interrupt` returned `{}`; matching terminal was `interrupted`; wrote Handoff `c7504de1…e342b` on C1 |
| C2 | Validated Handoff `c7504de1…e342b` → exact `ACTION_PROGRESS 20260826-205202-654005-codex 2/3 birch` | New identity; crossed at `29,821` on cycle 2; matching terminal was `interrupted`; wrote Handoff `c63f5067…43eb0` on C2 |
| C3 | Validated Handoff `c63f5067…43eb0` → exact `ACTION_COMPLETE 20260826-205202-654005-codex ember,birch,cobalt` | New identity; Action finished, so no further interruption or Handoff occurred |

- The raw request inventory contains exactly three `thread/start`, eleven `turn/start`, two
  `turn/interrupt`, two background-terminal `clean`, and four background-terminal `list` calls.
  It contains no resume call.
- C1 and C2 each retained their thread identity through Action, warm-up, interruption cleanup,
  and Handoff. Each Handoff turn began after the matching interrupted terminal and experimental
  cleanup; the live event stream observed a completed write-capable item.
- C1→C2 and C2→C3 each changed thread identity. In both cases the driver validated the Handoff
  before the successor's `thread/start`, seeded its observed bytes by value, and recorded equal
  Handoff and seed SHA-256 values.
- All three exact Action responses matched. No compaction-shaped drop occurred in either source
  session.

### Claude Code

| Session | Seed and Action response | Smart-zone / terminal observation |
| --- | --- | --- |
| A1 | Initial briefing → exact `ACTION_PROGRESS 20260826-205202-654005-claude 1/3 ember` | Crossed at `27,356` on cycle 2; live re-check remained above target; drained one `ResultMessage` with `aborted_streaming`; wrote Handoff `30d5e8ea…8b16` on A1 |
| A2 | Validated Handoff `30d5e8ea…8b16` → exact `ACTION_PROGRESS 20260826-205202-654005-claude 2/3 birch` | New identity; crossed at `27,658` on cycle 2; drained one `ResultMessage` with `aborted_streaming`; wrote Handoff `6ad87e2a…4b01` on A2 |
| A3 | Validated Handoff `6ad87e2a…4b01` → exact `ACTION_COMPLETE 20260826-205202-654005-claude ember,birch,cobalt` | New identity; Action finished, so no further interruption or Handoff occurred |

- The runner opened exactly three `ClaudeSDKClient` connections without a `resume` option. The
  trace contains three Action queries, two interrupt-target queries, two interrupts, two Handoff
  queries, and exactly two allowed `Write` callbacks.
- Within A1 and A2, every Action, warm-up, interrupted, and Handoff result used one identity. A3's
  Action messages used one identity. The three per-session identities were mutually distinct.
- A1→A2 and A2→A3 each changed identity only after the source Handoff terminal. Both successors
  received the validated Handoff bytes in their first query, with equal Handoff and seed SHA-256
  values.
- Each interrupted stream drained through exactly one terminal `ResultMessage` before the Handoff
  query. Each Handoff drained through exactly one successful `ResultMessage`, used the exact
  permitted path, and matched the expected document byte for byte. No compaction-shaped drop or
  permission denial occurred.

### Fail-loud boundary probes

| Input | Observation |
| --- | --- |
| Missing Handoff path | Raised `RuntimeError: missing Handoff` before successor creation |
| Malformed Handoff (`{ definitely-not-json`) | Raised `RuntimeError: malformed Handoff: invalid JSON at line 1 column 3` before successor creation |

## Trace inventory

Raw JSONL, Handoff documents, the derived summary, and exact session identities remain local and
untracked.

| Harness | Local path | SHA-256 | Sanitization notes |
| --- | --- | --- | --- |
| Codex | `local/traces/20260826-205202-654005-codex-continuation.jsonl` | `43a9a91f64fe8bc3eaa78e042f9dc85151fe535ea4025536ba7ed9c962823fc1` | none; full raw payload and identities are local only |
| Claude Code | `local/traces/20260826-205202-654005-claude-continuation.jsonl` | `79088739ae0897237a0872c319e98ff5033e0ccbb6b13b881efb170aa14e5589` | none; full raw payload and identities are local only |

## Result

- Outcome: **pass mechanically; proceed to Product Owner review**.
- Evidence-backed finding: both tested Harnesses autonomously carried one original Action through
  two source-to-successor Handoff boundaries and three distinct sessions, seeded each successor
  from the exact validated Handoff rather than resumed context, and returned the exact terminal
  Action proof without human or outer-loop intervention.
- Boundary behavior: identity remained stable within each source session and changed at both
  successor boundaries. Missing and malformed Handoffs raised before successor creation.
- Harness-specific constraint: Codex still requires the demonstrated experimental
  background-terminal cleanup before each source Handoff. Claude requires each interrupted
  `ResultMessage` to be drained before the Handoff query and a new SDK connection without
  `resume` for each successor.
- Remaining uncertainty: the runner prescribed a minimal synthetic Handoff and exact Action
  responses. It does not establish context-complete Handoff quality, behavior at the desired
  `200,000`-token default, real payload-skill dispatch, production retries, or crash recovery.

## Consequences for the map

If the Product Owner accepts M4, fresh-session seeding, autonomous repeated chaining, identity
boundaries, and fail-loud Handoff validation are sufficient to proceed to
[Can the adapter invoke the real Reviewer and Judge skills through Codex?](https://github.com/mcnewcp/my-team/issues/82).
No recovery ticket is needed from this passing run, and the map's failure-recovery fog remains
ungraduated. Do not start real skill dispatch before this evidence is accepted.
