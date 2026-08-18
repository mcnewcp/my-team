# The draft flag is the implementer's latch

A pull request is a draft exactly when the implementer holds it. The orchestrator converts it
to draft whenever it dispatches implementation work — first pass, CI repair, or judge-requested
revision — and only the implementer converts it back to ready, which is its declaration that the
round is finished. Because the orchestrator stores nothing durable, "is this round done?" has to
be answerable from GitHub alone, and `isDraft` is the one native boolean that answers it every
round rather than once per issue.

## Considered options

**Treating the existence of the pull request as the completion signal.** This was the first
answer and it works exactly once. Every later round — a judge asking for changes, a red CI run
sent back for repair — leaves the same observable picture: commits stacked on top of a stale
review, with no way to tell "finished the requested changes" from "committed halfway and handed
off to a successor". A handoff document cannot break the tie either, because handoffs are
deliberately not an input to any orchestrator decision (see
[0001](./0001-isolated-worktree-and-handoffs-outside-git.md)). The signal has to be repeatable,
one per round.

**A label the orchestrator writes**, or **assigning the pull request to whichever role currently
holds it.** Both work mechanically and the assignee version is pleasantly readable, but both are
the orchestrator writing down what it believes and then trusting its own note. That is durable
orchestrator state wearing a GitHub costume, and it can silently disagree with reality. Deriving
the same fact from a flag GitHub already maintains cannot.

**A sentinel in the title or body**, matched by string. Fragile the moment a human edits the pull
request, and it makes the machine parse prose — which nothing else in it does.

**Always re-reviewing whenever new commits appear.** Self-healing and stateless, but it means the
reviewer reads half-finished trees, and the handoff-and-resume path never fires at all because
the loop always moves forward instead of continuing the interrupted round.

## Consequences

Implementation dispatch is one state rather than three. First pass, CI repair and revision are
all just "the pull request is a draft", so the machine does not encode *why* it is implementing;
the implementer receives the whole observable picture and the judge's latest verdict stands as
the live instruction until superseded.

The pull request is opened mechanically by the orchestrator under the implementer's identity, at
the first observed commit, with a placeholder title constructed to satisfy the repo's title lint.
This amends the roster decision, which had the implementer opening it. Ownership is unchanged —
what matters there is that the implementer is the author, so GitHub's refusal to let an actor
approve its own pull request still bites — but the *act* is no longer an agent's. Nothing has to
invent a conventional-commit title before the work is done.

Merge is locked by the platform for free: GitHub refuses to merge a draft, so no orchestrator
policy is needed to prevent merging mid-revision.

Converting to draft was measured to be inert — reviews, their states, their pinned SHAs and their
timestamps all survive it byte-identically, and a GitHub App can drive both directions with only
`pull_requests: write`. The one path where conversion *is* destructive is pending review
requests, which GitHub drops. Nothing here may come to depend on review requests as signal.

Two flag transitions per round land in the pull request timeline as `convert_to_draft` and
`ready_for_review` events, which makes implementation rounds countable and stalls measurable
without the orchestrator remembering anything. Their timestamps are only second-resolution and do
collide, so ordering must come from the monotonic event id.

## The machine reads primitives, never computed summaries

`reviewDecision` is not read anywhere, and neither is any other field GitHub derives on our
behalf. Verdicts are read from the reviews list, filtered by the numeric id of the acting
identity, and freshness is established by comparing each review's pinned commit SHA to the
current head.

This is not defensive style. `reviewDecision` was observed to be `null` on this repo while an
`APPROVED` review sat plainly in the reviews list, because a branch protection rule requiring
zero approvals makes GitHub stop computing the field. A machine gated on it would refuse to merge
and give no reason. Filtering by *numeric* id rather than login matters for the same reason: the
REST and GraphQL surfaces disagree on whether a bot's login carries the `[bot]` suffix, so a
string comparison across them silently matches nothing.

The corollary is that an observation must be coherent before it is trusted. A pull request's head
SHA lags a push by several seconds while GitHub reports `mergeable_state: "unknown"`, and during
that window a review pinned to the *previous* head compares as current. The machine takes no
action on an unsettled observation.
