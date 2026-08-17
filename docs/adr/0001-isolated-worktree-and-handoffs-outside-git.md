# Agents work in an isolated worktree, and handoffs never enter git

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
handoff never selects an action. A tick derives "continue implementing" from the branch and PR
alone, identically whether or not a handoff exists; the handoff only enriches the prompt for an
action already chosen.

Handoffs must sit in a sibling directory and never at the worktree root, where they would be
untracked files in the working tree that `git add -A` stages.

The harness invocation has to grant write access to that sibling directory — `--add-dir` for
Claude Code — because it lies outside the agent's working directory.
