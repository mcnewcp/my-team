# Pipeline State is a label-backed cursor

Pipeline **State** is a durable GitHub label-backed cursor, not a value recomputed from artifacts
on every tick and not a label trusted as proof of work. Native artifacts corroborate whether a
transition is legal and, outside explicitly directed State repair, combine with State to derive the
next **Action**; narration never enters that decision. This deliberately supersedes ADR-0009's
rejection of orchestrator-written State labels while preserving its load-bearing boundary: GitHub
is the sole durable source of truth, and no local orchestration memory selects an Action.

A settled State has exactly one label on the issue, and the pull request never mirrors it. The
fixed taxonomy is `my-team:contracting`, `my-team:awaiting-contract-approval`,
`my-team:needs-clarification`, `my-team:implementing`, `my-team:auditing`, `my-team:reviewing`,
`my-team:judging`, `my-team:remediating`, `my-team:integrating`, `my-team:escalated` and
`my-team:merged`. Transient conditions such as unsettled observations, missing or stale artifacts,
CI waits, conflicts, invalid authorization and exhausted limits derive Actions instead of gaining
State labels.

The orchestrator alone changes State, under whichever control **Principal** the authority model
assigns later. Generative **Roles** produce attributable artifacts and the **Product owner**
performs approval or authorization acts; neither moves the cursor. Keeping the label on the issue
avoids a mid-run carrier change, while refusing a pull-request mirror avoids two authorities that
GitHub cannot update transactionally.

Each visit to a State is a distinct **State occurrence** identified by the latest attributable
application of its destination label. Its direct entry evidence includes the artifact that made
that edge legal and the adjacent source transition in the label timeline. Exit evidence must bind
that occurrence, its entry artifact or the row's explicit ordering boundary; an old artifact does
not become current merely because it has the right shape. This uses direct transition history to
recover the incoming edge without replaying the whole pipeline or writing another marker. An
explicit State repair is the sole exception: a fresh target application made under the Product
owner's direction, plus the target's validated non-Authorization bindings, substitutes for the
adjacent source edge that quarantine cannot supply.

State names the responsibility that owns the next work and is entered before its Action begins.
If a crash lands after entry but before dispatch, recovery can safely dispatch that Action; if it
lands after the Action's artifact but before advancement, recovery observes the artifact and
advances without repeating completed work. The label therefore records ownership, while the
artifact remains the evidence of completion.

State moves only along this directed graph:

```text
(no prior State) --authorization--> contracting

contracting ----------------------> needs-clarification
needs-clarification --response----> contracting
contracting ----------------------> awaiting-contract-approval
awaiting-contract-approval
  |--approval---------------------> implementing
  `--rework-----------------------> contracting
contracting --approval disabled---> implementing

implementing ---------------------> auditing
auditing -------------------------> implementing | remediating | reviewing
reviewing ------------------------> judging | integrating
judging --------------------------> remediating | integrating
remediating ----------------------> auditing
integrating ----------------------> merged

