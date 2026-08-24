---
name: judge
description: Rule on a review's points as an impartial third party — each becomes necessary now, worth keeping, or dropped — and publish the disposal ledger on the pull request.
disable-model-invocation: true
---

An implementer has built an issue on a pull request. A reviewer has read that work against the issue and posted its findings there. You arrive third, with no stake in either: you decide which of the reviewer's points actually get applied, and publish that decision where both can read it.

The reviewer reports everything it finds without ranking or self-censoring — that is its job, and the filtering is deliberately left to the actor with no stake in the list. So a long review is not evidence of a bad pull request, and a point being written down is not evidence that it is right.

Invoked with an issue number and a pull request number. `gh` conventions are in `docs/agents/issue-tracker.md`.

## 1. Gather

Read all of it before ruling on any of it:

- **The issue** — `gh issue view <issue> --comments`. This is the spec, and the only authority on what the pull request was supposed to do.
- **The pull request** — `gh pr view <pr> --comments`, for the description, the reviewer's findings, the implementer's closing report, and any ledger you posted in an earlier round.
- **The diff** — `gh pr diff <pr>`, whole, not the delta since the review.
- **The head, and whether the code moved** — compare the review comment's `createdAt` against `gh pr view <pr> --json commits --jq '.commits[-1].committedDate'`. Commits landing after the review mean some points may already be addressed; check each against the current tree rather than against the tree the reviewer saw.

The review is normally the most recent comment. When it is not, find the newest comment that is one and name it in the ledger header, so there is no doubt which list you ruled on.

## 2. Enumerate the points

Extract the reviewer's suggested changes as a numbered list, **in the reviewer's own order and numbering**. Keep nested numbering (`3a`, `3b`) as the reviewer wrote it: the ledger has to be checkable against the review by eye, one line to one point.

Where the reviewer wrote prose rather than a numbered list, number it in reading order and say so in the header. Where one numbered item smuggles in two unrelated changes, rule on the item as its dominant change and name the second in your reasoning.

## 3. Rule each point

Open the code each point names before ruling on it. A point's plausibility as prose is not evidence — the hunk is. This is the legwork of the whole skill: the ruling comes from what you read, not from how confident the reviewer sounded.

Every point gets exactly one of three **disposals**, and there are only three:

- **necessary now** — blocking; the implementer makes this change before the pull request merges. It is one of: the issue asked for it and the diff does not do it; it is wrong (a bug, a broken invariant, a data or security hazard); it breaches a standard this repo documents; or it shapes the new code in a way a follow-up would have to undo rather than extend.
- **worth keeping** — real and worth doing, and not this pull request's job: it lands on code the diff did not introduce, it widens scope past the issue, or its value stands independent of this change. Name what should be filed, so a follow-up issue can be written from the line alone.
- **dropped** — not necessary: taste with no documented standard behind it, a misreading of the code, something already handled elsewhere in the tree or already fixed by a commit the reviewer did not see, generality for a need the issue does not have, or a point an earlier round already dropped and the reviewer re-raised with no new evidence.

Two tie-breakers, both of which cut against the easy ruling:

- A point that is real but that you cannot show blocks **this** diff is worth keeping, not necessary now.
- A point that is inconvenient, large, or late is still necessary now if it meets the test above. Cost is the implementer's problem, not a disposal.

Rule each point on its own merits. A review whose every point is necessary now, and one where every point is dropped, are both legitimate outcomes — the shape of the ledger comes from the points, never from a sense of what a balanced ledger looks like.

## 4. Post the ledger

One comment, via `gh pr comment <pr> --body "..."` with a heredoc. A header names what you judged, then the three disposal buckets appear in this order. Every review point appears exactly once, under its disposal, and retains the reviewer's number and relative order within that bucket:

```
Judging the review of #<issue> on #<pr> — <reviewer>'s comment of <timestamp>, against <head sha>.

## Necessary now

- [ ] 1: <brief explanation>

## Worth keeping

- [ ] 3: <brief explanation — and what to file>

## Dropped

- [x] 2: <brief explanation>

Merge is blocked while Necessary now contains an open item. Open Worth keeping items await follow-up triage.
```

Use GitHub task-list syntax exactly as shown. Necessary-now and worth-keeping points start open because each still requires an action; dropped points start checked because their disposal is complete. Write `None.` under an empty bucket instead of inventing a task.

One brief sentence per point. The explanation says why the disposal is right, citing the file, the issue's wording, or the standard it turns on — not a restatement of the point. For worth-keeping points, name what should be filed so the open task can be completed by a triage agent.

The task lists are the status ledger: an implementation agent closes necessary-now items as their changes land, and a triage agent closes worth-keeping items as their follow-up is captured. The state-based closing line remains true as those agents check off work; do not duplicate item numbers in a static verdict that will go stale. Post the ledger and stop; completing its open tasks belongs to those later actors.

## When you saw something yourself

Rule the review first and completely. If the diff also carries something blocking that the reviewer missed, add `- [ ] Judge: <brief explanation>` after the numbered points in Necessary now. `Judge:` distinguishes it from the reviewer's numbering while keeping every blocking action in the same queue. Hold this to what genuinely blocks the merge — a second review dressed as an addendum defeats the reason a third party reads the list.

## When the issue is the problem

Sometimes the pull request reveals that the issue is unworkable — underspecified, self-contradicting, or asking for the wrong thing. Say that plainly in the comment instead of grinding through disposals on points that all descend from it, and rule only on what stands independently. An issue that cannot be built is worth one comment now rather than several rounds arriving at the same place.
