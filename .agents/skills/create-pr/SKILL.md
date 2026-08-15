---
name: create-pr
description: Open a pull request following this repo's commit conventions — a conventional-commit title, a description written as the squashed commit body, and verified issue links. Use when opening a PR, or when fixing a PR title or description that the lint rejected.
---

# Create PR

This repo squash-merges, so the PR title and description **are** the commit that lands on
`main` — and that log drives release automation. Write them as that commit, not as a note to
a reviewer.

The rules live in `docs/agents/commit-conventions.md`. Read it before composing. This skill is
the process; that file is the standard.

## Process

### 1. Survey the change

Read the diff, not just the file list:

```bash
git status --short
git log main..HEAD --oneline
git diff main...HEAD
```

Use the base the user named, or `main`.

Then account for the issues — nearly every PR here closes at least one. Check the branch name
and commit bodies for numbers, and search the tracker for work this diff resolves:

```bash
gh issue list --state open --json number,title,labels
```

Sort every hit into **closing** (this PR resolves it) or **related** (touched, not resolved),
and confirm the split with the user.

**Done when** you can state in one sentence what changed and why, and every issue this PR
closes or touches is on one of those two lists — or you have confirmed there are none.

### 2. Check the scope

One logical change per PR — a PR that does two things produces a commit that lies about what
it did. If the diff spans unrelated changes, say so and offer to split before opening.

**Done when** the branch is one logical change, or the user has chosen to ship the mix.

### 3. Get the work onto a branch

Skip to step 4 if `HEAD` is already a non-default branch with everything committed.

Name the branch `<type>/<issue>-<slug>` per the branch-name rules, using the type you will put
in the PR title and the lead issue from step 1.

- Uncommitted work: `git checkout -b <type>/<issue>-<slug>`, then commit it.
- Commits sitting on local `main`: `git branch <type>/<issue>-<slug>`, then rewind `main` with
  `git reset --hard @{upstream}`. Confirm before the rewind — it discards anything on `main`
  that isn't upstream.

Local commit messages are scratch — they collapse into the PR title and description on merge,
so spend the effort in step 4 instead.

**Done when** `HEAD` is a non-default branch and `git status` is clean.

### 4. Compose the commit

Write the title and description together as one artifact, against the standard:

- **Title** — `<type>(<scope>)<!>: <subject>`, imperative, ≤50 chars, lowercase after the
  colon, no trailing period. Pick the type from the six-type table.
- **Description** — why, not what. The constraint that forced this approach, the alternative
  rejected, what was left out of scope, the gotcha for the next reader. Wrap at 72.
- **Footers** — one `Closes #<n>` line per issue from the closing list, one `Refs` line for
  the related list, and `BREAKING CHANGE: <migration>` paired with `!` in the title when
  something breaks. One keyword per issue: `Closes #14, #15` closes only #14.

Leave checklists and review chatter out; the description ships to `main`'s history verbatim.

**Done when** the title and description would read correctly as a commit on `main`, because
they will be one.

### 5. Confirm

Show the user the title and description exactly as they will land. Let them edit.

**Done when** the user accepts the draft.

### 6. Push and open

```bash
git push -u origin HEAD
gh pr create --title "<title>" --body-file - <<'EOF'
<description>
EOF
```

### 7. Verify the links

Confirm GitHub actually parsed the keywords rather than trusting that it did:

```bash
gh pr view <n> --json closingIssuesReferences --jq '.closingIssuesReferences[].number'
```

Every number on the closing list from step 1 has to come back. A missing one means a malformed
keyword — fix the description with `gh pr edit --body-file -` and check again.

**Done when** the returned set matches the closing list exactly.

### 8. Report

Give the user the PR URL, the linked issues, and the commit that will land on `main` when they
squash.

`PR title lint` validates the title on open; if it fails, fix it with
`gh pr edit --title "<title>"` rather than opening a new PR.
