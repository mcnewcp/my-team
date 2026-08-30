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
The per-issue directory an agent works in — a `git worktree` of the target repo, plus that issue's handoffs alongside it. Lives outside every repo and is discarded when the issue merges.
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
One unit of work a tick dispatches: one role, one definition of done. Normally a single harness session running a single skill — a session stopped at the **smart zone** is resumed once to write a **handoff**, which is the tail of the same action rather than a new one. A tick may wrap an action with mechanical steps the orchestrator performs itself, such as pushing the branch afterwards. Several actions belong to the same role: the implementer runs again on every revision round.
_Avoid_: job, step, task

**Round**:
One lap of the loop: the orchestrator hands the pull request to the implementer, and the
implementer hands it back. Bracketed by the draft flag, so rounds are countable from the timeline
rather than remembered. A round that revises, a round that repairs a red check and a round that
rebases a conflict are the same kind of thing and are counted together.
_Avoid_: iteration, pass, attempt, turn

**Disposal**:
The judge's ruling on one of the reviewer's points, of which there are exactly three: **necessary now**, **worth keeping** — filed as a fresh issue — or **dropped**. Every point gets exactly one, and there is no non-blocking fourth, because nothing in the loop would ever read it.
_Avoid_: verdict, triage, ruling, severity

**Escalation**:
Handing an issue back to the **product owner**: the orchestrator swaps `ready-for-agent` for `ready-for-human`, states in one comment which limit tripped and on what evidence, and exits. The counterpart to halting, which stops without asking for anything because the human is already acting.
_Avoid_: failure, abort, bail

**Authorization**:
A **trusted human** applying `ready-for-agent` to an issue body they have read — the act that admits an issue to the loop. It lapses if the body is edited by an untrusted editor afterwards, and **escalation** revokes it.
_Avoid_: approval, permission, gate, sign-off

### State and narration

**Observation**:
The single snapshot of the target repo's GitHub state that one tick reads before it acts — the issue, the remote branch, the PR, its reviews, the checks at the current head, and the PR timeline. Local git inside the workspace is never part of it. A tick observes once; everything it decides comes from that one snapshot.
_Avoid_: poll, scan, read

**Progress event**:
An externally caused fact proving the issue moved — a new commit, a review submitted, a check run completing. It excludes the draft transitions the orchestrator performs itself: the loop's own bookkeeping is not progress, and counting it as such would let a livelock hold the stall detector open forever.
_Avoid_: activity, heartbeat, update

**State**:
The derived value naming where an issue sits in the loop. Computed from an Observation, never stored, and never written anywhere: the same Observation always yields the same State. The set is fixed and ordered, and the order is what breaks ties between states that look alike.
_Avoid_: status, phase, stage

**Ladder**:
The ordered list of guarded rows from which **State** is derived — evaluated top to bottom, first
match wins. The order is the ambiguity-breaker between states that look alike from one snapshot,
so it is part of the design rather than an implementation detail, and the ladder is data the tests
can enumerate rather than a chain of branches. Every row whose action is a dispatch has a guard
that is the negation of that action's definition of done, which is what makes a re-fire a retry
rather than a livelock.
_Avoid_: rules, dispatch table, decision tree, chain

**Declaration**:
An observable act by which a **Role** asserts something the orchestrator cannot verify for itself —
the counterpart to **Verify by observation**. A Declaration is always a deliberate API call
attributable to a **Principal**, never prose the orchestrator reads.
_Avoid_: signal, report, claim

**Narration**:
What humans read — reasoning, progress, and the events a future feed or board view would render. Never an input to an orchestrator decision. Distinct from **state**, and free to live outside GitHub as long as it is reachable by a link from it.
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
The span of context within which a model still works well, far below the window's true ceiling. One absolute token count, set once for the whole team; crossing it is what stops a dispatch and calls for a **handoff**.
_Avoid_: context limit, budget, cap, threshold

**Handoff**:
A context-complete document an agent writes when the orchestrator stops it at the **smart zone**, addressed to the next copy of its own role. Lives in the workspace rather than in git, and is never an input to an orchestrator decision.
_Avoid_: checkpoint, summary, context dump

**Verify by observation**:
Establishing what happened by inspecting the target repo directly — new commits, green tests, a PR that links its issue — rather than by trusting an agent's account of its own work. The rule that governs every state transition the orchestrator can check for itself.
_Avoid_: validation, confirmation

### Proving it

**Acceptance run**:
One issue taken through the whole loop to a merged pull request in a real target repo, unattended — the proof that the tool works, performed on work that was genuinely wanted. Its repeatable counterpart is the **release rehearsal**, which puts the same loop through the fixture repo before each release.
_Avoid_: smoke test, e2e, integration test
