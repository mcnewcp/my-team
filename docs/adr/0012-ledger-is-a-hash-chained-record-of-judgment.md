# The Ledger is a hash-chained record of judgment

A Reviewer submits an attributable native pull-request review containing a closed machine
envelope. The envelope binds the pull request, frozen **Contract** digest, reviewed head and delta
base; a digest of those values is the **Review round** identity. The native verdict must agree
with the envelope. The first Review round covers the base-to-head diff, while every later Review
round starts at the preceding accepted head.

Every new **Finding** names one blocking-eligible defect class — correctness, Contract violation,
security or data loss — and states the actual behavior, expected behavior and consequence. It
also carries one primary changed-line location at the reviewed head and at least one
commit-pinned evidence link. Its machine identity is a digest of the governing Contract criterion
or rule, path, stable symbol anchor and failure mode; wording, evidence and line numbers may
change without changing identity. The **Ledger** assigns a never-reused short display label only
after accepting the Finding.

The Judge decides every new Finding in one complete transaction. Its immutable **Disposition** is
`blocking_now`, `follow_up` or `dropped`; a referenced follow-up issue must exist before the
transaction is written. A blocking Finding remains live until a later accepted review proves it
resolved, while follow-up and dropped are terminal. Every later review accounts for each live
blocker exactly once as a resolution or continuation. A continuation preserves the original
identity and Disposition.

Every accepted Review round is incorporated into the Ledger before integration. When an
`APPROVED` review resolves prior blockers and introduces no new Findings, its whole snapshot
records those resolutions without inventing a subjective Disposition. The Ledger remains under
the Judge Principal; which pipeline Action performs this non-discretionary projection is left to
the State and Auditor/Integrator boundary decisions.

The Ledger is one Judge-authored pull-request conversation comment. One closed JSON authority is
rendered as readable Markdown, and every mutation replaces the whole projection with a snapshot
whose contiguous revision names the preceding digest and a content-derived mutation identity.
After a snapshot is accepted, the Judge dismisses its native `CHANGES_REQUESTED` review with a
pointer to the canonical comment URL, revision and digest. That both clears the platform blocker
and anchors the mutable comment from a native review artifact.

Recovery discovers candidates by exact sentinels, pull-request identity and the expected Judge
Principal. The lowest comment ID is canonical only when every duplicate has byte-identical
genesis; the current body, GitHub edit history, hash chain and dismissal anchors must all agree.
An exact review retry aliases the earliest identical native artifact, and an exact Judge retry is
a setter. Stale reviews remain visible but receive no round number and consume none of the cap.
Divergent retries, malformed submitted reviews, terminal re-raises, unchanged-delta Findings,
partial Disposition sets, foreign edits, deletion, broken chains and concurrent sibling writes
escalate rather than being guessed through. A blocker that survives the configured Review round
cap also escalates; no extra subjective sample is bought.

## Considered options

**Let the Reviewer preserve a hand-authored Finding ID.** Fresh Reviewers can change wording or
forget prior labels, making identity depend on model memory. A digest over the semantic subject
and code anchor makes repeats mechanically recognizable while leaving short labels readable.

**Append one Ledger comment per mutation, or trust the current mutable body.** Append-only
comments would scatter the current decision across the conversation and still could be edited;
trusting only the latest body would hide replacement, deletion and last-write-wins races. A single
whole-snapshot projection stays readable, while its hashes, native edit history and dismissal
anchors retain enough independent evidence to reject corrupted history. GitHub's inability to
[pin a pull-request conversation comment](https://github.com/mcnewcp/my-team/issues/103) is why
discovery and native anchors are part of the protocol rather than UI convention.

**Resolve concurrent Judge writes by last-write-wins or a three-way merge.** Two sibling snapshots
can make different legitimate Dispositions, and no mechanical merge rule has authority to choose
between those subjective decisions. Detecting the fork and escalating preserves the evidence and
keeps recovery deterministic.

## Consequences

The Ledger is GitHub evidence, not locally remembered orchestrator State, so crash recovery reads
and validates it from scratch. Only protocol-valid, current samples count as Review rounds; exact
retries and stale samples cannot exhaust the subjective-review allowance, while a submitted
protocol violation terminates in escalation rather than soliciting a replacement opinion.

This replaces the older assumptions that the Judge submits the formal native verdict, that all
draft-latched work shares one kind of Round, and that the trust boundary contains exactly two
Declarations. It does not decide the pipeline-State representation or the mechanical boundary
between Auditor and Integrator.

The Product Owner accepted the
[interactive Ledger protocol prototype](https://github.com/mcnewcp/my-team/blob/0d2c424dff4946576a2820abfaf78afc43e61e04/prototypes/ledger/ledger-logic-prototype.html)
as the detailed schema, readable rendering and executable edge-case record. Production must use
RFC 8785 canonicalization rather than the prototype's fixture-sized canonicalizer.
