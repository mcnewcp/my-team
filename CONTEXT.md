# my-team

A thin, locally-running orchestrator that sits on top of AI coding harnesses and drives a GitHub-backed development loop. The human is the product owner; the agents are the engineering team.

## Language

### Repos

**Orchestrator repo**:
This repo — the source of `my-team` itself.
_Avoid_: tool repo, host repo

**Target repo**:
The project `my-team` is pointed at, where issues, PRs and CI live. The CLI is installed into it and run from its root.
_Avoid_: client repo, downstream repo, consumer repo

**Workspace**:
The per-issue directory an agent works in — a `git worktree` of the target repo, plus that issue's
handoffs alongside it. It lives outside every repo.
_Avoid_: sandbox, checkout, workdir

**Fixture repo**:
A repo that exists only to be observed — where a test constructs a real pull request, a real stale review or a real red check run so the orchestrator can be pointed at the genuine article. Holds a small permanent project to work on; everything else in it is generated and disposable.
_Avoid_: sandbox, scratch repo, test repo

### The loop

**Tick**:
One observation of the target repo's state followed by exactly one action, then exit. The orchestrator's primitive unit of work.
_Avoid_: step, cycle, iteration

**Harness**:
An AI coding tool that `my-team` drives to do the actual engineering — Claude Code or Codex.
`my-team` wires Harnesses together; it does not replace them.
_Avoid_: backend, provider, engine, model

**Harness selection**:
The Harness and model selector assigned to one generative Role for an Action. It remains fixed
throughout the Action's continuity chain; Remediator uses Implementer's.
_Avoid_: runtime, provider/model pair, execution slot

**Skill payload**:
The skills `my-team` installs into a **target repo** — the procedures its **roles** run, and the only part of the tool a human can invoke by hand and get the same behaviour from. Membership is a closure: a skill belongs because the loop dispatches it or another payload skill names it, never because it is merely useful.
_Avoid_: bundle, kit, templates, prompts

**Role**:
A bounded responsibility in the delivery pipeline, such as Contractor, Implementer, Auditor,
Reviewer, Judge, Remediator or Integrator. A Role may be performed by a harness session or
mechanically and does not itself imply a GitHub credential.
_Avoid_: stage, worker, bot, agent

**Principal**:
The credentialed identity under which a **Role** acts and GitHub records authority. Multiple Roles
may use one Principal; the responsibility and the identity permitted to perform it are distinct.
_Avoid_: role identity, bot account, actor

**Product owner**:
The human the loop works for and escalates to. One GitHub login per target repo, and the only person the orchestrator ever addresses by name.
_Avoid_: owner, maintainer, user

**Trusted human**:
A GitHub user whose association with the **target repo** is `OWNER`, `MEMBER` or `COLLABORATOR`,
read from the platform on every observation rather than listed in config. Their prose is what an
agent is told to act on and their approval counts; no GitHub App **Principal** is ever one.
_Avoid_: allowlist, trusted user, maintainer

**Action**:
One unit of work a tick dispatches: one **role**, one definition of done. A Harness-backed Action
keeps one **Harness selection** through its whole continuity chain — each stopped session writes a
**handoff** for a fresh successor — and ends only when the Role finishes or fails; several Actions
may belong to the same Role.
_Avoid_: job, step, task

**Review round**:
One current, protocol-valid Reviewer sample of a pull request's permitted code delta. Stale or
exact-retry artifacts remain evidence but do not create another Review round.
_Avoid_: round, iteration, pass, attempt, turn

**Finding**:
A structured, evidence-backed Reviewer claim that one defect exists at a stable code anchor. Its
identity follows the claimed failure rather than its wording, evidence or line number.
_Avoid_: point, comment, suggestion, concern

**Disposition**:
The Judge's immutable decision for one new **Finding**: blocking now, follow-up or dropped. Every
new Finding receives exactly one.
_Avoid_: disposal, verdict, triage, ruling, severity

**Ledger**:
The durable history of adjudicated **Review rounds**, their **Findings**, **Dispositions** and
resolutions for one pull request. It is the record later Roles consult to bound subjective review.
_Avoid_: review log, state file, scratchpad

**Escalation**:
Handing an issue back to the **Product owner** from a valid **State**: the orchestrator moves State
to `escalated`, projects `ready-for-human`, makes a durable notice of what blocked the loop and on
what evidence available, and anchors its completion on the issue timeline before exiting. Only the
anchor's attribution, occurrence binding and event order gate recovery; the human-readable notice
is **Narration**. **State corruption** and an unexpected merge are quarantined instead; halting
stops without asking for anything because the human is already acting.
_Avoid_: failure, abort, bail

