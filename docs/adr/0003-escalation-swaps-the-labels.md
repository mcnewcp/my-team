# Escalation swaps the labels, and the swap back resets the limits

When the loop stops converging, the orchestrator removes `ready-for-agent`, adds
`ready-for-human`, mentions the product owner once with the evidence, and exits. Every
convergence limit is counted from the most recent `labeled: ready-for-agent` event on the
issue timeline, so the human's act of re-authorizing the issue is the same act that clears
the counters. Nothing is written down: the limits and their reset both derive from the
issue's own history.

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

The escalation comment has to carry its own evidence. A resumed loop re-derives everything
from GitHub and remembers nothing about why it stopped, so the comment is the only record
of which limit tripped, at what value, and what the last agent said before it did.
