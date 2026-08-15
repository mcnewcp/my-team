# Shipping the `my-team` skill payload into a target repo

Research resolving issue #6. Every claim below is cited inline: a URL, a path in this repo,
or the command whose output is quoted. Facts are labelled **[documented]** when they come from
Anthropic's or OpenAI's published docs, or are read directly from Codex's open source, and
**[observed]** when established by running Claude Code 2.1.233 (`claude --version`) in a scratch
directory. Codex CLI was not installed on this machine, so nothing about Codex is **[observed]**.

Section 8 (Codex) materially changed the recommendation in §1 — `.agents/skills` is Codex's
native repo skill root, not an arbitrary staging directory — so §1 should be read as the
post-Codex conclusion.

---

## 1. Recommendation

**Write the payload into `.agents/skills/` — which is Codex's native repo skill root *and*
a legal symlink target for Claude Code — project it into `.claude/skills/` as symlinks, and
record per-skill ownership in a namespaced lockfile.**

`my-team init` writes, and commits, exactly this:

```
<target repo>/
├── .agents/skills/                 # canonical payload — Codex reads this path directly (§8)
│   ├── implement/
│   │   ├── SKILL.md
│   │   └── agents/openai.yaml      # Codex-native sidecar, shipped with the skill
│   ├── create-pr/…
│   ├── review/…
│   ├── judge/…
│   └── handoff/…
├── .claude/skills/                 # Claude Code projection — symlinks only
│   ├── implement  -> ../../.agents/skills/implement
│   ├── create-pr  -> ../../.agents/skills/create-pr
│   ├── review     -> ../../.agents/skills/review
│   ├── judge      -> ../../.agents/skills/judge
│   └── handoff    -> ../../.agents/skills/handoff
├── .my-team/skills-lock.json       # ownership + version + content hash, per skill
├── AGENTS.md                       # + a `## my-team` section
└── CLAUDE.md -> AGENTS.md          # created only if neither file already exists
```

Everything is committed. The repo carries the full skill text in-tree, so it stays
self-describing; a human who types `/implement 12` in that repo runs the same `SKILL.md` the
orchestrator runs, under the **bare** name — the requirement that eliminates the plugin route
(§7.1) — and the same file is reachable from Codex as `$implement` with no second copy (§8).

`my-team sync` obeys one invariant:

> **`sync` writes to `.agents/skills/<name>` only when `<name>` is listed in
> `.my-team/skills-lock.json` with `ejected: false` *and* the on-disk content hash matches the
> hash recorded there. Every other entry under `.agents/skills/` is somebody else's, and `sync`
> neither writes nor deletes it.**

Per skill in the payload:

| State | `sync` does |
| :--- | :--- |
| in lockfile, `ejected: false`, hash matches | rewrite `.agents/skills/<name>`, ensure the `.claude/skills/<name>` symlink |
| in lockfile, `ejected: true` | **nothing** — report as overridden |
| in lockfile, `ejected: false`, hash differs | **nothing** — report as edited-in-place, offer eject-or-restore |
| not in lockfile but present on disk | **nothing** — not ours (e.g. the repo's own skills) |
| in lockfile, absent on disk | recreate it |

Ownership is a positive, explicit fact recorded in one file, not a property inferred from the
filesystem. That matters because `.agents/skills/` is a **shared namespace** — the target repo
may already install skills there with the upstream tool (§6) — so `my-team` must be a good
tenant of a directory it does not own.

### Overrides

`my-team eject <skill>` hands a managed skill to the repo:

1. set `"ejected": { "at": "<my-team version>", "hash": "<sha256>" }` on the lockfile entry;
2. that is all — **no file moves**.

The skill directory stays exactly where it is, so nothing downstream changes: `/implement` still
resolves in Claude Code, `$implement` still resolves in Codex, and the symlink farm is untouched.
From that moment `sync` classifies the entry as not-ours and never writes it again.

The override needs no precedence trick, and that is the point. A skill name maps to exactly one
path — `.agents/skills/<name>` — so the managed version and the override cannot coexist and
cannot race; there is nothing for precedence to arbitrate. Clobber-safety reduces to "is this
name mine?", answered by a lockfile lookup that is identical for every harness. Contrast the
precedence-based override designs in §7.4, which are Claude-Code-only and live outside the repo.

Editing a managed file in place is the wrong move and `sync` says so: row 3 of the table above
catches it by hash and tells the user to eject rather than silently reverting their work.

### Drift

Three kinds, all detectable **offline** — no registry call, checkable on every tick:

| Kind | Test | Meaning |
| :--- | :--- | :--- |
| 1. Stale payload | lockfile `myTeamVersion` ≠ installed CLI version | `my-team sync` is available |
| 2. Tampered managed skill | `sha256(.agents/skills/<n>)` ≠ lockfile `hash` | edited in place; should have been ejected |
| 3. Diverged override | ejected `at` version < current payload version | upstream moved since the fork; 3-way diff, never auto-merge |
| 4. Broken projection | `.claude/skills/<n>` missing or not a symlink to `.agents/skills/<n>` | the Claude Code view drifted from the payload; `sync` repairs it |

Kind 1 works because `my-team` *ships* the skills inside its own package: "is my pinned payload
stale?" is answered by comparing the lockfile's pinned version against the version of the CLI
that is running. No network, works on a plane, and it is one integer comparison at the top of
every command.

Surfaces: `my-team doctor` reports all three plus the shadowing hazard (§4); `my-team sync --check`
exits non-zero for the target repo's CI, which is what makes drift visible without anyone
remembering to look.

### One extra flag for orchestrated ticks

Orchestrated Claude Code runs should invoke `claude -p --setting-sources project`. Without it, a
developer's personal `~/.claude/skills/implement/` silently wins over the repo's (§4) — and that
collision is near-certain for the first user of `my-team`. Caveat in §4. This is a Claude Code
concern only; Codex has no shadowing (§8).

### Harness scope of this recommendation

The layout above is designed to serve both harnesses from one copy of the payload, and §8 shows
that it does. Two parts are harness-specific and should be read as such:

- `.claude/skills/` symlinks and the `--setting-sources project` flag are **Claude Code only**.
- The single unverified dependency is whether **Codex follows a symlink** at
  `.agents/skills/<name>`. The recommendation above deliberately does not require it — the
  payload sits at `.agents/skills/` as **real directories**, and only the Claude-facing
  projection is symlinked, which is documented to work. See §8 for what would change if Codex
  did follow symlinks.

---

## 2. Where Claude Code finds skills

**[documented]** https://code.claude.com/docs/en/skills.md — "Where skills live":

| Location   | Path                                       | Applies to                     |
| :--------- | :----------------------------------------- | :----------------------------- |
| Enterprise | See managed settings                       | All users in your organization |
| Personal   | `~/.claude/skills/<skill-name>/SKILL.md`   | All your projects              |
| Project    | `.claude/skills/<skill-name>/SKILL.md`     | This project only              |
| Plugin     | `<plugin>/skills/<skill-name>/SKILL.md`    | Where plugin is enabled        |

Plus, from the same page:

- **[documented]** Parent directories: "Project skills load from `.claude/skills/` in the
  directory where you start Claude Code and in every parent directory up to the repository root."
- **[documented]** Nested directories below cwd are **not** loaded at startup: "They load the
  first time Claude reads or edits a file inside that subdirectory," and appear under a
  directory-qualified name such as `apps/web:deploy`.
- **[documented]** `--add-dir`: "Claude Code loads `.claude/skills/` and `.claude/commands/`
  from each added directory automatically."
- **[documented]** `~/.claude/skills/synced/` for skills synced from claude.ai when
  `CLAUDE_CODE_SYNC_SKILLS` is set; `synced` is a reserved folder name.
- **[documented]** A skill folder containing `.claude-plugin/plugin.json` "loads as a plugin
  named `<name>@skills-dir`". In a project's `.claude/skills/`, "this requires accepting the
  workspace trust dialog first" — a hazard for non-interactive use, and a reason not to put a
  `plugin.json` in the payload.

Skill *descriptions* are preloaded into context; the body loads only on invocation
(https://code.claude.com/docs/en/skills.md). So a five-skill payload costs five descriptions
of always-on context, not five bodies.

---

## 3. Precedence — the load-bearing answer

**[documented]** https://code.claude.com/docs/en/skills.md, quoted verbatim:

> When skills share the same name, Claude Code resolves the conflict by source:
>
> * Across levels, enterprise overrides personal, and personal overrides project.
>   * For example, with a `deploy` skill in both `~/.claude/skills/` and your project's `.claude/skills/`, `/deploy` runs the personal one.
> * A skill at any of these levels also overrides a bundled skill with the same name, but not the bundled skill's aliases.
> * Plugin skills use a `plugin-name:skill-name` namespace, so they can't conflict with other levels.
>   * For example, `my-plugin/skills/deploy/SKILL.md` becomes `/my-plugin:deploy` and loads alongside a `deploy` skill in your project's `.claude/skills/`.
> * If you have files in `.claude/commands/`, those work the same way, but if a skill and a command share the same name, the skill takes precedence.
> * A skill or command from any of these sources overrides a skill synced from your claude.ai account with the same name.

So the documented order is **enterprise > personal > project > bundled**, with plugins sitting
outside the ordering entirely because they are namespaced.

### Verified by experiment

Run in `<scratchpad>/probe`, a directory whose only content was
`.claude/skills/zzprobe-prec/SKILL.md` emitting `PROJECTWINS`, against
`~/.claude/skills/zzprobe-prec/SKILL.md` emitting `PERSONALWINS`. Each row is the tail of
`claude -p "/zzprobe-prec" --model sonnet --output-format text`.

| Setup | Result | Status |
| :--- | :--- | :--- |
| personal + project, same name | `PERSONALWINS` | **[observed]** — matches the doc |
| project only (personal renamed away) | `PROJECTWINS` | **[observed]** control: project skills do load |
| plugin (`--plugin-dir`) + project, bare `/zzprobe-prec` | `PROJECTWINS` | **[observed]** — matches the doc |
| same, invoked as `/myteam:zzprobe-prec` | `PLUGINWINS` | **[observed]** namespacing is real |
| `--add-dir` payload + project, same bare name | `PROJECTWINS` | **[observed]**, *undocumented tie-break* |
| personal + project, with `--setting-sources project` | `PROJECTWINS` | **[observed]**, *undocumented* |

Two of those are **observed-not-documented** and should be treated as version-pinned behaviour
(re-verify on Claude Code upgrade):

- an in-repo `.claude/skills/<n>` beats an `--add-dir` payload of the same bare name;
- `--setting-sources project` suppresses personal skills. Nothing in
  https://code.claude.com/docs/en/skills.md, https://code.claude.com/docs/en/settings.md, or the
  `--setting-sources` row of https://code.claude.com/docs/en/cli-reference.md mentions skills —
  that row reads only "Comma-separated list of setting sources to load (`user`, `project`, `local`)".

---

## 4. The shadowing hazard (and why `--setting-sources project`)

Because **personal overrides project**, any developer with `~/.claude/skills/implement/` gets
*their* `/implement`, not the target repo's — silently, with no warning, in both interactive and
`-p` sessions.

This is not hypothetical. `/Users/coymcnew/code/my-team/skills-lock.json` pins upstream skills
named `implement`, `handoff`, and `code-review`, and `/Users/coymcnew/code/my-team/.agents/skills/create-pr/`
is authored here — i.e. the *exact* names `my-team` intends to ship. Anyone who has installed
that upstream skill set at user scope shadows the payload on day one.

Mitigations, in order:

1. **Orchestrated ticks**: pass `--setting-sources project`. **[observed]** to suppress personal
   skills. **Caveat**: it also stops loading `~/.claude/settings.json`, so user-level model
   choice, permission allowlists, env, and `apiKeyHelper` go with it — the orchestrator must
   supply those explicitly (`--settings`, `--model`, `--allowedTools`). This is a blunt
   instrument, deliberately chosen because determinism of *which skill ran* is worth more to a
   tick than inheriting user settings.
2. **`my-team doctor`**: list names in `~/.claude/skills/` that collide with the payload and warn
   loudly. This is the only mitigation for the *human* path — a person typing `/implement`
   interactively passes no flags.
3. Not recommended: renaming the payload skills to `myteam-implement` etc. It fixes shadowing but
   breaks the "run `/implement 12` by hand" property that motivates in-repo installation at all.

---

## 5. External injection — yes, it exists, and it costs self-description

There **is** a mechanism to supply skills from outside the working directory. Two, in fact.

- **`--add-dir <path>`** — **[documented]** https://code.claude.com/docs/en/skills.md: "The
  `--add-dir` flag and `/add-dir` command grant file access rather than configuration discovery,
  but skills and commands are an exception: Claude Code loads `.claude/skills/` and
  `.claude/commands/` from each added directory automatically. This exception applies only to
  `--add-dir` and `/add-dir`. The `permissions.additionalDirectories` setting in `settings.json`
  grants file access only and doesn't load skills or commands."
  **[observed]** confirmed: with `$SCRATCH/payload/.claude/skills/zzprobe-addir/SKILL.md` and a
  working directory containing no skills at all, `claude -p "/zzprobe-addir" --add-dir $SCRATCH/payload`
  returned `ADDIRWINS`. Skills arrive under **bare** names, so `/implement` would still be `/implement`.
- **`--plugin-dir <path>` / `--plugin-url <url>`** — `claude --help`: "Load a plugin from a
  directory or .zip for this session only (repeatable)". **[observed]** works, but the skills
  arrive namespaced as `/myteam:implement` (§3), so it fails the bare-name requirement.

So the honest answer to the ticket's question is *yes* — `my-team` could keep its payload in
`~/.my-team/skills/` and pass `--add-dir`, never writing a byte into the target repo.

**What it costs:** the target repo stops being self-describing, completely. The skill text is not
in the tree; a human running plain `claude` in that repo gets no `/implement`; a collaborator who
clones the repo gets nothing; CI gets nothing; and the repo cannot be reasoned about without also
having `my-team` installed at the right version. The whole point of the settled decision — a
human can run `/implement 12` by hand and get identical behaviour — is exactly what injection
gives up. Rejected on those grounds, not on capability grounds.

It remains useful for one narrow thing: `my-team` can inject *orchestrator-private* skills that
the target repo has no business carrying, without polluting the payload.

---

## 6. The existing pattern in this repo

Observed directly with `ls -la /Users/coymcnew/code/my-team/.claude/skills/`: 27 entries, every
one a symlink of the form `<name> -> ../../.agents/skills/<name>`. The real directories live in
`/Users/coymcnew/code/my-team/.agents/skills/`. `/Users/coymcnew/code/my-team/CLAUDE.md` is itself
a symlink to `AGENTS.md`.

### What it gets right — keep all of it

1. **A harness-neutral source of truth — which turns out to be better than neutral.**
   `.agents/skills/` is the one copy; `.claude/skills/` is a *projection* for one harness. That is
   the property that makes a second harness cheap, and §8 shows it is not merely a good instinct:
   `.agents/skills` is Codex's hard-coded repo skill root, so this layout is already dual-harness
   with no second copy and no translation step. Keep it exactly as it is.
2. **Symlinks are officially supported.** **[documented]** https://code.claude.com/docs/en/skills.md:
   "A `<skill-name>` entry in the enterprise, personal, or project locations can be a symlink to a
   directory elsewhere on disk. Claude Code follows the symlink and reads `SKILL.md` from the
   target directory, and if the same target is reachable from more than one location, Claude Code
   loads the skill once." Not a trick — a blessed layout with defined dedup semantics.
3. **A lockfile at all**, with a per-skill content hash — the basis of drift kinds 2 and 3.
4. **Per-skill granularity.** `.claude/skills/` is a farm of independent links, so one skill can be
   ejected without disturbing the other four.
5. **`CLAUDE.md -> AGENTS.md`.** One file, two harnesses. `my-team init` should reproduce this when
   neither file exists (and follow the existing rule in
   `/Users/coymcnew/code/my-team/.agents/skills/setup-matt-pocock-skills/SKILL.md` §4 — never create
   one when the other is already there).

### Where it breaks when *generated* into a foreign repo

1. **A shared namespace with a second writer.** `.agents/skills/` and a root `skills-lock.json`
   are the convention of the upstream installer that produced
   `/Users/coymcnew/code/my-team/skills-lock.json`, and a target repo may already use that
   installer. `my-team` cannot move out of the way — §8 shows `.agents/skills/` is *also* Codex's
   hard-coded repo skill root, so the payload has to live there. Two writers, one tree. The
   recommendation therefore (a) puts my-team's lockfile at **`.my-team/skills-lock.json`** so the
   two lockfiles cannot collide by filename, and (b) makes `sync` write only names its own
   lockfile claims. Residual risk is real and per-name: that installer ships skills called
   `implement`, `handoff`, `code-review`, and `create-pr` — the exact overlap with the my-team
   payload. `my-team init` must detect a pre-existing unclaimed `.agents/skills/<name>` and stop,
   not overwrite.
2. **No managed/unmanaged marker.** Here, every entry is managed and hand-maintenance is the
   author's own business. Generated into a foreign repo, `sync` needs to answer "may I overwrite
   this?" for every entry, and the existing lockfile cannot answer it: a hash mismatch proves the
   file *changed* but not whether the change should be *kept*. The explicit `ejected` marker is
   the one addition the recommendation makes — a positive statement of intent rather than an
   inference from a diff.
3. **The lockfile pins no immutable upstream coordinate.** Entries in
   `/Users/coymcnew/code/my-team/skills-lock.json` carry `source`, `sourceType`, `skillPath`, and
   `computedHash` — but **no ref, commit, tag, or version**. It can verify "this file is what I
   fetched"; it cannot answer "has upstream moved?" or "reinstall exactly what I had". For skills
   that *are* the product, that is not enough — hence the added `myTeamVersion` (drift kind 1).
4. **Locally-authored skills are invisible to the lockfile.**
   `/Users/coymcnew/code/my-team/CLAUDE.md` says so outright: "Skills authored in this repo rather
   than vendored — currently `create-pr` — have no lockfile entry." Absence-means-local is fine when
   a human curates the tree; in a generated tree it is indistinguishable from a corrupt lockfile.
   The `ejected` marker makes local ownership explicit and positive.
5. **Windows.** Git stores symlinks as mode `120000`, but a Windows clone without
   `core.symlinks=true` materialises them as text files containing the target path, and the payload
   silently vanishes. v0.1 targets macOS, so symlink mode is the default; `my-team sync --copy`
   (real directories, ownership falls back to hash comparison, recorded as a mode in the lockfile)
   is the escape hatch when it matters. Not needed for v0.1.

---

## 7. Alternatives rejected

### 7.1 Ship the payload as a Claude Code plugin

The most tempting option — plugins are the purpose-built distribution mechanism, with versioning,
`claude plugin install --scope project`, enable/disable, marketplaces, and updates
(`claude plugin --help`).

**Rejected: namespacing.** **[documented]** "Plugin skills use a `plugin-name:skill-name` namespace,
so they can't conflict with other levels" (https://code.claude.com/docs/en/skills.md), and
**[observed]** `/myteam:zzprobe-prec` → `PLUGINWINS` while bare `/zzprobe-prec` → `PROJECTWINS`.
A plugin therefore *cannot* provide a bare `/implement`; the human would have to type
`/myteam:implement`. That is a different command from the one the docs, the tickets, and the
orchestrator refer to, and it breaks the settled requirement directly.

Two further costs: a marketplace-installed plugin's files live outside the repo, so the repo is no
longer self-describing (only a `.claude/settings.json` entry enabling it is in-tree); and a
skills-directory plugin inside a project `.claude/skills/` "requires accepting the workspace trust
dialog first" (https://code.claude.com/docs/en/skills.md), which is hostile to non-interactive
`claude -p` ticks.

### 7.2 Inject from outside with `--add-dir`

Covered in §5. Capable, but surrenders self-description entirely. Rejected on the settled
requirement, not on capability.

### 7.3 Write the payload directly into `.claude/skills/`, with no `.agents/skills/` tree

The obvious minimal version: one directory, real files, no symlinks.

**Rejected: it is invisible to Codex.** Codex's repo skill root is `.agents/skills` and nothing
else (§8) — a payload that lives only under `.claude/skills/` would need a second, duplicated
copy the day Codex support lands, and two copies of the product's actual payload is exactly the
divergence risk worth paying one symlink per skill to avoid. Writing the canonical copy at
`.agents/skills/` and symlinking into `.claude/skills/` gets both harnesses from one file.

A second, weaker reason: hash-only ownership (no `ejected` marker) can detect that a managed file
changed but cannot distinguish "user deliberately customised this" from "user made a typo", so
every sync becomes an interactive prompt — unusable inside an autonomous tick.

### 7.4 Override via the personal tier (`~/.claude/skills/`)

Documented to work — personal beats project (§3). Rejected: the override then lives outside the
repo, so it is invisible to collaborators and to CI, per-user rather than per-repo, and it turns
the accidental-shadowing hazard of §4 into a sanctioned pattern, which is precisely the wrong
lesson.

---

## 8. Codex

**Codex has a first-class skill concept, and it reads the same `SKILL.md` payload from the same
directory. No parallel representation is needed.** `AGENTS.md` is *not* its only project-context
channel — that was true of earlier Codex, and is no longer true.

This is the finding that reshaped §1, so it is evidenced in detail. Codex CLI was not installed
on this machine (`which codex` → `codex not found`), so everything below is **[documented]** from
OpenAI's docs or read from Codex's source; none of it is **[observed]**.

### 8.1 Codex's repo skill root is literally `.agents/skills`

**[documented]** https://learn.chatgpt.com/docs/build-skills (served from
`https://developers.openai.com/codex/skills`, 308): "Repository skills load from
`$CWD/.agents/skills`, `$CWD/../.agents/skills`, and `$REPO_ROOT/.agents/skills`. User skills come
from `$HOME/.agents/skills`, admin skills from `/etc/codex/skills`."

