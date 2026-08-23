# my-team

## Skill directories

Three trees hold skills. They look alike and behave differently — know which one you are
editing.

| tree | what it is | loaded here? |
| --- | --- | --- |
| `.agents/skills/<name>/` | **This repo's own skills**, maintained here. Symlinked into `.claude/skills/<name>`: `.agents/skills` is Codex's repo skill root and `.claude/skills` is Claude Code's, so one copy serves both. Originally vendored from an upstream set; that link is cut and these are now ours to change. | yes |
| `src/my_team/payload/skills/mt-<name>/` | **Product data** — the skill payload `my-team` installs into a target repo, shipped inside the Python package. It looks exactly like a skill and is not one: nothing loads it, and editing it changes nothing until `my-team sync` runs. | **no** |
| `.agents/skills/mt-<name>/` | The payload **after** `my-team sync` has been run against this repo, which is a target repo like any other. Owned by `.my-team/skills-manifest.json` — never hand-edit, use `my-team eject`. | yes |

Payload skills carry the `mt-` prefix so they can never collide with the skills in row one,
or be shadowed by a personal `~/.claude/skills/` entry. See
[ADR 0007](docs/adr/0007-payload-skill-names-are-prefixed.md) and
[ADR 0008](docs/adr/0008-the-payload-is-installed-into-the-target-repo.md).

## Development

`uv sync`, then `uv run <tool>`. CI runs three jobs — `lint`, `types`, `tests` — which are
also this repo's own `required_checks` when the team is pointed at its own source;
`.github/workflows/ci.yml` is the source of truth for what each one runs.

Coverage is a **split floor**: 100% on `src/my_team/core/` and ~85% globally, and the global
figure ratchets up only. `core/` is the pure core — plain data and the functions over it — so
a module belongs there only when it opens no file, spawns no process and reaches no API.
Everything else sits outside it, under the global floor.

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