**Authorization**:
A **Trusted human** applying `ready-for-agent` to an issue body they have read — the act that opens
an authorization epoch and admits the issue to the loop. Orchestrator-authored queue changes never
authorize; the epoch lapses if the body is edited by an untrusted editor afterwards, and
**Escalation**, State-corruption quarantine or unexpected-merge quarantine revokes it.
_Avoid_: approval, permission, gate, sign-off

### The Contract

**Contract**:
The definition of done for one issue, fixed before implementation. It names the outcomes
that must be proven and the boundaries neither implementation nor review may expand.
_Avoid_: specification, brief, issue body, requirements

**Contract Candidate**:
A validated proposal for a **Contract** that has not crossed its approval boundary. A candidate
may be followed by a correction or successor; it is not yet permission to implement.
_Avoid_: draft contract, proposal, working contract

**Contract Approval**:
The **Product owner** adding `+1` to the current valid **Contract Candidate**, accepting it as the
definition of done and releasing implementation. It is distinct from **Authorization**, which
admits the issue to the loop.
_Avoid_: authorization, sign-off, acceptance

**Contract Rework**:
The **Product owner** adding `-1` to the current valid **Contract Candidate**, returning State to
`contracting` so the Contractor can propose a successor. Explanatory prose informs the Contractor
but never moves State; simultaneous `+1` and `-1` reactions escalate.
_Avoid_: rejection, disapproval, change request

**Acceptance Criterion**:
One stable, falsifiable outcome in a **Contract** that the finished change must prove. A changed
outcome is a new criterion, never a reinterpretation of the old one.
_Avoid_: requirement, check, test

**Test Plan**:
The **Contract's** account of how each **Acceptance Criterion** can be proven, expressed as setup,
action and an observable oracle. It names proof intent rather than implementation-owned tests.
_Avoid_: test suite, test list, QA plan

**Non-Goal**:
A salient outcome deliberately excluded from a **Contract**. It guards a likely scope temptation
without claiming to enumerate everything the issue will not do.
_Avoid_: rejection, omission, backlog item

**Test Budget**:
The **Contract's** hard ceiling on new leaf test cases for the issue. Every case added for an
**Acceptance Criterion** or a demonstrated defect consumes the same finite budget.
_Avoid_: coverage target, token budget, estimate

**Scope Path**:
A repository path boundary naming where the issue may change files and which kinds of change are
allowed. It restricts the delivered diff, not what a **Role** may read.
_Avoid_: working directory, read scope, module

### State and narration

**Observation**:
The single snapshot of the target repo's GitHub state that one tick reads before it acts — the
issue and its timeline, protocol comments and reactions, the remote branch, the pull request and
its timeline, reviews, Ledger and checks at the current head. Local git inside the workspace is
never part of it; an ordinary tick observes once, and everything it decides comes from that
snapshot. A **State repair** tick additionally receives the Product owner's explicit direction,
resupplied rather than remembered across ticks.
_Avoid_: poll, scan, read

**Progress event**:
An externally caused fact proving the issue moved — a new commit, a review submitted, a check run completing. It excludes the draft transitions the orchestrator performs itself: the loop's own bookkeeping is not progress, and counting it as such would let a livelock hold the stall detector open forever.
_Avoid_: activity, heartbeat, update

**State**:
The durable cursor stored throughout the loop as a `my-team:<state>` label on the issue, never on
its pull request; it names the responsibility that owns the next work and is entered before its
Action begins. A settled State has exactly one label, while an adjacent source-and-destination pair
marks a transition in progress. Its values are `contracting`, `awaiting-contract-approval`,
`needs-clarification`, `implementing`, `auditing`, `reviewing`, `judging`, `remediating`,
`integrating`, `escalated` and `merged`. The orchestrator alone moves State; native artifacts
corroborate its entry and exit and prove Role completion, while the cursor alone never proves work
and artifacts never become competing State.
_Avoid_: status, phase, stage

**State transition**:
The orchestrator-owned movement along one edge of the fixed **State** graph: add the destination,
reobserve, remove the source, and reobserve again before acting. Each mutation is an idempotent
tick of its own; escalation may interrupt any ordinary nonterminal State other than `escalated`,
while conditions that merely stop or delay the loop do not move State.
_Avoid_: state swap, status update, phase change, jump

**State occurrence**:
One visit to a **State**, identified by the latest attributable application of its destination
label and the direct entry evidence for that edge. A later return to the same State is a new
occurrence, so artifacts from an earlier visit cannot discharge it merely by looking alike.
_Avoid_: attempt, round, phase instance

**State corruption**:
A State-label set that is neither an untouched issue, one attributable settled State, nor one
attributable adjacent State transition. It is quarantined without changing those labels or
dispatching work; artifacts never guess a replacement, and the Product Owner must direct a
**State repair** before ordinary reauthorization.
_Avoid_: ambiguous State, inferred State, best-effort recovery

