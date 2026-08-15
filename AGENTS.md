# my-team

Agent skills are installed under `.agents/skills/` (source of truth) and surfaced to
Claude Code via symlinks in `.claude/skills/`. `skills-lock.json` pins their versions.
Skills authored in this repo rather than vendored — currently `create-pr` — have no
lockfile entry.

## Agent skills

### Issue tracker

Issues live in GitHub Issues at `mcnewcp/my-team`, driven by the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Commit conventions

Conventional Commits over squash merge, so a PR title and description are the commit that
lands on `main` and the input to release automation. Read before writing any commit message,
PR title, or PR description: `docs/agents/commit-conventions.md`.
