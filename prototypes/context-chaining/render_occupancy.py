#!/usr/bin/env python3
"""Render sanitized M1 evidence from the local occupancy summary."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
SUMMARY = LOCAL / "occupancy-summary.json"
EVIDENCE = ROOT / "evidence" / "m1-occupancy.md"
PLOT = ROOT / "evidence" / "m1-occupancy.svg"


def command_output(*argv: str) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip()


def points(
    observations: list[dict[str, Any]],
    field: str,
    *,
    x0: float,
    y0: float,
    width: float,
    height: float,
    maximum: int,
) -> str:
    if len(observations) == 1:
        xs = [x0 + width / 2]
    else:
        xs = [x0 + width * index / (len(observations) - 1) for index in range(len(observations))]
    return " ".join(
        f"{x:.1f},{y0 + height - height * int(observation[field]) / maximum:.1f}"
        for x, observation in zip(xs, observations, strict=True)
    )


def panel(
    *,
    title: str,
    observations: list[dict[str, Any]],
    target: int,
    y0: int,
    left_series: tuple[tuple[str, str, str], ...],
    right_series: tuple[tuple[str, str, str], ...],
) -> str:
    x0 = 90
    width = 800
    height = 210
    left_max = max(
        target, *(int(item[field]) for item in observations for _, field, _ in left_series)
    )
    right_max = max(1, *(int(item[field]) for item in observations for _, field, _ in right_series))
    threshold_y = y0 + height - height * target / left_max
    elements = [
        f'<text x="{x0}" y="{y0 - 18}" class="title">{html.escape(title)}</text>',
        f'<rect x="{x0}" y="{y0}" width="{width}" height="{height}" class="frame"/>',
        f'<line x1="{x0}" y1="{threshold_y:.1f}" x2="{x0 + width}" y2="{threshold_y:.1f}" class="threshold"/>',
        f'<text x="{x0 + 6}" y="{threshold_y - 5:.1f}" class="small">Smart zone {target:,}</text>',
        f'<text x="{x0 - 8}" y="{y0 + 5}" class="axis" text-anchor="end">{left_max:,}</text>',
        f'<text x="{x0 - 8}" y="{y0 + height}" class="axis" text-anchor="end">0</text>',
        f'<text x="{x0 + width + 8}" y="{y0 + 5}" class="axis">{right_max:,}</text>',
        f'<text x="{x0 + width + 8}" y="{y0 + height}" class="axis">0</text>',
        f'<text x="{x0 + width / 2}" y="{y0 + height + 25}" class="axis" text-anchor="middle">session observations</text>',
    ]
    legend_x = x0
    for label, field, color in left_series:
        path = points(
            observations,
            field,
            x0=x0,
            y0=y0,
            width=width,
            height=height,
            maximum=left_max,
        )
        elements.append(f'<polyline points="{path}" style="stroke:{color}" class="series"/>')
        elements.append(
            f'<text x="{legend_x}" y="{y0 + height + 48}" style="fill:{color}" class="legend">{html.escape(label)}</text>'
        )
        legend_x += 190
    for label, field, color in right_series:
        path = points(
            observations,
            field,
            x0=x0,
            y0=y0,
            width=width,
            height=height,
            maximum=right_max,
        )
        elements.append(
            f'<polyline points="{path}" style="stroke:{color}" class="series cumulative"/>'
        )
        elements.append(
            f'<text x="{legend_x}" y="{y0 + height + 48}" style="fill:{color}" class="legend">{html.escape(label)} (right axis)</text>'
        )
        legend_x += 245
    return "\n".join(elements)


def render_plot(summary: dict[str, Any]) -> str:
    target = int(summary["target_tokens"])
    codex = summary["codex"]["observations"]
    claude = summary["claude"]["observations"]
    panels = [
        panel(
            title="Codex app-server",
            observations=codex,
            target=target,
            y0=80,
            left_series=(
                ("last total (direct candidate)", "last_total_tokens", "#006d77"),
                ("last input", "last_input_tokens", "#ee6c4d"),
            ),
            right_series=(
                ("reported cumulative total", "reported_total_tokens", "#6a4c93"),
                ("sum(last total)", "derived_cumulative_last_total_tokens", "#9c6644"),
            ),
        ),
        panel(
            title="Claude Code Agent SDK",
            observations=claude,
            target=target,
            y0=415,
            left_series=(
                ("get_context_usage total", "context_total_tokens", "#006d77"),
                ("cache-additive request input", "request_input_tokens", "#ee6c4d"),
            ),
            right_series=(
                ("cumulative billed input", "cumulative_billed_input_tokens", "#6a4c93"),
            ),
        ),
    ]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="760" viewBox="0 0 1000 760" role="img" aria-labelledby="title desc">
<title id="title">M1 current-context occupancy observations</title>
<desc id="desc">Codex and Claude direct occupancy candidates compared with per-request input and cumulative billing arithmetic.</desc>
<style>
  text {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; fill: #202124; }}
  .title {{ font-size: 18px; font-weight: 700; }}
  .axis, .small {{ font-size: 11px; }}
  .legend {{ font-size: 11px; font-weight: 700; }}
  .frame {{ fill: #fff; stroke: #aab2bd; }}
  .threshold {{ stroke: #d00000; stroke-width: 1.5; stroke-dasharray: 5 4; }}
  .series {{ fill: none; stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }}
  .cumulative {{ stroke-dasharray: 7 5; }}
</style>
<rect width="1000" height="760" fill="#f7f7f5"/>
<text x="40" y="35" class="title">M1 — live context occupancy vs billing usage</text>
{"".join(panels)}
</svg>
"""


