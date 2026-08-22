# Verify by observation, and the trust boundary is exactly two declarations

No state transition is taken on an agent's account of its own work when the fact is checkable
directly. Did the branch reach origin? Are the required checks green at this head? Does a pull
request exist and does it link its issue? Each is a question GitHub answers, and the orchestrator
asks GitHub rather than the agent that claims to have done it.

Where an assertion genuinely cannot be verified — "this implementation round is complete", "these
changes are necessary" — it is taken only as a **Declaration**: a deliberate API call
attributable to a role identity, never prose. There are exactly two.

1. **The implementer marks its pull request ready.** The code is done *and* the pull request
   describes it.
2. **The judge submits a formal review** — `APPROVED` or `CHANGES_REQUESTED`.

That is the whole set. **No prose is parsed anywhere in the state machine.**

## Why this is not merely good hygiene

Both harnesses in scope report success on work that did not happen, and it was measured on each
rather than assumed. Codex's exit status is strictly binary and reports *harness* health rather
than *task* outcome: a run where the model tries, fails, and says "I could not fix the test"
exits `0`, and an interrupted run shares its exit code with a failed one. Claude Code has the
same failure mode from the other direction — a blocked tool yields exit `0`, `is_error: false`,
and the failure present only as English prose, in five distinct denial shapes.

So `returncode` is read nowhere in this system. An orchestrator that trusted it would report a
merged feature to a human who was not watching, which is the specific failure this project
cannot have.

## Considered options

**Trust the agent's final message and parse it.** Cheapest, and it works most of the time, which
is the problem. A model that has been blocked, has run out of room, or has quietly decided a
requirement was optional writes a confident summary either way — observed directly, twice, in the
first real dispatches, where an implementer reported success while noting in passing that it had
pinned dependency versions "from knowledge, not verified" because a tool call was denied. Prose
also drags in the whole injection surface: anything that steers what an agent writes would then
steer what the machine does.

**A structured self-report** — make the agent emit a JSON verdict rather than prose. Better
looking and no better founded. It moves the claim into a schema without making it checkable, and
it fails in exactly the same case: the agent that is wrong about its own work fills the field in
confidently.

**Verify everything and admit no declarations at all.** Attractive, and it does not reach. "Is
this implementation round finished?" has no observable answer — commits on a branch look
identical whether the agent finished or stopped halfway — and "are these changes necessary?" is a
judgment by construction. Refusing to admit any declaration means either re-reviewing on every
new commit, which hands the reviewer half-finished trees and means the resume path never fires,
or inventing a heuristic that is a self-report with extra steps.

**More declarations, one per interesting act.** The set stays at two because each one is a place
the machine can be lied to, and each has to be worth its risk. Pull request *creation* was a
candidate and became a mechanical act instead; the push was a candidate and became a mechanical
sweep. Both are things the orchestrator can simply do, so neither needs trusting.

## Consequences

**Declarations must be repeatable, which is what forced the draft flag.** "The pull request
exists" is a declaration that works exactly once; every later round leaves the same observable
picture. `isDraft` gives one signal per round, and the latch is the subject of
[0002](./0002-draft-flag-is-the-implementer-latch.md).

**Each declaration is an act, not a message.** Marking a pull request ready and submitting a
review are both API calls GitHub attributes to a numeric actor. That attribution is what makes
them evidence: the orchestrator is not reading a claim about who did something, it is reading
that GitHub recorded who did it.

**The machine reads primitives, never computed summaries.** Verdicts come from the reviews list
filtered by the acting identity's **numeric** id — not from `reviewDecision`, which was measured
reading `null` with a fresh `APPROVED` plainly in the list, and not by login, since REST and `gh`
disagree on the `[bot]` suffix and a string comparison across them silently matches nothing.
Freshness is the review's pinned SHA against the current head, never the review's own `state`.

**Skills must state their definition of done as the fact the machine reads.** A skill whose
stated finish line drifts off its dispatching row's guard produces a row that can never discharge
itself — which is not hypothetical: it is the livelock a first real run found, where every tick
succeeded and no progress was made. The rule that catches it is that **for every dispatch row,
the guard is the negation of that action's definition of done**, and it is checked at authoring
time on both sides.

**The orchestrator performs the mechanical acts itself.** Opening the draft pull request under
the implementer's identity, pushing the branch as the tail of every implementation dispatch,
converting to draft, merging. None of these needs judgment, so none of them needs an agent, so
none of them needs trusting. The push in particular is done by *both* the skill and the
orchestrator, and neither is trusted — the guard reads the remote ref.

**Platform enforcement is preferred to orchestrator policy wherever it exists.** GitHub refuses
to let an actor approve its own pull request (`422`, with no review recorded, under protection
and without it); it refuses to merge a draft (`405`); `--match-head-commit` refuses a merge of a
tree that moved; and a closing keyword in the body closes the issue on merge. Each of those is a
rule we would otherwise have to write, test and get right.

**The narration channel is deliberately separate and deliberately unparsed.** Agents produce
genuinely valuable prose — a flagged deviation, a judgment call worth another pair of eyes, an
admitted guess — and it is posted to the pull request conversation for humans and for the
reviewer and judge to read as context. Posting is not parsing. The ladder stays blind to it, and
that separation is what lets the loop be talkative without being steerable by its own chatter.

**The honest cost: the loop is slower than a trusting one.** The first pass necessarily takes
three ticks rather than one, because there is no pull request to mark ready at the moment the
branch is created. A round that commits nothing leaves its guard undischarged and re-dispatches
rather than moving on. An implementer that cannot finish is told plainly never to mark ready to
escape a problem, which means the loop burns rounds getting to escalation instead of exiting on
the first refusal. Every one of those is the design working: slower, never wrong.