Confirmed in source —
https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs:

```rust
const AGENTS_DIR_NAME: &str = ".agents";
const SKILLS_DIR_NAME: &str = "skills";
```

So the directory this repo already uses as its skill source of truth
(`/Users/coymcnew/code/my-team/.agents/skills/`, 27 real directories) is not a neutral staging
area that happens to be harness-agnostic — **it is Codex's live read path**. That is why §1 moved
the canonical payload there and demoted `.claude/skills/` to a projection, rather than the
`.my-team/skills/` tree this document originally proposed.

### 8.2 The frontmatter contract is compatible, and deliberately tolerant

**[documented]** https://learn.chatgpt.com/docs/build-skills: "The `SKILL.md` file must include
`name` and `description` fields in YAML frontmatter" — the same two fields Claude Code requires
(https://code.claude.com/docs/en/skills.md).

Codex's parser is permissive about the rest —
https://github.com/openai/codex/blob/main/codex-rs/skills/src/parser.rs:

```rust
#[derive(Debug, Deserialize)]
struct SkillFrontmatter {
    #[serde(default)] name: Option<String>,
    #[serde(default)] description: Option<String>,
    #[serde(default)] model: Option<serde_yaml::Value>,
    #[serde(default)] metadata: SkillFrontmatterMetadata,
}
```

There is **no `#[serde(deny_unknown_fields)]`**, so Claude-Code-specific keys present throughout
the payload — `disable-model-invocation`, `argument-hint`, `allowed-tools` — are silently ignored
rather than fatal. The same file carries a `repair_frontmatter_scalar_fields()` path whose comment
names the case explicitly: "Some third-party skills use prose like `description: Build for AWS: ECS`"
that lacks proper quoting. Codex is built to swallow other vendors' skills.

### 8.3 `agents/openai.yaml` is a Codex file, and the payload already ships it

Every vendored skill in this repo carries one, e.g.
`/Users/coymcnew/code/my-team/.agents/skills/implement/agents/openai.yaml`:

```yaml
interface:
  display_name: "Implement"
  short_description: "Build work from a spec or tickets"
policy:
  allow_implicit_invocation: false
```

That is Codex's own schema, at Codex's own path.
https://github.com/openai/codex/blob/main/codex-rs/skills/src/interface.rs carries the comment
"Interface metadata deserialized from a skill's `agents/openai.yaml` file", and the documented
schema (https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/skill-creator/references/openai_yaml.md)
has exactly the three top-level keys `interface`, `dependencies`, `policy`, with
`allow_implicit_invocation` documented as: "When set to false, the skill requires explicit
invocation via `$skill`; defaults to true."

Note the semantic pairing: `policy.allow_implicit_invocation: false` is the Codex spelling of
Claude Code's `disable-model-invocation: true`, and both appear on the same skills
(`implement`, `handoff`). The payload is already dual-annotated. **[documented]** the file is
optional (https://learn.chatgpt.com/docs/build-skills). `my-team` should ship it for each skill
and treat it as part of the skill, not as generated output.

### 8.4 `AGENTS.md`, and why `CLAUDE.md -> AGENTS.md` is the right topology

Codex reads `AGENTS.md` (https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs,
https://github.com/openai/codex/blob/main/docs/agents_md.md). A GitHub code search for `"CLAUDE.md"`
across `openai/codex` returns 9 hits, **all** of them under `external-agent-migration` /
`external_agent_config_migration` — i.e. one-time import from another agent's config, never
runtime discovery (`gh api search/code -f q='repo:openai/codex "CLAUDE.md"'`).

So `/Users/coymcnew/code/my-team/CLAUDE.md -> AGENTS.md` has the arrow pointing the right way:
`AGENTS.md` is the real file that Codex reads, `CLAUDE.md` is the Claude-facing shim. `my-team init`
should reproduce that direction — never the reverse — and only when neither file already exists.

### 8.5 Where the harnesses genuinely differ

| | Claude Code | Codex |
| :--- | :--- | :--- |
| Repo skill path | `.claude/skills/<n>/SKILL.md` | `.agents/skills/<n>/SKILL.md` |
| Explicit invocation | `/implement` | `$implement` (or the `/skills` picker) |
| Same name in two scopes | personal **shadows** project (§3) | no precedence — "both can appear in skill selectors" |
| Symlinked skill dir | **[documented]** followed (§6) | **UNVERIFIED** |

Two consequences worth carrying forward:

1. **The sigil differs.** A human gets the same *behaviour* on both harnesses from one file, but
   types `/implement` in Claude Code and `$implement` in Codex. The "self-describing repo"
   property survives; literal keystroke parity does not, and no installation mechanism can
   deliver it.
2. **The §4 shadowing hazard is Claude-Code-specific.** **[documented]**
   https://learn.chatgpt.com/docs/build-skills: "If two skills share the same `name`, Codex
   doesn't merge them; both can appear in skill selectors." A user's
   `$HOME/.agents/skills/implement` therefore does not silently displace the repo's — the failure
   mode is an ambiguous picker rather than a silent wrong answer. `--setting-sources project` has
   no Codex counterpart and needs none.

### 8.6 The one open question

**UNVERIFIED: does Codex follow a symlink at `.agents/skills/<name>`?** Claude Code documents that
it does (§6). Codex's `host_roots.rs` deduplicates roots by path
(`dedupe_skill_roots_by_path()` / `roots.retain(|root| seen.insert(root.path.clone()))`) but says
nothing about symlink resolution, and Codex was not installed here to test it.

§1 is deliberately built so the answer does not matter: the payload sits at `.agents/skills/` as
**real directories**, and only the Claude-facing projection is symlinked, which is documented to
work. If Codex is later confirmed to follow symlinks, a pristine store (`.my-team/skills/`) with
both `.agents/skills/` and `.claude/skills/` as symlink farms becomes available, and ownership
could revert to the one-`lstat` test this document originally proposed. That is an optimisation,
not a prerequisite — **verify it before building anything that depends on it.**

---

## 9. Open items

- **UNVERIFIED** — Codex symlink resolution under `.agents/skills/` (§8.6). Test with a real
  Codex install before relying on any symlinked-payload variant.
- **[observed], undocumented** — `--setting-sources project` suppressing personal skills (§3, §4),
  and in-repo project skills beating an `--add-dir` payload (§3). Both are version-pinned to
  Claude Code 2.1.233; re-verify on upgrade, since §4's mitigation depends on the first.
- The upstream installer's lockfile pins no immutable upstream coordinate (§6.3), so
  `my-team`'s lockfile must add its own `myTeamVersion` rather than inheriting that schema.
