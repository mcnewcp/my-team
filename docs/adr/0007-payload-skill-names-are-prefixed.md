# Payload skill names are prefixed

Every skill in the payload `my-team` installs into a target repo carries an `mt-` prefix —
`/mt-implement`, `/mt-review`, `/mt-judge`, `/mt-create-pr`, `/mt-handoff`. Without it the
payload's names collide with two different things, and both collisions are silent.

The first is **personal-skill shadowing**. Claude Code resolves skills enterprise > personal >
project, so a product owner with `~/.claude/skills/implement/` running `/implement` by hand in
their own repo gets theirs, not the one the loop runs. The orchestrated path is already safe —
the Claude Code adapter passes `--setting-sources project`, which suppresses personal skills —
so this hits exactly the by-hand path the payload exists to keep honest. The second is
**self-installation**: the role identities are installed on this repo as well as the target, so
the team can be pointed at its own source, and this repo already has `.agents/skills/implement`,
`handoff` and `create-pr` under its own names. `create-pr` is the sharp case — the one here is
interactive and reads `docs/agents/commit-conventions.md`, both of which a payload skill is
forbidden to be, so it is not two copies of one skill but two different skills wanting one name
in one directory.

The prefix appears to weaken the promise that a human can run the loop's procedures by hand and
get identical behaviour. It secures it. That promise is about identical *behaviour*, and today,
by hand, `/implement` can silently be somebody else's skill.

## Considered options

**Bare names, plus ejecting the colliding skills here.** Fixes this repo and nothing else. The
shadowing hazard is a property of every target repo and every developer's home directory, so it
would stay live everywhere the tool is actually used.

**Plugin namespacing**, which yields `/my-team:implement`. Buys the same property and costs a
marketplace and an install mechanism to get it; the skill-payload research rejected plugins
already, on the grounds that namespacing was the cost rather than the feature. Now that
namespacing *is* the feature, the rest of the plugin machinery is still unwanted.

## Consequences

**The rename had to happen before the skills were written, not after.** None of the five exists
yet, so this costs nothing today. It would not have stayed cheap: `/mt-implement` invokes
`/mt-create-pr` **by name**, and a by-name reference to a renamed skill fails *invisibly* — the
skill is not listed to the model rather than refused. A later rename would also have to move
files in target repos we do not control.

**The prefix is what the referenced-skill test checks against.** The test reads the allowed set
from the payload tree itself rather than a fixed list, so a shared sub-skill joins the roster by
being present and prefixed, and any `/token` in a payload skill that is not a payload member
fails the build. That is what keeps the roster a closure as it grows.

**`--setting-sources project` stays**, though its shadowing rationale is now gone. It still
pins the dispatch environment by dropping user `settings.json`.