any ordinary nonterminal State ---> escalated
escalated --reauthorization-------> interrupted State
```

`merged` has no outgoing edge. Manual issue closure not explained by an expected merge, closing its
pull request unmerged, deliberately removing its Queue label, observing an unsettled GitHub
projection, or waiting on CI stops or delays the loop without changing State. Ordinary recovery
moves only along a legal edge; explicitly directed State repair is the sole exceptional replacement
and is never inferred.

The first application of `implementing` freezes the immediately preceding canonical Contract
Candidate and closes its revision chain. Source-label removal, a later settled observation,
dispatch, a commit and pull-request creation are all too late to define that boundary. Later
returns to `implementing` retain the same frozen Contract; a post-freeze Contract edit or
successor, source-body change, approval withdrawal or conflicting rework reaction breaks the
Invariant spine and escalates.

`implementing` is valid before a branch or pull request exists. Until a deliverable commit is
visible, it continues to dispatch the Implementer. The first commit on the expected implementation
branch makes opening one draft pull request the next mechanical Action while State remains
`implementing`; that canonical pull request then permanently joins the Invariant spine and binds
the source issue and frozen Contract. Missing, duplicate or mismatched pipeline pull requests
escalate after that boundary, while closing the canonical pull request unmerged halts. The branch
and pull-request contract decides their exact names, schema and author separately.

When `remediating` owns more than one live `blocking_now` Finding, it selects the oldest in
canonical Ledger order and dispatches the Remediator for that Finding alone. Incidental changes
do not resolve another Finding; only a later accepted Review round can do so.

While State remains `auditing`, a coherent advance of the otherwise-valid canonical branch keeps
ownership in `auditing`, makes prior-head Audit runs historical and requires Audit evidence at the
new head. Entry into `reviewing` pins the successfully audited head; a later push then breaks the
Entry invariant and escalates. Foreign or branch-contract-invalid mutations escalate in either
State.

After a protocol-valid `APPROVED` Review round, `reviewing` retains ownership until a deterministic
Ledger setter under the expected Ledger authority has incorporated that exact round, creating
genesis if necessary. No subjective Judge dispatch is required. Only the valid projection permits
the direct edge to `integrating`; later decisions choose the implementing component and concrete
Principal.

GitHub offers no atomic replacement scoped only to the State-label namespace. A transition
therefore adds the legal destination and stops; the next tick reobserves the adjacent pair,
validates that the transition-owning Principal added the destination, removes the source and
stops; only a third observation acts in the settled destination. Removing first would create a
zero-State crash window, while replacing the issue's complete label set could overwrite a
concurrent triage change. An ambiguous add or remove response is harmless: the next observation
either proves the mutation landed or retries the same idempotent operation.

If an independent non-merge fault becomes visible while a legal adjacent State pair is in
progress, recovery finishes that pair before escalating from its destination on a later tick.
Adding `escalated` to the pair would turn a recoverable transition into three-label corruption. A
merge is the terminal exception: only a coherent expected merge observed from settled
`integrating`, or the attributable `integrating -> merged` pair that observation created, may
advance or finish normally. Every other observed merge quarantines the existing State-label set
unchanged until explicit repair to `merged`; settling another pair first could erase the
cross-object fact that the merge was unexpected. A pair that is not attributable and legal is
already State corruption and is quarantined instead.

Outside a derived repair hold, recovery accepts only three State-register shapes. An authorized
issue with no current or historical State label and no pipeline artifacts is untouched and
initializes to `contracting`.
Exactly one recognized label is settled when its latest application is attributable to the
transition-owning Principal. Exactly two are a transition in progress when the later attributable
application forms a legal edge from the earlier label; absent quarantine, recovery removes the
source. A missing
State after initialization, an unknown `my-team:*` value, a foreign-authored application, a
nonadjacent pair or three or more State labels is **State corruption**. Recovery preserves that
evidence and quarantines the issue rather than inferring a replacement from artifacts. Because
there is no valid source State, State-corruption quarantine does not add `escalated`. Unexpected
merge quarantine likewise preserves even a valid singleton or adjacent pair because terminal
cross-object ordering cannot be reconstructed. Either quarantine ensures the human Queue and an
attributable notice-completion anchor on the issue timeline while making its human-readable notice
available and dispatching nothing. The Product owner must direct an explicit orchestrator-mediated
repair before ordinary reauthorization can resume.

The existing triage labels are a **Queue projection**, not another source of State. In ordinary
operation, `ready-for-agent` covers `contracting`, `implementing`, `auditing`, `reviewing`,
`judging`, `remediating` and `integrating`; `ready-for-human` covers
`awaiting-contract-approval`, `needs-clarification` and `escalated`; `merged` carries neither.
Quarantine and every repaired nonterminal target remain human-queued until fresh Authorization.
The first trusted-human application of `ready-for-agent` opens the Authorization epoch. Later
orchestrator-authored queue changes are distinguishable by actor and never authorize, so the
projection can follow ownership without weakening the human admission boundary.

Each human-owned State has one attributable exit act, and none requires parsing prose.
`needs-clarification` returns to `contracting` on the first new Product owner issue comment after
the canonical Contractor clarification request; only the comment's author, ID and ordering enter
the machine, while its body is prompt input. On the current valid Contract Candidate, Product
owner `+1` advances `awaiting-contract-approval` to `implementing`, while `-1` returns it to
`contracting`; both reactions together escalate. `escalated` returns to its interrupted State only
on a trusted-human `ready-for-agent` application ordered after that occurrence's notice-completion
anchor in the issue timeline, which opens a new Authorization epoch.
Quarantine rejects ordinary reauthorization until repair has produced one valid target State.

A Product owner response or reaction remains current when it arrives after its bound clarification
request or on its current candidate but before the corresponding human-owned State settles.
Artifact binding and within-timeline ordering, not destination-label time, establish its freshness.

Invalid Authorization escalates only an ordinary settled nonterminal State. Before initialization
it selects no State write; in `escalated`, `merged`, quarantine and the post-repair human hold, its
absence is expected and cannot trigger another transition. A repaired nonterminal target does not
evaluate its ordinary table row until qualifying later Authorization exists and its Queue is
reconciled.

Every State validates a cumulative **Invariant spine** plus its direct entry artifact. The spine
retains the canonical Contract and source-body binding, issue and pull-request identity, expected
Principals, closed artifact envelopes and all still-relevant head or digest bindings; each
hash-chained artifact validates its own history without replaying every State transition. Queue
membership and intentional halt controls are evaluated separately rather than being mistaken for
entry evidence.

Queue drift is not repaired blindly from State. Recovery completes an attributable interrupted
orchestrator projection, but a trusted human's removal or mismatch halts without moving State.
Applying `ready-for-agent` cannot bypass the clarification response, Contract reaction or explicit
State repair required by a human-owned State. Foreign or unattributable queue mutations fail
closed with an attributable issue-timeline notice anchor. This keeps queue labels useful as a
human pause control even though they are not State.

The latest attributable destination-State application itself proves the one corresponding Queue
projection currently owed, even before its first Queue mutation. That crossover is not deliberate
drift: recovery adds the destination Queue label, reobserves, removes the source Queue label and
reobserves. A later higher-precedence State transition supersedes an uncompleted earlier projection,
so recovery reconciles directly to the latest target rather than replaying obsolete routing. When
both State and Queue transitions are owed, the State pair settles first; no destination Action
dispatches before its Queue projection settles. A same-owner transition needs no Queue mutation,
while `merged` only removes the remaining Queue label. A repair-applied
destination is excluded: every non-`merged` target remains on the human Queue until a later
trusted-human `ready-for-agent` event ordered after the target application. Reauthorization is
then reconciled after State settlement: an automated destination removes `ready-for-human`, while
a human-owned destination removes the triggering `ready-for-agent` but retains its trusted event
as Authorization. Any other later human Queue event wins and halts.

For a valid State register, artifacts are partitioned into that State's **Entry invariant** and
**Exit evidence**. On a coherent Observation, broken entry evidence escalates instead of rolling
State backward. If entry remains valid, absent or incomplete exit evidence continues, waits or
retries the current Action; exactly one protocol-valid exit advances one edge; malformed or
conflicting current exits escalate. Valid artifacts bound to older Contract revisions, heads or
Review rounds remain historical evidence and never move current State. Thus a push after
`reviewing` was entered at an audited head breaks its Entry invariant and escalates rather than
silently returning to `auditing`.

## Per-State contract

The table below runs only after the global precedence checks. “Current” means bound to the
canonical issue and pull request, frozen Contract, expected Principal, current State occurrence
and any head, delta or Ledger identity the artifact's protocol requires. Event IDs order facts
within one GitHub timeline; cross-object freshness comes from protocol bindings and direct entry
artifacts rather than timestamp comparison. Stale artifacts remain history; malformed or
conflicting current artifacts escalate. Exact schemas, credentials and merge mechanics remain
with their dedicated decisions.

For every ordinary nonterminal row other than `escalated`, re-entry from `escalated` wraps the
listed entry rule: trusted-human Authorization is the new direct entry artifact, while the
interrupted occurrence's underlying entry bindings and State-local Action identity are inherited
and revalidated. That includes an open or not-yet-open producer latch, Audit producer and
remediation target, so reauthorization resumes an interrupted producer cycle rather than opening a
new one. State repair may similarly target any permitted row, but its fresh target application
substitutes only for the missing adjacent source edge; all other target bindings except active
Authorization validate before application, and Authorization follows separately. Neither wrapper
lets a compatible snapshot stand in for preserved direct evidence.

| Stored State | Direct Entry invariant | Exit evidence and State-local Action |
| --- | --- | --- |
| no prior State | The issue is open and coherently observed; Authorization is valid; no State label has ever existed; and no pipeline branch, pull request or protocol artifact exists. | Eligibility selects the one Action of adding `contracting`. Any pipeline artifact makes this corruption, never initialization by inference. |
| `contracting` | The occurrence follows untouched Authorization, the first Product owner response to its entering clarification request, or `-1` on its entering Contract Candidate. The Authorization epoch, issue identity and source body remain valid. | The latest valid canonical candidate created after this occurrence selects `awaiting-contract-approval`, or `implementing` when approval is disabled. One current Contractor clarification request selects `needs-clarification`. If neither exists, dispatch Contractor; if both or either is malformed, escalate. |
| `needs-clarification` | Its canonical, unedited Contractor request remains valid and no competing candidate from the source occurrence exists. | The first later Product owner issue comment selects `contracting`; otherwise wait. Only author, event ID and ordering are machine input, while the body is prompt input. |
| `awaiting-contract-approval` | Approval is enabled and the latest valid pre-freeze Contract chain, candidate and source-body binding remain valid. A contiguous successor becomes current and makes older reactions stale. | On the current candidate, Product owner `+1` alone selects `implementing`, `-1` alone selects `contracting`, neither waits and both escalate. Other actors' reactions do not move State. |
| `implementing` | First entry follows the current candidate's approval or approval-disabled publication and freezes it; later ordinary entries follow a failed Audit whose recorded producer was `implementing`. The frozen spine remains valid. | Before the canonical PR exists, dispatch Implementer until the branch/merge contract's PR-creation predicate holds, then perform the abstract open-draft-PR Action. For an established non-draft PR without a current latch opening, perform the abstract open-draft-latch Action; with the current latch open and PR draft, dispatch Implementer. A fresh valid producer completion selects `auditing`. |
| `auditing` | A fresh completion from `implementing` or `remediating` identifies the producer to which failure returns; the canonical PR and frozen spine remain valid. | Until one valid terminal result exists for the current-head Audit identity, start, wait for or resume that single Audit Action as its protocol requires. A valid `success` selects `reviewing`; a valid `failure` selects the recorded producer State. A coherent valid head advance changes the Audit identity and makes prior-head runs historical. |
| `reviewing` | The occurrence follows one accepted passing Audit at coherent head H; H remains current and the valid prior Ledger determines the exact delta base. | With no protocol-valid Reviewer artifact bound to that passing Audit identity, dispatch Reviewer. Current `CHANGES_REQUESTED` selects `judging`. Current `APPROVED` first selects the deterministic Ledger setter while its round is absent there, then selects `integrating` once incorporated. |
| `judging` | The occurrence follows the unique current `CHANGES_REQUESTED` Review round; its head and prior Ledger remain valid. | While the one whole next Ledger snapshot, prerequisite follow-up issues and native dismissal anchor do not yet validate, dispatch or resume that one Judge transaction. Zero live blockers selects `integrating`; live blockers below the configured Review-round cap select `remediating`; a blocker at the cap selects `escalated`. |
| `remediating` | Entry follows either the valid Judge snapshot that selected remediation or a failed Audit whose recorded producer was `remediating`. The current Ledger contains at least one live `blocking_now` Finding below the cap; the oldest in Ledger order is this occurrence's target. | For an established non-draft PR without a current latch opening, perform the abstract open-draft-latch Action; with the current latch open and PR draft, dispatch Remediator for that one target. A fresh valid producer completion selects `auditing`; only a later accepted Review round resolves Findings. |
| `integrating` | Entry follows either the incorporated `APPROVED` round from `reviewing` or the valid zero-blocker Judge transaction from `judging`. The exact current head is audited and reviewed, every accepted round is incorporated in the valid Ledger, every required dismissal and follow-up anchor exists, and no live blocker remains. | An expected exact-head merge selects `merged`. An unsettled final projection waits and a definitive failure of required integration evidence escalates. While evidence is settled and not definitively failed, absence of that merge selects the abstract Integrator Action against the head required by the branch/merge contract. There is no backward edge. |
| `escalated` | An ordinary legal transition from exactly one valid interrupted State occurrence remains attributable and its escalation evidence remains identifiable. | Complete the human Queue projection. Until an attributable notice-completion anchor bound to this occurrence exists on the issue timeline, perform or retry the abstract notice Action; then wait. The first valid trusted-human Authorization ordered after that anchor selects exactly the interrupted State; its inherited Entry invariant is revalidated after settlement and may escalate again. Only anchor attribution, occurrence binding and event order are machine input; its exact encoding and the notice's carrier, schema and rendering belong to the CLI contract, and narrative content is never parsed. |
| `merged` | Either an expected native merge after the owning `integrating` occurrence binds its exact head and authority, or an explicit State repair acknowledges coherent canonical-PR merge evidence that was unexpected. | There is no Role Action or outgoing edge. Remove both Queue labels. Branch, issue, workspace, summary and process-exit cleanup belong to the branch/merge and CLI contracts. |

Each ordinary `implementing` or `remediating` producer cycle consumes one attributable draft-latch
opening. Mechanical creation of the canonical draft pull request opens the first `implementing`
cycle. A cycle entered from failed Audit consumes the first unconsumed `convert_to_draft` event
after the `ready_for_review` completion bound into that Audit; Judge-selected remediation consumes
the first such event after its entering Review round. Those anchors and latch events share the
pull-request timeline, while protocol bindings connect the Audit, so no issue-to-pull-request
timestamp comparison is used. Re-entry from `escalated` inherits the interrupted cycle's open or
not-yet-open latch rather than consuming another. Completion requires the pull request to be
non-draft and an expected-producer `ready_for_review` event ordered after its opening within that
timeline. Older ready events cannot complete a later cycle.

The Audit protocol's candidate identity must bind the expected Principal, canonical pull request,
frozen Contract, coherent head and `auditing` occurrence. Its later contract chooses how evidence
is collected, retried and encoded, which terminal conclusions are valid, and how conflicts are
recognized. Until that contract yields one valid terminal outcome, `auditing` retains ownership
while its Audit Action starts, waits or resumes without inventing another State.

Raw Reviewer artifacts, not `reviewDecision`, supply review evidence. ADR-0012's exact retries
alias the earliest identical artifact, stale samples consume no Review round, and divergent or
malformed current samples escalate. A partial Judge transaction likewise retains `judging`; its
idempotent setter completes the same transaction rather than starting another one.

State repair is an explicitly invoked exceptional Action. For State corruption, the Product owner
direction names one non-`escalated` target; for an unexpected merge, it can name only `merged`.
One repair invocation supplies the same direction and target to every tick, and its CLI shape is
decided later. If it stops before the fresh target application, ordinary ticks remain quarantined
and continuation requires another explicit invocation rather than remembered input.

Before the first State-label removal, repair completes the human Queue projection and attributable
issue-timeline anchor for the quarantine notice. Every target identity and artifact binding other
than active Authorization is revalidated on each observation.
The persistent quarantine cause plus attributable cleanup history keeps every intermediate
register — even an otherwise legal pair, singleton or empty set — in the repair hold ahead of
ordinary register, Queue and invalid-Authorization rules. Without a direction it waits; with one it
removes every current State-namespace label in lexical name order, one mutation and reobservation
at a time, then freshly applies the target. No intermediate shape initializes, reauthorizes,
advances or dispatches, and only that fresh application after the empty register completes repair.

A repaired producer target may inherit one uniquely valid surviving latch and work binding;
otherwise an established draft pull request invalidates that target, while a non-draft pull request
can open a fresh latch after reauthorization. A repaired nonterminal singleton remains human-queued
and unauthorized until a separate trusted-human `ready-for-agent` event ordered after its
application restores Authorization; until then it cannot evaluate an Entry invariant, Exit evidence
or Action from its ordinary row. Repair to `merged` instead requires coherent terminal merge
evidence and projects no Queue. The issue timeline preserves the quarantined set and every repair
mutation, so no extra repair marker is written.

Only State and Queue projections are orchestrator-written cursors. Authorization, State
occurrences and incoming edges, the interrupted State, current Contract revision and frozen
binding, canonical branch and pull request, current head, producer return target, Audit candidate,
Review-round identity and delta base, Ledger blockers and round count, integration readiness and
the next ordinary Action are derived from native events and protocol artifacts. The repair target
is exceptional Product owner input resupplied on every repair tick. Protocol artifacts may bind
the derived identities needed to prove their own Actions, but no extra cursor stores an independent
copy.

Each tick evaluates one fresh Observation and selects at most one Action in this fixed precedence:

1. Parse State labels, Queue labels, Authorization events and their actors without writing.
2. Recognize an expected exact-head merge only from a coherent settled `integrating` occurrence,
   before the issue closure or Queue removal caused by that merge. Treat an attributable
   `integrating -> merged` pair as the pending transition already created by such an observation;
   classify every other observed merge as unexpected terminal quarantine.
3. Honor manual issue closure, a closed-unmerged pull request and deliberate Queue removal or
   mismatch as no-write halts; an owed State-caused projection, valid reauthorization or explicit
   repair hold is not deliberate drift.
4. Maintain quarantine before ordinary State and Authorization semantics: select one owed human-
   Queue mutation or issue-timeline notice-anchor Action, then, only after both are complete and
   while a valid explicit repair direction is supplied, select one repair mutation; otherwise
   wait. A repaired
   nonterminal target likewise waits for qualifying later Authorization and Queue reconciliation
   before ordinary evaluation. From an ordinary settled nonterminal State, escalate invalid
   Authorization, foreign mutations and other faults. State corruption and unexpected merges
   preserve their labels in quarantine, while an independent non-merge fault beside a legal
   adjacent pair waits for step 5 and is reevaluated from the destination.
5. Complete one attributable in-progress State transition mutation; only when none is owed,
   complete one attributable Queue transition mutation. Then stop and reobserve.
6. Wait while any pull-request, head or check projection required by the remaining candidates is
   incoherent.
7. Initialize an untouched issue only after a coherent Observation proves no pipeline artifacts
   exist; otherwise validate the cumulative Invariant spine and direct Entry invariant, escalating
   on failure.
8. Interpret Exit evidence: one valid exit advances, pending evidence waits, absent evidence keeps
   current ownership and conflicting evidence escalates.
9. Apply convergence limits before repeating an Action whose Exit evidence remains absent.
10. Perform exactly one selected Action and exit the tick.

This ordering gives human controls and irreversible terminal truth precedence without letting an
artifact-dependent mutation use an incoherent snapshot.

## Considered options

**Derive State entirely from artifacts.** This preserves the former pure-derivation model but
leaves no durable ownership cursor when several facts are simultaneously true.

**Trust the State label without corroboration.** This turns stale or malformed bookkeeping into
proof that work completed.

**Store State on the pull request or mirror it across both objects.** A pull request does not exist
at the start of the pipeline, while mirroring creates a new cross-object reconciliation problem.

**Let each Role advance its own label.** This makes the generative actor self-certify the fact that
should release the next Role.

## Consequences

State recovery needs no local checkpoint, but every occurrence must remain bound to native GitHub
evidence before its cursor can advance. Transitions take multiple ticks and therefore more API
round trips; in return, every mutation is attributable, reobservable and safe to resume after a
crash.

Corrupt State labels and unexpected merges cannot be guessed through. They stop automated work
and require explicit Product owner repair, while concrete credentials, artifact encodings, Audit
mechanics, branch and merge policy, and CLI behavior remain decisions of their downstream
contracts.
