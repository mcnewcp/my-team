# PROTOTYPE — one tick against a real issue

Throwaway. Answers [my-team#13](https://github.com/mcnewcp/my-team/issues/13): does the
tick model settled in [ADR 0002](../../docs/adr/0002-draft-flag-is-the-implementer-latch.md)
survive contact with reality?

Not production shape and never will be. `tick.py` transcribes the 16-row ladder row for
row so that running it exercises the *design*, not a paraphrase of it.

## Run it

```sh
cd prototypes/one-tick
python3 tick.py              # observe, derive, print. Mutates nothing.
python3 tick.py --calibrate  # cheapest real headless dispatch — checks the stream shape
python3 tick.py --act        # observe, derive, take exactly one action, exit
```

Config is the `CONFIG` dict at the top of `tick.py`. Target is
`mcnewcp/personal-assistant#17`, a genuine `ready-for-agent` issue filed for this spike.

## Shape

- `tick.py` — `observe()` builds one snapshot from GitHub REST, `derive()` is the ladder,
  `act()` wires up **only the implementer rows** (6 `UNSTARTED`, 7 `NO_PR`,
  8 `IMPLEMENTING`, 9 `NEEDS_PR_AUTHORING`). Rows 10–16 print what they would do and exit;
  the reviewer and judge identities are [#16](https://github.com/mcnewcp/my-team/issues/16)'s job.
- `harness.py` — drives `claude -p` per the contract in
  [#3](https://github.com/mcnewcp/my-team/issues/3): raw CLI not the SDK, `stream-json`,
  context read passively off each assistant message's `usage`, outcome taken from the
  `result` event's `is_error` rather than the exit code.

Workspace and streams land under `~/.local/state/my-team/mcnewcp-personal-assistant/17/`
(`worktree/`, `handoffs/`, `streams/`) per
[ADR 0001](../../docs/adr/0001-isolated-worktree-and-handoffs-outside-git.md).

## Findings

Recorded in the resolution comment on
[my-team#13](https://github.com/mcnewcp/my-team/issues/13).
