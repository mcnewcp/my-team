# GitHub is the sole source of truth for orchestrator state

The orchestrator holds nothing durable. Every tick reads one Observation of the target repo from
GitHub, derives a State from it, performs one action, and exits. State is computed and never
stored — not in a file, not in a database, not in a label the orchestrator wrote itself. The same
Observation always yields the same State, and no tick knows anything about the tick before it.

This is the constraint the rest of the design is built on rather than one decision among many.
It is what makes the loop crash-safe (there is no progress to lose), resumable (the resume path
is the same code as the first run), testable (State is a pure function over plain data), and
eventually parallelisable (nothing is shared between issues except a remote nobody owns).

Two things follow that are easy to mistake for oversights. **If a counter cannot be derived from
GitHub, it does not exist** — which is why implementation rounds are counted from
`convert_to_draft` timeline events and a stall is measured as elapsed time rather than as a
number of ticks. And **a local cache may never become load-bearing**: the workspace, the handoff
documents and the harness session ids are all real, all useful, and none of them may ever select
an action.

## Considered options

**A state file beside the workspace.** The obvious shape, and it fails on the case the tool
exists for: an unattended run that crashes. A file recording "we are in review" survives a crash
and can be wrong the moment a human closes the pull request, and the orchestrator has no way to
notice — it believes its own note. Every predicate then needs a reconciliation rule for the case
where the note and the repo disagree, and those rules are where the bugs live. Deriving the same
fact fresh cannot disagree with reality, because there is nothing to disagree with.

**Labels or an assignee the orchestrator writes.** A state file wearing a GitHub costume. It
survives a crash, it is even pleasantly readable in the UI, and it is still the orchestrator
writing down what it believes and then trusting its own note. It also loses on a subtler point:
a human who moves the issue by hand has to know the private scheme and update it, or the machine
reads a state nobody is in any more.

**A durable session, resumed across ticks.** Cheaper per tick, since context is already warm,
and it collapses the loop into one long-lived agent conversation — which is the thing this design
is not. A session that outlives an action makes the session id load-bearing, so a crash orphans
state rather than merely wasting a few seconds, and it removes the fresh-context property that
the smart zone and handoff mechanism depend on.

**In-memory state within one `work` invocation.** Tempting, and almost harmless, which is what
makes it worth naming. It is admitted exactly once, deliberately: the stall detector's floor at
the start of the invocation. That single value is ephemeral, dies with the process, is passed to
the pure core as a parameter rather than read inside it, and never selects an action on its own.
Anything beyond it re-introduces the problem in miniature.

## Consequences

**The tick is the primitive, and it is cheap.** One Observation, one action, exit. Rows that
mutate mechanically stop rather than also dispatching, because two mutations in one tick buy one
saved tick at the cost of a crash window — and ticks are free precisely because there is nothing
to reload.

**Nothing durable stores a harness session id.** The seam mints one, uses it at most once inside
a single action to write a handoff, and returns it as telemetry. A crash mid-action orphans the
session and the next tick starts fresh: slower, never wrong.

**Counters are derived or they do not exist.** Judge rounds come from the reviews list,
CI-repair rounds from distinct failing head SHAs, implementation rounds from `convert_to_draft`
events, and a stall from elapsed time on GitHub's own clock. "N ticks with no new commit" is not
representable at all, because a tick leaves no trace unless it mutates something. That turns out
to be the better primitive anyway: elapsed time catches a *hung* agent, which tick-counting
cannot, since a hung tick never returns to be counted.

**Handoff documents are not state.** They live outside git in the workspace and are never an
input to a decision. Tick N+1 derives "continue implementing" from the remote branch and the
pull request alone, identically whether or not a handoff exists; the handoff only enriches a
prompt for an action already chosen. That is what lets them be local files rather than committed
ones (see [0001](./0001-isolated-worktree-and-handoffs-outside-git.md)), and it is why nothing
counts them to detect grinding.

**The workspace is acted on and never observed.** Making local git a co-equal observation source
was taken seriously and rejected because no action changes: State is the value that names one
action, so a distinction the ladder cannot act on differently is not a state. The bar for
reopening that is a single question — *which action changes?*

**The restrictive choice is the reversible one.** GitHub-only → also-local-git is cheap and
additive; local-git → GitHub-only is expensive, because by then every predicate has quietly come
to depend on the second source. What this record buys is not commitment but a deliberate
expansion if one ever happens.

**The cost is real and is accepted.** Every tick pays a handful of API calls to re-read what it
could have remembered — roughly eight per tick, against an installation token's 5000 per hour,
so the ceiling is nowhere near. And GitHub is eventually consistent, which is a genuine tax: a
pull request's head SHA lags a push by several seconds while `mergeable_state` reads `"unknown"`,
and the ladder carries a row whose entire job is to refuse to act on a snapshot that has not
settled. A local cache would not have that problem. It would have worse ones.
