---
name: implement-change
description: Implement and close the next necessary-now item in a pull request's judge ledger.
disable-model-invocation: true
---

Invoked with a pull request number only. Take exactly one unchecked item from the judge's Necessary now queue through implementation, verification, push, and closure. Leave every later item for another invocation.

GitHub operations use `gh`; repository conventions live in the applicable agent instructions and the files they point to.

## 1. Select the item

Require a clean working tree, then read the pull request's metadata, description, comments, diff, head ref, and head SHA. Sort comments by `createdAt` and capture the most recent comment's GraphQL `id` and body. This is the judge's ledger; retain its ID so later comments cannot change which ledger gets updated.

Within that comment, find the exact `## Necessary now` section and select its first `- [ ]` task in document order, stopping at the next level-two heading. The review number or `Judge:` prefix and explanation together define the task. If the section is malformed or has no open task, make no changes and report that there is no necessary-now work to pick up.

## 2. Work on the pull request's branch

Check out the pull request head with `gh pr checkout <pr>` when the current branch is not already that head, then fast-forward from its configured upstream. Confirm the current branch and `HEAD` match the pull request's head ref and SHA before editing. Preserve a dirty, divergent, or conflicting checkout unchanged and report the exact obstacle instead of forcing it into shape.

Read the selected ledger line, the pull request description and diff, and the current code it names. Follow a cited issue, review point, standard, or repository context document when the explanation depends on it. Scope the change to the selected item; the other open tasks are separate work.

## 3. Implement and verify

Use `/tdd` when the item changes observable behavior at a public seam already established by the issue or existing test suite: make the relevant test fail for the missing behavior, then make the smallest implementation pass. The established seam is enough agreement for this workflow; request no input beyond the pull request number. When the item has no executable seam, make the focused change and use the nearest relevant validation.

Read the repository's agent instructions and CI configuration for its required commands. Run the focused test during implementation, then every documented lint, type, test, build, and coverage check that gates the pull request. The implementation is locally complete only when all of those checks pass with the current working tree.

## 4. Commit and push

Review the complete diff against the one selected ledger item. Read and follow the repository's commit conventions, stage only this implementation, create a commit on the pull request's existing head branch, and push that branch to its configured remote. Confirm the pull request's remote head SHA is the commit you pushed.

When the pull request reports CI checks, wait for the checks required by repository convention. Repair failures caused by this implementation, rerun the local gate, commit, push, and wait again. A failure outside this change or a check that cannot run is a blocker: report it and leave the task open.

## 5. Close the item

Closing the checkbox is the last write. Refetch the captured comment by its GraphQL ID and edit that current body, preserving any concurrent changes. Change only the selected line's `- [ ]` marker to `- [x]`; use the `updateIssueComment` GraphQL mutation with the captured ID rather than posting a replacement comment or rebuilding the ledger from the stale original body.

Refetch the comment once more and verify that the selected item is checked, every other task retains its prior state, the pull request head still matches the pushed commit, and required checks are passing. Report the item completed, the commit pushed, and the checks run.
