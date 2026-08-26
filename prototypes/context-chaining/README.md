# PROTOTYPE — autonomous context chaining

Throwaway scaffolding for the experiment mapped by
[Explore autonomous context chaining across Claude Code and Codex](https://github.com/mcnewcp/my-team/issues/75).
It prepares the environment; milestone behavior and production design live elsewhere.

The prototype has two non-negotiable safety properties:

- every Harness process runs without `CODEX_API_KEY` or `ANTHROPIC_API_KEY`; and
- the workload is read-only at both the prompt and Harness permission layers.

Raw protocol traces, generated schemas, Handoffs, and other run artifacts stay under `local/`.
That directory is present but ignored so traces cannot be committed accidentally. Only sanitized
evidence belongs in `evidence/`.

## Prepare

From this directory:

```sh
uv sync --frozen
./run-safe prepare.py
./run-safe environment_probe.py
```

`run-safe` removes both API-key variables before starting Python. The Python entry points also
refuse to run if either variable is present, so bypassing the wrapper fails closed.

`prepare.py` generates the stable and experimental schemas from the installed Codex binary into
`local/schemas/`, then writes `local/schema-manifest.json` with the CLI version and SHA-256 for
each v2 bundle. It never writes Harness configuration.

`environment_probe.py` performs one inert, no-tool query through each Harness from a temporary
empty directory outside the repository, so it does not load or transmit repository instructions.
It records a sanitized environment report in `evidence/environment.md` and raw query events under
`local/traces/`. It requires existing subscription logins; it never starts a login flow and never
persists a model or Harness setting. Codex configuration is read separately and reduced to the
model and compaction fields before it enters sanitized evidence.

The Claude Agent SDK is pinned to the version researched for this map. `uv.lock` is the complete
dependency record for the isolated `.venv` in this directory.

## Experiment inputs

- `workload.md` defines the harmless read-heavy workload and its permission envelope.
- `evidence/milestone-template.md` is copied for each milestone report.
- `local/schema-manifest.json` identifies the generated Codex schemas used by a run.

The desired v0.1 Smart-zone boundary is 200,000 tokens, but milestone runners must accept an
arbitrary positive count so mechanics can be exercised cheaply. This setup does not claim that
either Harness can reach the default before automatic compaction.

## M1 — current-context occupancy

`occupancy.py` opens one ephemeral session per Harness and repeats the same read-only payload until
the direct context signal crosses a configured absolute count, a sharp occupancy drop indicates
compaction, or the cycle limit is reached. The files are embedded into each prompt so the payload
is byte-for-byte comparable and model-side tools remain disabled. It records full raw payloads
under `local/traces/` and a local derived summary, without changing persistent Harness settings.

From this directory:

```sh
./run-safe occupancy.py --target 200000 --max-cycles 40
./run-safe render_occupancy.py
```

The renderer writes the sanitized report and SVG plot under `evidence/`. Review M1 before adding
interruption, Handoff, continuation, or skill-dispatch behavior.

## M2 — absolute-occupancy interruption

`interrupt.py` reuses the accepted M1 signals and adds only the configured count check and
interrupt-to-terminal path. Codex checks `last.totalTokens` at the completed-turn cadence observed
in M1, starts the next turn, sends `turn/interrupt`, and keeps consuming app-server events through
the matching `turn/completed`. Claude starts its interrupt-target query, checks
`get_context_usage().totalTokens` through the live control channel, calls `interrupt()`, and drains
`receive_response()` through exactly one terminal `ResultMessage`.

An arbitrary positive target can exercise the mechanics cheaply. The accepted M1 run already
established that both effective Harness/model combinations can cross the desired 200,000-token
default before compaction.

From this directory:

```sh
./run-safe interrupt.py --target 50000 --max-cycles 12
```

The run writes full raw protocol events under `local/traces/` and a derived local summary at
`local/interruption-summary.json`. Stop and review the sanitized M2 evidence before adding a
Handoff turn.

## M3 — same-session Handoff

`interrupt.py --handoff` retains the M2 threshold and interrupt path, then drains the interrupted
turn before asking the same live session to write a one-line placeholder Handoff under
`local/handoffs/`. The Handoff is nonce-bearing so the runner can distinguish the current run's
artifact from stale output. It records session identity, current-context occupancy immediately
before and after the Handoff, the consumed headroom, and the remaining context window.

Codex opts into its experimental API for an explicit background-terminal list/clean/list sequence
between the interrupted terminal event and the Handoff turn. The Handoff turn alone receives a
workspace-write sandbox rooted at its ignored artifact directory. Claude exposes only `Write` and
uses a permission callback that denies every call except the exact Handoff path during the
Handoff phase. No successor session is created.

From this directory:

```sh
./run-safe interrupt.py --handoff --target 50000 --max-cycles 12
```

The run writes raw protocol events under `local/traces/`, the ignored Handoffs under
`local/handoffs/`, and a derived local summary at `local/handoff-summary.json`. Stop and review the
sanitized M3 evidence before adding fresh-session continuation.

Running `workload.md` sends the listed repository files to the selected model service. Preparing
the workload does not authorize that transfer; obtain the Product Owner's explicit approval before
a milestone runner executes it against a private repository.
