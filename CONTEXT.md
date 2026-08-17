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

### The loop

**Tick**:
One observation of the target repo's state followed by exactly one action, then exit. The orchestrator's primitive unit of work.
_Avoid_: step, cycle, iteration

**Harness**:
An AI coding tool that `my-team` drives to do the actual engineering — Claude Code, later Codex. `my-team` wires harnesses together; it does not replace them.
_Avoid_: backend, provider, engine, model

**Role**:
An identity with authority — the implementer, the reviewer, the judge. A role holds its own credential and is what GitHub sees acting. Roles are provisioned once and perform many actions.
_Avoid_: worker, bot, agent

**Action**:
One unit of work a tick dispatches: one harness session, one skill, one definition of done. Several actions belong to the same role — the implementer both writes the code and opens the PR.
_Avoid_: job, step, task

**Persona**:
The name and voice attached to a role — Robin implements, Shane reviews, Lewis judges. Lives in the orchestrator and is injected at dispatch; never in a skill file, so a human running the skill by hand gets the behaviour without the character. A persona colours the prose it writes; it never announces itself.
_Avoid_: character, personality

### State and narration

**State**:
What the orchestrator reads to decide what to do next. Lives exclusively on GitHub, and must always be derivable from observed issue, PR, and CI state.

**Narration**:
What humans read — reasoning, progress, and the events a future feed or board view would render. Never an input to an orchestrator decision. Distinct from **state**, and free to live outside GitHub as long as it is reachable by a link from it.
_Avoid_: logs, chatter, output

**Handoff**:
A context-complete document written by an agent that stopped before finishing, addressed to the next copy of its own role. Lives in the workspace rather than in git, and is never an input to an orchestrator decision.
_Avoid_: checkpoint, summary, context dump

**Verify by observation**:
Establishing what happened by inspecting the target repo directly — new commits, green tests, a PR that links its issue — rather than by trusting an agent's account of its own work. The rule that governs every state transition the orchestrator can check for itself.
_Avoid_: validation, confirmation
