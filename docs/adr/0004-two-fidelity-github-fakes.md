# Two fake GitHubs, bound to the real one by a contract test

> **Supersession note:** [ADR-0013](./0013-pipeline-state-is-a-label-backed-cursor.md) supersedes
> the historical row counts, derived-State examples and `AMBIGUOUS` State below. The two-fake
> testing boundary remains: hand-built Observations isolate pure decision logic, a stateful world
> tests convergence across mutations, and captured GitHub payloads bind both to reality. The
> replacement spec will supply the new State-register and State-local Ladder cases.

The ladder tests hand-build `Observation` values through a builder; the convergence tests
drive a stateful in-memory world that mutations change. These are deliberately two
different fakes, because they are answering two different questions — and because the
builder can mint observations GitHub would never produce, a contract test against a real
fixture repo asserts that parsing real payloads yields the shapes the builder claims.
Delete that contract test and the builder quietly becomes fiction.

## Considered options

**One stateful fake used everywhere.** The obvious economy: set up a world, observe out of
it, assert the derived state. It was rejected on two counts. The eighteen row tests are
tests of a *pure function*, and routing them through a fake makes every one of them also a
test of the fake — a failure then has two possible causes and the test no longer isolates
the thing it names. Worse, several rows are only reachable as nonsense: `AMBIGUOUS`
requires two matching branches, or a formal review from an identity that is not in the
roster. Teaching a stateful fake to emit states GitHub would never emit corrupts it for
the convergence tests, where its entire value is that it models only the reachable world.
With a builder, an impossible observation is one keyword argument.

**Hand-built observations only, with no stateful world.** Cheaper still, and it cannot
catch the failure mode this project has already met. Row 9 of the sixteen-row ladder was a
livelock — its action did not discharge its own guard, so the orchestrator re-dispatched
the same work forever. Every per-row test passed; the row derived correctly every time.
Only a loop driven far enough to see the same state derived twice with nothing changed can
find that, and that needs a world where an action's effect is visible to the next
observation.

**Recorded HTTP cassettes as the single fake.** Faithful to the wire and hostile to the
question. Constructing eighteen states plus their shadowing pairs as recorded traffic means
recording a repo into each of them first, and a cassette cannot express "a review from an
unrecognised identity" without a real unrecognised identity. Cassettes survive here in a
narrower role — the captured payloads the contract test parses.

## Consequences

The two fakes can disagree, and that is the standing risk. The builder's defaults encode
what we *believe* GitHub returns, and every load-bearing fact in the state machine was a
surprise when it was measured: `reviewDecision` reading `null` with a fresh `APPROVED` in
the list, REST and `gh` disagreeing on the `[bot]` suffix, `head.sha` lagging a push by
about ten seconds, timeline timestamps colliding at second resolution. A builder is happy
to reproduce any belief at all.

The contract test is therefore not optional infrastructure. It parses payloads captured
from a real fixture repo and asserts the resulting observations match what the builder
produces, which is the only thing tying the two fakes to each other and to reality. It also
re-captures those payloads, which is what stops them ageing silently against a live API.

Splitting `observe()` into a `fetch` that only does I/O and a `parse` that is pure is what
makes any of this possible. Fused, as the spike had them, there is no seam at which a real
payload can enter a test.
