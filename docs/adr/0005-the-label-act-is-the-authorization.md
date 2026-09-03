# The label act is the authorization

> **Supersession note:** [ADR-0013](./0013-pipeline-state-is-a-label-backed-cursor.md) retains the
> trusted-human label act as Authorization but narrows its boundary to ordinary pipeline advancement
> and dispatch from a settled nonterminal State. Transition recovery, quarantine, explicitly
> directed State repair and terminal bookkeeping may act while unauthorized; ADR-0013 replaces the
> old ladder row numbers below. Reauthorization from `escalated` must follow that occurrence's
> attributable issue-timeline notice anchor, while post-repair Authorization must follow the
> freshly applied target State.

An issue enters the loop when a trusted human applies `ready-for-agent`; who *authored*
the issue does not matter. GitHub enforces that only triage-or-above can apply a label, so
the label is already proof that someone with write access read the issue and vouched for
it — and authorization additionally requires that the issue body carry no edit by an
untrusted editor since that label event, which closes the window in which the author could
rewrite what was vouched for. A human is trusted when GitHub reports their
`authorAssociation` on the target repo as `OWNER`, `MEMBER` or `COLLABORATOR`; trust is
derived from the platform on every read rather than listed in config.

The provocation was a live incident. On 2026-08-16 an account with no write access opened
six issues on this repo (#17–#22), including a full ADR, three implementation tickets
written in the shape `/to-issues` would produce, and a ticket asking the maintainer to
grant its integration repository write access. It cost them nothing, and `my-team` is
being built to read `ready-for-agent` issues and drive them to a merged pull request with
no human in the loop — which makes the tracker not just a tracker but the orchestrator's
instruction surface, world-writable on a public repo. The accidental gate held: none of
the six was ever labelled. This decision makes that gate deliberate.

## Considered options

**Gating on the issue's author.** The obvious reading of "whose text may an agent act on",
and it fails the case the incident obscures: an outsider files a genuinely excellent issue
and the maintainer wants it worked. Under author-gating the only remedy is re-filing it
under a trusted login, which discards the reporter's attribution to satisfy a check the
maintainer has already performed by hand. The labeller read the issue; that is what
vouching is.

**The conjunction — trusted author *and* trusted labeller.** Strictly safer, and it buys
nothing: the labeller's act already asserts everything the author check would establish,
and the conjunction forbids the good case above for no additional guarantee.

**A `trusted_humans` allowlist in config**, which is what the failure-and-budget policy
originally specified — logins resolved to numeric ids at load. Rejected for maintenance:
it drifts against the repo's real collaborator list, needs its own `doctor` validation,
and cannot express "we added a collaborator this morning." The derived predicate is free
on every issue, comment and review payload and is always current.

**The `permission` API** (`repos/{owner}/{repo}/collaborators/{user}/permission`, requiring
`write` or `admin`) is the exact primitive `authorAssociation` approximates. Rejected for
the per-tick path: one call per distinct author where the association is already in hand,
and it is blind to Apps regardless. It is used once, in `doctor`, where exactness is worth
a round trip.

**Halting silently when the gate trips**, writing nothing at all, so that nothing an
outsider does can provoke the orchestrator into acting. Rejected because escalation *is*
the un-authorization: swapping `ready-for-agent` for `ready-for-human` is precisely the
right response to "this authorization is no longer valid", and
[0003](./0003-escalation-swaps-the-labels.md) already makes the swap back the
re-authorization. The provoked write is self-limiting — once escalated, `ESCALATED`
catches every subsequent tick, so it is one write per re-authorization rather than a loop.

## Consequences

**This is authorization, not injection defence, and the distinction is the part most
likely to be misread.** The boundary decides what may *enter* the loop. It does not make
an agent immune to hostile prose, and the surfaces it does not cover are the larger ones:
CI logs, dependency READMEs, `.md` files on a contributor's branch, and whatever
`/research` fetches from the open web. The real containment is structural and was decided
elsewhere — no prose is parsed anywhere in the state machine
([0002](./0002-draft-flag-is-the-implementer-latch.md)), role authority lives in the
credential where GitHub enforces it, and GitHub itself refuses a self-approval. Injected
prose can steer what an agent writes; it cannot move the ladder. The harness seam
knowingly accepted that role keys are readable by the dispatched agent, and this decision
does not mitigate that.

**The ladder gains `UNAUTHORIZED` at row 3, directly under `HALTED`, and goes to nineteen
rows.** Authorization is a precondition on acting at all, so it is checked before the
ladder reasons about the work — above `AMBIGUOUS`, so "your authorization is bad" beats
"you have two branches" as the escalation message. It is safe above `OBSERVATION_UNSETTLED`
because the predicate reads only issue-level fields, the label timeline and the body's
`lastEditedAt`, never the eventually-consistent head SHA that row guards. Placing it below
`MERGED` was considered, mirroring `NOT_CONVERGING`; it was not worth the weaker principle,
since `MERGED` is terminal and clears the label on the next tick anyway.

**Untrusted reviews leave the Observation entirely.** On a public repo GitHub permits
anyone to submit a formal review, including `APPROVED`, so `AMBIGUOUS`'s "formal review
from an unrecognised identity" guard let any passerby park the loop by leaving one. A
review from a `User` with an untrusted association is now filtered out at parse — exactly
as untrusted comments are already absent from prompts — and that guard narrows to what it
was written to mean: a `Bot` review from an App id not in config. This also keeps human
approval honest, since an outsider's `APPROVED` must not satisfy it.

**Every GitHub App reads as untrusted, including our own roles.** Measured rather than
assumed: `reviewer-my-team[bot]` submitted an `APPROVED` review reporting
`author_association: NONE` despite being installed with write permissions.
`authorAssociation` is a collaborator-list readout, not a permission readout. Two things
follow. Role identities keep their own mechanism — numeric bot-user ids from config — and
the human predicate never touches them. And the roles fail the human-approval predicate
*structurally* rather than by absence from a list, which is a stronger guarantee than the
allowlist gave.

**Only an actor of type `User` can authorize.** A `ready-for-agent` applied by any App does
not authorize. No `trusted_apps` key ships: an empty key would be code with no second
branch. The widening is named here instead, because the hard part is not the App id — a
planner role that files and labels its own issues makes trust **transitive**, inheriting
its authority from whoever authored the spec it read, and *that* is the boundary that will
need drawing when the triage/planner role arrives.

**`doctor` trades one check for another.** It loses "fail on a `trusted_humans` login that
does not resolve" and gains: call the `permission` API once for `product_owner` and fail
unless it is `write` or `admin` on the target repo. Without it a mistyped `product_owner`
would make the human's own guidance silently invisible to every prompt.

**Comments need no freshness clause, unlike the issue body.** GitHub restricts comment
editing to the comment's author and users with write access, so every possible editor of a
trusted comment is itself trusted. The issue body is different only because its author can
edit it forever regardless of association.

**Re-authorization is re-vouching, not ceremony.** Because the freshness clause anchors on the
most recent trusted-human `labeled: ready-for-agent` event, a human clearing a tampering escalation
has to look at the body as it now stands before swapping the label back. Orchestrator-authored
Queue projections never move that anchor. When clearing `escalated`, the qualifying event must
follow that occurrence's notice-completion anchor; after repair, it must follow the fresh
target-State application. The ritual for acting on an outsider's good issue is the same one act:
label it.