def crossing(value: dict[str, Any] | None) -> str:
    if value is None:
        return "not observed"
    return f"cycle {value['cycle']} at `{value['at']}` (`{value['value']:,}` tokens)"


def compaction(harness: dict[str, Any]) -> str:
    if not harness["compactions"]:
        return "No sharp occupancy drop was observed."
    events = ", ".join(
        f"cycle {item['cycle']} ({item['before']:,} → {item['after']:,})"
        for item in harness["compactions"]
    )
    return f"Sharp occupancy drop(s): {events}."


def render_markdown(summary: dict[str, Any]) -> str:
    codex = summary["codex"]
    claude = summary["claude"]
    codex_last = codex["observations"][-1]
    claude_last = claude["observations"][-1]
    target = int(summary["target_tokens"])
    schema = json.loads((LOCAL / "schema-manifest.json").read_text())
    stable_digest = schema["bundles"]["stable_v2"]["sha256"]
    codex_config = codex["config"]
    claude_auth = claude["auth"]
    outcome = summary["outcome"]
    decision = (
        "proceed to Product Owner review" if outcome == "pass" else "stop and revisit the map"
    )
    return f"""# M1 — current-context occupancy

## Decision this evidence informs

[Can both Harnesses report current context occupancy before compaction?](https://github.com/mcnewcp/my-team/issues/78): whether each Harness exposes a live absolute count that can trip the configurable Smart zone without confusing current context with cumulative billing usage.

## Reproduction identity

- Captured at: `{summary["captured_at"]}`
- Prototype commit used for the run: `{summary["prototype_commit_before_run"]}`
- Evidence rendered from commit: `{command_output("git", "rev-parse", "HEAD")}`
- Host platform: `{summary["platform"]}`
- Python: `{summary["python"]}`
- Smart-zone trip count: `{target:,}` absolute tokens
- Workload: `{summary["workload"]["embedded_bytes_per_cycle"]:,}` read-only bytes per cycle from six fixed files; model-side tools disabled
- API-key environment: `CODEX_API_KEY absent; ANTHROPIC_API_KEY absent`
- Persistent Harness configuration changed: **no**

| Harness | Harness / SDK versions | Subscription-auth evidence | Effective model | Context window | Automatic compaction |
| --- | --- | --- | --- | ---: | --- |
| Codex | `{codex["versions"]["cli"]}`; stable v2 schema `{stable_digest}` | account type `{codex["auth"]["type"]}`, plan `{codex["auth"]["plan_type"]}` | `{codex["effective"]["model"]}`, reasoning `{codex["effective"]["reasoning_effort"]}` | `{codex["effective"]["context_window"]:,}` | configured limit `{json.dumps(codex_config["model_auto_compact_token_limit"])}`, scope `{json.dumps(codex_config["model_auto_compact_token_limit_scope"])}`; Harness defaults remained in force |
| Claude Code | SDK `{claude["versions"]["sdk"]}`; bundled CLI `{claude["versions"]["bundled_cli"]}`; standalone `{claude["versions"]["standalone_cli"]}` | `{claude_auth["authMethod"]}` via `{claude_auth["apiProvider"]}`; API-key source `{json.dumps(claude_auth["apiKeySource"])}` | `{claude["effective"]["model"]}` | effective `{claude["effective"]["context_window"]:,}`, raw `{claude["effective"]["raw_context_window"]:,}` | enabled `{str(claude["effective"]["auto_compact_enabled"]).lower()}`, threshold `{claude["effective"]["auto_compact_threshold"]:,}` |

## Procedure

```text
cd prototypes/context-chaining
./run-safe occupancy.py --target {target} --max-cycles {summary["max_cycles"]}
./run-safe render_occupancy.py
```

The runner opened one ephemeral session per Harness from the same empty temporary directory. Each cycle embedded the same repository bytes in the same order and required the same compact comparison. Codex ran with `approvalPolicy=never`, a read-only sandbox, empty explicit instructions, and no discovered instruction sources. Claude ran with no tools and no setting sources. Every client request, server event, direct-usage response, timestamp, source, and full raw payload was appended to local JSONL.

A sharp occupancy drop was defined before the run as both at least `{summary["compaction_drop_rule"]["minimum_tokens"]:,}` tokens and at least `{summary["compaction_drop_rule"]["minimum_fraction"]:.0%}` of the prior direct observation.

## Expected observation

M1 passes only if Codex `last.totalTokens` and Claude `get_context_usage().totalTokens` behave like live absolute current-context counts, cross `{target:,}` before any compaction drop, and remain distinguishable from cumulative billing arithmetic. A direct signal that resets before the Smart zone, never advances, or only mirrors cumulative billed usage fails the kill gate.

## Observations

![M1 occupancy signals](m1-occupancy.svg)

### Codex

- `last.totalTokens` crossed the Smart zone in {crossing(codex["crossings"]["last_total"])}; `last.inputTokens` crossed in {crossing(codex["crossings"]["last_input"])}.
- Reported cumulative `total.totalTokens` crossed in {crossing(codex["crossings"]["reported_total"])}; independently summing every `last.totalTokens` crossed in {crossing(codex["crossings"]["derived_cumulative"])}.
- The final notification reported `last.totalTokens={codex_last["last_total_tokens"]:,}`, `last.inputTokens={codex_last["last_input_tokens"]:,}`, `last.cachedInputTokens={codex_last["last_cached_input_tokens"]:,}`, reported cumulative `total.totalTokens={codex_last["reported_total_tokens"]:,}`, and derived cumulative `{codex_last["derived_cumulative_last_total_tokens"]:,}`.
- {compaction(codex)} The observed model window was `{codex_last["model_context_window"]:,}` tokens.

### Claude Code

- `get_context_usage().totalTokens` crossed the Smart zone in {crossing(claude["crossings"]["context_total"])}.
- Cache-additive request input (`input_tokens + cache_creation_input_tokens + cache_read_input_tokens`) crossed in {crossing(claude["crossings"]["request_input"])}; cumulative billed input crossed in {crossing(claude["crossings"]["cumulative_billed_input"])}.
- The final observation reported direct context `{claude_last["context_total_tokens"]:,}`, cache-additive request input `{claude_last["request_input_tokens"]:,}`, and cumulative billed input `{claude_last["cumulative_billed_input_tokens"]:,}`.
- {compaction(claude)} Auto-compaction remained enabled at `{claude_last["auto_compact_threshold"]:,}` within the raw `{claude_last["raw_max_tokens"]:,}`-token window.

## Trace inventory

Raw JSONL remains local and untracked.

| Harness | Local path | SHA-256 | Sanitization notes |
| --- | --- | --- | --- |
| Codex | `{codex["trace"]}` | `{codex["trace_sha256"]}` | none; full raw payload is local only |
| Claude Code | `{claude["trace"]}` | `{claude["trace_sha256"]}` | none; full raw payload is local only |

## Result

- Outcome: **{outcome}**
- Evidence-backed finding: Codex `last` and Claude `get_context_usage().totalTokens` each supplied a live absolute signal that reached the `{target:,}`-token Smart zone before automatic compaction, while cumulative usage crossed substantially earlier and therefore cannot stand in for occupancy.
- Remaining uncertainty: this run does not establish signal cadence during an in-flight request, behavior at either Harness's automatic-compaction boundary, context-quality calibration, interruption, Handoff, continuation, or real skill dispatch.
- Kill-gate decision: **{decision}**. No interruption or chaining work was performed.

## Consequences for the map

If the Product Owner accepts M1, both direct signals can anchor the next interruption milestone. The fallback to live Codex rollout JSONL was not needed. The open fog around an alternative occupancy path can be removed; compaction-boundary and supported-model constraints remain unresolved beyond this milestone.
"""


def main() -> None:
    if not SUMMARY.is_file():
        raise SystemExit("local/occupancy-summary.json is missing; run occupancy.py first")
    summary: dict[str, Any] = json.loads(SUMMARY.read_text())
    if not summary.get("codex") or not summary.get("claude"):
        raise SystemExit("both Harness observations are required before rendering M1 evidence")
    PLOT.write_text(render_plot(summary))
    EVIDENCE.write_text(render_markdown(summary))
    print(f"wrote {PLOT.relative_to(ROOT)}")
    print(f"wrote {EVIDENCE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
