# The payload is installed into the target repo, in both skill roots

`my-team sync` writes the skill payload into the target repo as committed files — real
directories at `.agents/skills/mt-<name>/` and relative symlinks at `.claude/skills/mt-<name>`
— and records what it wrote in `.my-team/skills-manifest.json`. It does not commit on the
human's behalf; `doctor` gates the run on the payload being present **and committed on the
default branch**, since the per-issue worktree branches off `origin/<default>` and never reads
the human's checkout.

Two things about that shape are surprising enough to write down: the payload ships a Codex
skill root and a symlink farm in a version that only supports Claude Code, and it keeps a
manifest, six `sync` cases and drift detection when a simpler alternative would have deleted
all of it.

**The dual root is insurance against a migration we could not run.** `.agents/skills` is
literally Codex's repo skill root and `.claude/skills` is Claude Code's, which documents that
its entries may be symlinks — so one copy serves both harnesses with no translation layer.
v0.1 is Claude Code only, but the payload lands in repos we do not control, and installing to
`.claude/skills/` alone would mean that adding Codex later requires moving files in every one
of them. A symlink per skill today is cheaper than that, and it is the same posture the harness
seam already takes: design against Codex's real shape, ship Claude Code only. It is also the
only root under which the `agents/openai.yaml` sidecars have a home.

## Considered options

**Inject the payload instead of installing it** — write it into the per-issue workspace at
dispatch, or load it out-of-tree via the `--add-dir` the seam already passes for handoffs.
Either one deletes this entire subsystem: no `sync`, no manifest, no drift checks, no staleness
check, and the payload version tracks the CLI automatically so it can never go stale. That is a
real benefit and it is the reason this needs recording, because the machinery it would have
saved is sitting right there for someone to question.

Rejected because it does not bend the promise that a target repo stays self-describing and a
human can run the loop's procedures by hand — it deletes it. A payload that exists only inside
an ephemeral workspace cannot be invoked by hand, and the repo stops recording which procedures
it runs. The auto-tracking benefit has a matching cost of its own: upgrading a CLI would
silently change the procedures a repo runs, with nothing in the repo to say so.

The workspace variant is worse than the `--add-dir` variant regardless. Files written inside the
worktree are untracked under a tree the implementer commits and the orchestrator pushes, so the
payload would ship itself into every pull request — the same hazard that put handoffs *beside*
the worktree rather than in it.

**Have `sync` commit.** Writing to a human's working tree is already the most invasive thing the
tool does; committing for them is a step past it. Requiring a committed file is ordinary for
repo-scoped tooling, and nothing forces a commit straight to the default branch — one normal
pull request at setup satisfies it.

## Consequences

**The manifest is not a lock and is not named like one.** There is no upstream to pin the
payload against; it records the paths `sync` wrote (both of them per skill, or it could never
clean up), a content hash, an `ejected` flag, and the version that wrote it.

**`sync` never touches a file it did not write.** That single rule is what makes the first run
safe with no manifest present, and it is what lets `sync` *delete* a skill dropped from a future
payload — only a path it wrote, only while still byte-identical to what it wrote. A
human-edited file is refused and reported instead, which is the signal to use `eject`.

**This repo keeps no lockfile of its own.** Its skills are maintained here rather than tracked
against an upstream, which leaves the payload manifest as the only manifest in play and the
three skill trees disjoint by name. `AGENTS.md` carries the table that tells them apart.
