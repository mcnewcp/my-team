# One Action owns its continuity chain

A Harness-backed **Action** owns every session needed to discharge its one Role and definition of
done. When a session crosses the **Smart zone**, the adapter interrupts and drains it, proves its
background work quiescent, runs one constrained **Handoff** turn on that source session, validates
the artifact, and seeds a genuinely fresh successor by value. The adapter repeats that sequence
inside the same invocation until the Action finishes or returns a real terminal failure; crossing
the Smart zone is an internal continuity event, not an Action outcome.

This keeps Action aligned with responsibility rather than context-window accidents. The empirical
dual-Harness prototype carried one Action through three fresh sessions without an outer-loop
decision, while the old `Capped` outcome ended an Action before its definition of done and made a
local Handoff look like pipeline progress. Session identities and Handoffs remain ephemeral
telemetry: neither may select orchestrator State or the next Action, so a crash still recovers by
observing GitHub and dispatching fresh.

## Considered options

**End the Action as `Capped`.** This preserved a process-shaped seam, but split one Role obligation
into context-sized Actions and exposed a Harness implementation detail to the tick loop.

**Resume the stopped session as the successor.** This retained warm context by retaining the very
context rot the Handoff exists to escape. The source session is reused only for its one Handoff
turn; every worker successor is fresh.

## Consequences

The public outcomes are `Finished`, `Failed`, `TimedOut`, `ContinuityFailed`, and `HarnessError`.
Compaction before a valid Handoff, incomplete draining, unprovable quiescence, an invalid Handoff,
or a non-fresh successor returns `ContinuityFailed` without creating another successor. One
Action-wide deadline and the separately specified Handoff-chain policy bound the loop.

The seam emits per-session occupancy and lifecycle telemetry but exactly one Action terminal event.
Native protocol payloads stay in local diagnostics, and no continuity telemetry becomes
orchestrator State.
