---
name: review-pr
description: Review a pull request for the judge-driven implementation cycle.
disable-model-invocation: true
---

Invoked with a pull request number only. Review the current pull request head against its issue and repository standards, then publish one comment containing the complete list of requested changes for the judge. This is a fresh snapshot review whether the pull request is new or has already passed through earlier review, disposal, and implementation rounds.

GitHub operations use `gh`; repository conventions live in the applicable agent instructions and the files they point to.

## 1. Pin the review

Read the pull request metadata, description, full diff, commits, comments, required checks, base SHA, head SHA, and closing issue references. Resolve exactly one closing issue from the pull request and read its body and comments as the spec. A missing or ambiguous closing issue leaves no trustworthy spec: post nothing and report the linkage problem.

The head SHA is the review's fixed point. Read the full base-to-head diff on every invocation, not only commits since the previous review; later rounds can regress code outside their immediate change.

## 2. Respect the cycle

Read the earlier review and judge comments before forming findings.

- If the newest judge ledger has an unchecked task under `## Necessary now`, post nothing and report that implementation is still in progress. A new review would replace the latest-comment handoff before `implement-change` drains it. Open Worth keeping tasks do not block review.
- If this head SHA already has a review comment and no later judge ledger disposes it, post nothing and report that the review is awaiting judgment.
- Treat earlier disposals as cycle memory. A dropped point stays out unless changed code or new evidence defeats the judge's reason. A worth-keeping point stays in its triage queue unless the issue or current diff has brought it into this pull request's scope. Re-raise a checked necessary-now point only when the current tree has regressed it, and cite that regression.

Wait for pending required checks before finalizing the review. A failed check caused by the current change is one requested change per root cause, not one item per log line. An infrastructure failure that says nothing about the code blocks publication; report it without adding review noise.

## 3. Review in two passes

Review the whole current diff twice, keeping the lenses separate while investigating:

- **Issue fit** — every requirement is present and correct; behavior outside the issue is justified; tests demonstrate the requested behavior rather than merely exercising the implementation.
- **Code and standards** — changed code preserves correctness, security, data, and domain invariants and follows every applicable documented repository standard. Structural smells are judgment calls that need a concrete hunk and consequence; tooling-enforced style is already covered by the checks.

Open the current head version of every file a possible finding names. Report every evidenced requested change without assigning severity or a disposal; filtering belongs to the judge. Each item is atomic and actionable: one change, its `path:line` evidence, and the issue wording, standard, or observable failure that makes it worth requesting. Combine two symptoms only when one root change resolves both.

## 4. Publish the review

Immediately before posting, refetch the pull request head SHA. If it moved, discard the draft and repeat the review once against the new head. If it moves again, post nothing and report that the branch is actively changing.

Post exactly one final comment with `gh pr comment <pr> --body-file -`. When changes are requested, use this shape and renumber from 1 on every review:

```
Reviewing #<issue> on #<pr> at <head sha>.

1. `<path>:<line>` — <requested change and evidence>
2. `<path>:<line>` — <requested change and evidence>
```

When there are no requested changes, use the same header followed by the exact sentence `No requested changes.` The header plus the numbered list or that sentence is the whole body: post no summary, praise, severity, disposal, or follow-up comment that the judge could mistake for another point.

Refetch the pull request comments and verify the posted body and reviewed head SHA. The review is complete only when that single comment is visible and is the final action of the invocation.
