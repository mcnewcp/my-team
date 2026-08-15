# Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) over a squash-merge
workflow. Every commit on `main` is one merged PR, and that log is the input to release
automation — so a PR title is a release artifact, not a note to a reviewer.

## Format

```
<type>(<scope>)<!>: <subject>

<body>

<footers>
```

Type and subject are required; scope and `!` are optional.

## Types

| Type | Use for | Release |
|---|---|---|
| `feat` | new capability | minor |
| `fix` | bug fix | patch |
| `docs` | documentation only | none |
| `refactor` | behaviour-preserving change | none |
| `test` | tests only | none |
| `chore` | tooling, deps, config, CI, scaffolding | none |

Closed set of six. `.github/workflows/pr-title-lint.yml` rejects anything else, so widening
the set means editing that workflow and this table together.

Scaffolding is `chore` even when it lands the thing users care about — the first commit that
makes a capability reachable is the `feat`, not the vendoring that preceded it.

## Subject

- Imperative mood: it completes "If applied, this commit will ___".
- ≤50 characters for the whole first line, so `git log --oneline` and the GitHub PR list show
  it whole. CI checks the format; the length is on you.
- Lowercase after the colon, no trailing period.
- Names the change, not the file: `fix(triage): apply labels idempotently` over
  `fix: update triage.md`.

## Body

The subject stays succinct because the body carries the substance. Explain **why** — the diff
already shows what. Wrap at 72 characters.

What earns its place: the constraint that forced this approach, the alternative rejected and
the reason, what was deliberately left out of scope, the gotcha waiting for the next reader.

## Footers

### Issue links

Every PR names its issues. Give each closing issue its **own keyword** — GitHub reads
`Closes #14, #15` as closing only #14:

```
Closes #14
Closes #15
Refs #9, #12
```

- **Closing** — `Closes` (or `Fixes`/`Resolves`) once per issue the PR resolves. Closes it on
  merge and lists it under **Linked issues** in the PR sidebar.
- **Related** — one `Refs` line for issues the PR touches without resolving. Posts a
  cross-reference on each issue's timeline; it does not populate the sidebar.

The keywords have to be in the PR description, which is why they survive the squash — the
description becomes the commit body, so `main`'s history keeps the links too.

Issue numbers stay out of the title: GitHub appends the PR's own `(#123)` there on squash, and
a second number next to it is ambiguous.

### Breaking changes

`BREAKING CHANGE: <what breaks and how to migrate>`, paired with `!` after the type or scope.
This is the only trigger for a major bump.

## Squash merge

`main` takes exactly one commit per PR, so the PR **is** the commit:

| PR field | Becomes |
|---|---|
| Title | Commit subject |
| Description | Commit body |

The repo is pinned to `squash_merge_commit_title=PR_TITLE` and
`squash_merge_commit_message=PR_BODY` so this holds regardless of how many commits the branch
carries. GitHub appends `(#123)` to the subject; conventional-commit parsers ignore it.

Three consequences:

- **One logical change per PR.** This is the discipline that replaces one-change-per-commit.
  A PR that does two things produces a commit that lies about what it did, and lands wrong in
  the changelog.
- **Local commits are scratch.** They collapse on merge, so commit as often and as messily as
  the work wants. Only the PR title and description survive.
- **The description ships.** Checklists, review chatter, and template boilerplate land in
  `main`'s history. Keep the description to what belongs in a commit body, or rewrite it in
  the merge dialog before confirming.

Commits pushed straight to `main` skip the PR path but follow the same convention — release
tooling reads them identically.

## Branch names

```
<type>/<issue>-<slug>
```

`feat/12-create-pr-skill`, `fix/31-triage-label-dedup`, `chore/deps-bump-actions`.

- **type** — the same six types as the title, picked once at branch time and carried into the
  PR title. A branch on `feat/` under a PR titled `fix:` means one of them is wrong.
- **issue** — the primary issue number, which is where `/create-pr` looks first for links.
  Omit it when there genuinely is no issue.
- **slug** — lowercase kebab-case, three to five words.

One number only. A PR closing several issues names the lead one here and lists the rest in the
description, which is the source of truth for links.

Nothing enforces this. Branches are deleted on merge and never reach `main`'s history, so the
name only has to serve whoever is reading the open PR.

## Opening a PR

`/create-pr` walks the branch through these rules and opens it.