**State repair**:
An explicit **Product owner** direction naming the one non-`escalated` **State** that should replace
a corrupt label set, or naming `merged` to acknowledge an irreversible unexpected merge. The
fresh target application made under that direction substitutes for a missing adjacent source edge
only when the target's other identity and artifact bindings validate; repair does not itself
restore **Authorization**.
_Avoid_: reset, inference, automatic recovery

**Queue projection**:
The current `ready-for-agent` or `ready-for-human` triage label derived from who owns the next work:
automation for an active pipeline State, or the **Product owner** for a human-waiting State. It is
tracker routing rather than State or Authorization, and `merged` projects neither label. A repaired
nonterminal State remains human-queued until fresh **Authorization**; only an interrupted
orchestrator-authored projection is repaired automatically, while other drift halts without moving
State so a human queue edit remains an effective pause.
_Avoid_: State label, authorization label, status

**Invariant spine**:
The compact set of durable identity, **Contract**, Principal and artifact bindings that every later
State continues to validate alongside that State's direct **Entry invariant**. Artifact hash chains
prove their own history, so recovery need not replay every preceding State transition.
_Avoid_: transition replay, workflow history, local checkpoint

**Entry invariant**:
The protocol-valid GitHub evidence that made entering one **State** legal and must remain valid
while that State owns the work. Once an Observation is coherent, a broken Entry invariant
escalates rather than moving State backward.
_Avoid_: prerequisite, previous-State output, assumed context

**Exit evidence**:
The protocol-valid GitHub evidence by which one **State** selects exactly one adjacent destination.
Absent or incomplete Exit evidence leaves the current State responsible; stale evidence is history,
while malformed or conflicting current evidence escalates.
_Avoid_: completion label, agent report, inferred progress

**Ladder**:
The ordered list of guarded rows that derives the next **Action** from **State** and an
**Observation**. Its order breaks ties between simultaneously visible evidence, so it is part of
the design rather than an implementation detail; it selects at most one Action per tick and is
data the tests can enumerate rather than a chain of branches. Every row whose Action is a dispatch
has a guard that is the negation of that Action's definition of done, which is what makes a re-fire
a retry rather than a livelock.
_Avoid_: rules, dispatch table, decision tree, chain

**Declaration**:
An observable act by which a **Role** asserts something the orchestrator cannot verify for itself —
the counterpart to **Verify by observation**. A Declaration is always a deliberate API call
attributable to a **Principal**, never prose the orchestrator reads.
_Avoid_: signal, report, claim

**Narration**:
What humans read — the human-readable account of reasoning, progress and events that a future feed
or board view would render. Its payload never selects **State** or an **Action**. Distinct from
State, and free to live outside GitHub as long as it is reachable by a link from it.
_Avoid_: logs, chatter, output

**Sink**:
A consumer of **narration**. Sinks subscribe; nothing in the loop asks one what to do. A tick emits what happened and each sink decides what to render — the terminal shows the whole run, the pull request conversation takes only an action's closing report. A new surface is a new sink, never a new branch in the loop.
_Avoid_: handler, listener, reporter, channel

**Briefing**:
What the orchestrator hands a **role** at the start of an **action**, and the counterpart to its **Report** at the end: only what the role cannot look up for itself — which issue, which identities are in play, which checks are the gate, and where a **handoff** waits. It never names a counter, a limit, or the **state**.
_Avoid_: context block, instructions, preamble

**Report**:
What a **role** says at the end of an **action** — the closing message the orchestrator posts to the pull request conversation on its behalf. It carries what the artifacts cannot: what the role deviated from, the judgment calls worth another pair of eyes, and anything it guessed at or was blocked on. It never restates what the role already wrote to the pull request itself, and like all **narration** it is never an input to an orchestrator decision.
_Avoid_: summary, output, final message, log

**Smart zone**:
The target-repo-wide span of context within which a model is expected to work well, far below its
window's true ceiling. One configurable absolute token count applies to every Harness-backed
**action**; crossing it calls for a **handoff** without ending the action.
_Avoid_: context limit, budget, cap, threshold

**Handoff**:
A context-complete document a stopped Harness session writes for a fresh copy of its own **role**
to continue the same **action**. Lives in the workspace rather than in git, and is never an input
to an orchestrator decision.
_Avoid_: checkpoint, summary, context dump

**Verify by observation**:
Establishing what happened by inspecting the target repo directly — new commits, green tests, a PR that links its issue — rather than by trusting an agent's account of its own work. The rule that governs every state transition the orchestrator can check for itself.
_Avoid_: validation, confirmation

### Proving it

**Acceptance run**:
One issue taken through the whole loop to a merged pull request in a real target repo, unattended — the proof that the tool works, performed on work that was genuinely wanted. Its repeatable counterpart is the **release rehearsal**, which puts the same loop through the fixture repo before each release.
_Avoid_: smoke test, e2e, integration test
