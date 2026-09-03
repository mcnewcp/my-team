# Escalation swaps the labels, and the swap back resets the limits

> **Supersession note:** [ADR-0013](./0013-pipeline-state-is-a-label-backed-cursor.md) broadens
> `ready-for-agent` and `ready-for-human` into a queue projection for every automated or
> human-waiting State. The escalation swap, trusted-human reauthorization and limit-reset
> semantics in this record remain in force for a valid State. State corruption has no valid source
> to replace with `escalated`, and an unexpected merge is irreversible terminal truth, so ADR-0013
> instead quarantines either while preserving the State labels until an explicit repair. It also
> abstracts this record's comment into a durable notice-completion anchor on the issue timeline,
> bound to the escalation occurrence. Concrete mutation credentials, anchor encoding, notice
> carrier, schema and rendering are decided later; its narrative payload never selects State or an
> Action.

When the loop stops converging, the orchestrator enters `escalated`, adds `ready-for-human`, then
removes `ready-for-agent`, reobserving after each mutation, and records one attributable
notice-completion anchor for that occurrence on the issue timeline before accepting
reauthorization. Every convergence limit is counted from the most recent trusted-human application
of `ready-for-agent` that opened the Authorization epoch. Orchestrator-authored Queue projections
never reset a counter. The human's later reauthorization is therefore the same act that clears the
counters, and both the limits and their reset derive from issue history.

## Considered options

**Additive labels** — leave `ready-for-agent` in place and add `ready-for-human` beside it.
This is what the state machine originally specified, on the grounds that `ready-for-agent`
is authorization rather than a lock and only a terminal state should clear it. It works
mechanically, because `ESCALATED` is evaluated before `HALTED`, and it makes resumption a
single act rather than two. It was rejected because the two labels are defined as mutually
exclusive triage states, so an escalated issue would go on matching every "ready for an
agent" query — the one question that label exists to answer. The swap also means every
escalation is cleared by a deliberate re-authorization from someone with write access,
which is worth having on a public repo whose tracker is the orchestrator's instruction
surface.

**Storing the counters locally**, in the per-issue state directory beside the worktree.
Immediate and obvious, and ruled out by [0001](./0001-isolated-worktree-and-handoffs-outside-git.md):
the workspace is acted on and never observed, and a counter the orchestrator writes and
then trusts is durable state wearing a different costume — the same objection that
[0002](./0002-draft-flag-is-the-implementer-latch.md) raised against a label the
orchestrator maintains itself.

**Counting from the issue's beginning, with no reset.** The simplest thing to derive, and
it makes an escalation permanent: the human clears the label, re-runs, and the same limit
trips on the first tick with the same evidence. An escalation that cannot be cleared is
worse than no escalation.

**A `--resume` flag, or a counter offset in config.** Both work. Both put the reset in a
file or a flag the human has to remember, rather than in the act they are already
performing to hand the issue back.

## Consequences

Counting and measuring cannot share the anchor. The round limits count events since the
re-authorization, which is independent of how long ago it happened — an issue labelled on
Saturday and worked on Sunday counts zero rounds, correctly. The stall detector measures a
duration, so anchoring it to the same event would read twenty-four hours of elapsed
weekend as a stalled agent and escalate on the first tick. It is floored at the start of
the current `work` invocation instead, which is the one piece of orchestrator memory in
the design and is deliberately ephemeral: it dies with the process, nothing durable
records it, and State was already a function of the observation *and the clock* the moment
stalls were defined as elapsed time rather than tick counts.

A half-cleared escalation halts rather than resuming. Removing `ready-for-human` without
adding `ready-for-agent` back leaves the issue matching `HALTED`, and the loop stops
without asking for anything. This is the correct reading — an issue with neither label is
untriaged — but it is a quiet stop rather than a loud one, so `work` says so on exit.

The escalation notice has to make its evidence durably available. A resumed loop remembers
nothing about why it stopped, so it observes only the issue-timeline anchor's attribution,
occurrence binding and event ordering. The CLI contract decides its exact encoding and the
notice's carrier, schema and rendering; the ladder never parses the narrative payload.
