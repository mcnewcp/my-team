# Agents work in an isolated worktree, and handoffs never enter git

> **Supersession note:** [ADR-0013](./0013-pipeline-state-is-a-label-backed-cursor.md) retains
> this record's refusal to observe the workspace, but supersedes the claims below that the remote
> branch and pull request alone select an Action and that one State names one Action. The issue's
> label-backed State is also GitHub evidence, names the owner of the next work, and feeds a
> State-local Ladder that selects at most one Action.

Each issue gets a `git worktree` under `~/.local/state/my-team/<owner>-<repo>/<issue>/`, and the
handoff documents an agent writes for its successor live beside that worktree rather than on the
working branch. Working in the human's own checkout would lock them out of their repo for the
length of an unattended run, and keeping handoffs in git forces a pre-merge scrub commit that
cannot coexist with branch protection's dismiss-stale-reviews.

## Considered options

**Working in place** in the target repo checkout — which the deployment model otherwise favours,
since the CLI is installed into the target repo and run from its root. Rejected on autonomy:
`my-team work <issue>` runs unattended for a long stretch, and in place the human cannot touch
their own repo until it finishes, which contradicts the premise of the tool. The parallel-agents
argument for worktrees is real but was not the deciding one — parallelism is out of scope for
v0.1, and this decision would hold without it.

**Handoffs on the working branch** at `.my-team/handoff-NN.md`, which was the original charter
decision and is the option a future reader is most likely to propose again. Squash merge collapses
commits but not files, so any handoff sitting on the branch tip lands in the target repo
permanently. Scrubbing them in a pre-merge commit fixes that, but then the merged tree differs
from the approved tree; scrubbing before review instead destroys a reviewer's handoff to the next
reviewer, which is a real case rather than a hypothetical one. Taking them out of git removes the
scrub commit, the stray-file merge precondition, and the ordering conflict in one move.

## Consequences

Handoffs are lost if the state directory is deleted, and that is acceptable: the work itself is
committed to the branch, so a fresh agent reads the issue and the commits and continues — less
informed, never wrong.

The rule that GitHub is the sole source of truth for orchestrator state survives intact, because a
handoff never selects an action. A tick derives "continue implementing" from the remote branch and
the PR alone, identically whether or not a handoff exists; the handoff only enriches the prompt for
an action already chosen.

Handoffs must sit in a sibling directory and never at the worktree root, where they would be
untracked files in the working tree that `git add -A` stages.

The harness invocation has to grant write access to that sibling directory — `--add-dir` for
Claude Code — because it lies outside the agent's working directory.

## The orchestrator acts on the workspace and never observes it

The orchestrator creates the workspace, dispatches into it, pushes from it and tears it down. It
never derives **State** from it. Every guard in the tick ladder reads GitHub — the remote branch,
the pull request, its reviews, the checks at head, the timeline — and the local git inside the
worktree is not part of an Observation.

This was settled later than the decision above, while correcting two ladder rows whose guards named
a different fact than the action dispatched to discharge them. The row recognising "no work has
started" read the *remote* branch, but nothing in its action put the branch there: the implementer
committed and the branch stayed local, so the row re-matched forever. The alternative on the table
was to make the worktree's git a second observation source, letting the ladder see the local commit
directly.

It was rejected because **no action changes**. State is the value that names one action, so a
distinction the ladder cannot act on differently is not a state. The one case that mattered —
committed but not pushed — is discharged mechanically instead: the orchestrator pushes the branch
as the tail of every implementation dispatch, a no-op both when the agent has already pushed and
when it has committed nothing. The skill also tells the agent to commit and push as it works, so a
human running it by hand gets the same result. Neither is trusted, because the guard reads the
remote ref either way.

Three further things argued against the alternative. Two authorities that can disagree need a
reconciliation rule for every predicate, which is the failure the sole-source-of-truth rule exists
to prevent. The acceptance above — that losing the state directory is survivable because the work
itself is committed to the branch — holds only while the branch is *pushed*; make local git
load-bearing and a wiped state directory loses tracked progress rather than prose. And the worktree
is the agent's drafting surface, not its published one: an implementer was measured verifying its
own work by cloning the pushed branch into a fresh directory rather than trusting its working tree.

The bar for reopening this is one question — **which action changes?** A concrete case where
observing local git would make the ladder dispatch differently is a reason to revisit. The
expansion is cheap and additive, which is exactly why the restrictive choice is the one worth
writing down.
