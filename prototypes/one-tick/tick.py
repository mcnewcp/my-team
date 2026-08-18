#!/usr/bin/env python3
"""PROTOTYPE -- throwaway. One tick against a real issue in a real repo.

Answers my-team#13: does the tick model survive contact with reality?

    python3 tick.py                # observe, derive, print. Mutates nothing.
    python3 tick.py --act          # observe, derive, take exactly one action, exit.
    python3 tick.py --calibrate    # cheap headless dispatch to check the stream shape.

One observation, one action, exit. The orchestrator stores nothing durable; every run
rebuilds its whole picture from GitHub. The ladder below is ADR 0002's, transcribed row
for row, evaluated top-down, first match wins.

Only the implementer rows (6, 7, 8, 9) have actions wired up. Everything else prints what
it *would* do and exits -- the reviewer and judge identities are my-team#16's job.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import harness

CONFIG = {
    "repo": "mcnewcp/personal-assistant",
    "issue": 17,
    "base": "main",
    "local_repo": Path.home() / "code" / "personal-assistant",
    # Declared, never inferred. Empty list == "this repo has no CI gate", which is
    # distinguishable from "CI has not started yet" only because it is declared.
    "required_checks": [],
    # Numeric ids, never logins -- REST and gh disagree on the [bot] suffix.
    "roles": {
        "implementer": 16102656,  # mcnewcp; the spike runs the implementer on personal auth
        "reviewer": None,         # shane-my-team is provisioned but off the implementer path
        "judge": None,            # not provisioned yet (my-team#16)
    },
    "require_approval_to_merge": False,
    "state_root": Path.home() / ".local" / "state" / "my-team",
}

FORMAL_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED"}

ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "NotebookEdit", "Skill",
    "Bash(git:*)", "Bash(uv:*)", "Bash(uvx:*)",
    "Bash(gh pr ready:*)", "Bash(gh pr view:*)", "Bash(gh issue view:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(mkdir:*)", "Bash(rm:*)", "Bash(mv:*)", "Bash(cp:*)",
    "Bash(find:*)", "Bash(grep:*)", "Bash(sed:*)", "Bash(head:*)", "Bash(tail:*)",
    "Bash(wc:*)", "Bash(echo:*)", "Bash(touch:*)", "Bash(chmod:*)", "Bash(test:*)",
    "Bash(which:*)", "Bash(python3:*)", "Bash(pytest:*)", "Bash(ruff:*)",
]

IMPLEMENTER_PERSONA = """You are Robin, the implementer on this repository's agent team.
You write the code, you commit it, you push it. You do not review your own work -- a
separate reviewer and a judge do that on the pull request once you have handed off. Write
in your own voice; never announce who you are."""


# --------------------------------------------------------------------------- shelling out

def sh(args, cwd=None, check=True, capture=True):
    p = subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=True,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(str(a) for a in args)}\n{p.stderr or p.stdout}")
    return p


def gh_json(path, check=True):
    p = sh(["gh", "api", path], check=False)
    if p.returncode != 0:
        if check:
            raise RuntimeError(f"gh api {path}\n{p.stderr}")
        return None
    return json.loads(p.stdout) if p.stdout.strip() else None


# --------------------------------------------------------------------------- observation

@dataclass
class Observation:
    at: str
    issue_state: str = ""
    issue_title: str = ""
    issue_body: str = ""
    issue_labels: list = field(default_factory=list)
    branches: list = field(default_factory=list)      # [{name, sha}] from the remote
    commits_ahead: int | None = None
    open_pr_count: int = 0
    pr: dict | None = None                             # the PR under consideration
    reviews: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    draft_events: list = field(default_factory=list)
    closing_refs: list = field(default_factory=list)

    # derived predicates, computed once so the ladder reads like the ADR
    ci_ok: bool = True
    ever_reviewed: bool = False


def observe(cfg):
    repo, n, base = cfg["repo"], cfg["issue"], cfg["base"]
    owner = repo.split("/")[0]
    o = Observation(at=time.strftime("%Y-%m-%dT%H:%M:%S"))

    issue = gh_json(f"repos/{repo}/issues/{n}")
    o.issue_state = issue["state"]
    o.issue_title = issue["title"]
    o.issue_body = issue["body"] or ""
    o.issue_labels = [lab["name"] for lab in issue["labels"]]

    refs = gh_json(f"repos/{repo}/git/matching-refs/heads/my-team/{n}-", check=False) or []
    o.branches = [
        {"name": r["ref"].removeprefix("refs/heads/"), "sha": r["object"]["sha"]} for r in refs
    ]

    if len(o.branches) == 1:
        branch = o.branches[0]["name"]
        cmp_ = gh_json(f"repos/{repo}/compare/{base}...{branch}", check=False)
        if cmp_:
            o.commits_ahead = cmp_["ahead_by"]

        prs = gh_json(f"repos/{repo}/pulls?head={owner}:{branch}&state=all&per_page=100") or []
        o.open_pr_count = sum(1 for p in prs if p["state"] == "open")
        chosen = next((p for p in prs if p["state"] == "open"), None)
        if chosen is None and prs:
            chosen = sorted(prs, key=lambda p: p["number"])[-1]

        if chosen is not None:
            full = gh_json(f"repos/{repo}/pulls/{chosen['number']}")
            o.pr = {
                "number": full["number"],
                "state": full["state"],
                "isDraft": full["draft"],
                "merged": full["merged"],
                "headRefOid": full["head"]["sha"],
                "mergeable_state": full["mergeable_state"],
                "title": full["title"],
                "url": full["html_url"],
            }
            reviews = gh_json(f"repos/{repo}/pulls/{full['number']}/reviews") or []
            o.reviews = [
                {
                    "id": r["id"],
                    "author_id": r["user"]["id"],
                    "author_login": r["user"]["login"],
                    "state": r["state"],
                    "commit_id": r.get("commit_id"),
                    "submitted_at": r.get("submitted_at"),
                }
                for r in reviews
            ]
            timeline = gh_json(
                f"repos/{repo}/issues/{full['number']}/timeline?per_page=100", check=False
            ) or []
            o.draft_events = sorted(
                (
                    {
                        "id": e["id"],
                        "event": e["event"],
                        "actor": (e.get("actor") or {}).get("login"),
                        "at": e.get("created_at"),
                    }
                    for e in timeline
                    if e.get("event") in ("convert_to_draft", "ready_for_review")
                ),
                key=lambda e: e["id"],
            )
            runs = gh_json(f"repos/{repo}/commits/{o.pr['headRefOid']}/check-runs", check=False)
            o.checks = [
                {"name": c["name"], "status": c["status"], "conclusion": c["conclusion"]}
                for c in (runs or {}).get("check_runs", [])
            ]

    o.ever_reviewed = bool(o.reviews)
    o.ci_ok = _ci_ok(o, cfg)
    return o


def _required(o, cfg):
    names = cfg["required_checks"]
    return [c for c in o.checks if c["name"] in names]


def _ci_ok(o, cfg):
    req = _required(o, cfg)
    if not cfg["required_checks"]:
        return True  # declared empty: no CI gate
    if len(req) < len(cfg["required_checks"]):
        return False  # a declared check has not reported at head
    return all(c["status"] == "completed" and c["conclusion"] == "success" for c in req)


def current(review, o):
    return o.pr is not None and review.get("commit_id") == o.pr["headRefOid"]


def latest_from(o, role_id, states=None):
    """Most recent review by a numeric identity, optionally filtered by state."""
    if role_id is None:
        return None
    hits = [
        r for r in o.reviews
        if r["author_id"] == role_id and (states is None or r["state"] in states)
    ]
    return sorted(hits, key=lambda r: r["id"])[-1] if hits else None


# --------------------------------------------------------------------------- the ladder

def derive(o, cfg):
    """ADR 0002's ladder. Top-down, first match wins -- the order IS the tie-breaker."""
    roles = cfg["roles"]
    known = {v for v in roles.values() if v is not None}
    pr = o.pr

    # 1
    if "ready-for-human" in o.issue_labels:
        return 1, "ESCALATED", "ready-for-human present", "none -- exit"
    # 2
    if o.issue_state == "closed":
        return 2, "HALTED", "issue closed", "none -- exit, workspace left intact"
    if "ready-for-agent" not in o.issue_labels:
        return 2, "HALTED", "ready-for-agent absent", "none -- exit, workspace left intact"
    if pr and pr["state"] == "closed" and not pr["merged"]:
        return 2, "HALTED", "PR closed unmerged", "none -- exit, workspace left intact"
    # 3
    if len(o.branches) > 1:
        return 3, "AMBIGUOUS", f"{len(o.branches)} matching branches", "escalate"
    if o.open_pr_count > 1:
        return 3, "AMBIGUOUS", f"{o.open_pr_count} open PRs", "escalate"
    strangers = [
        r for r in o.reviews
        if r["state"] in FORMAL_REVIEW_STATES and r["author_id"] not in known
    ]
    if strangers:
        who = ", ".join(sorted({str(r["author_login"]) for r in strangers}))
        return 3, "AMBIGUOUS", f"formal review from unrecognised identity: {who}", "escalate"
    if pr and pr["state"] == "open" and o.commits_ahead == 0:
        return 3, "AMBIGUOUS", "PR with zero commits ahead of base", "escalate"
    # 4
    if pr and pr["state"] == "open" and pr["mergeable_state"] == "unknown":
        return 4, "OBSERVATION_UNSETTLED", "mergeable_state is 'unknown'", "wait"
    # 5
    if pr and pr["merged"]:
        return 5, "MERGED", "PR merged", "tear down workspace -- terminal"
    # 6
    if not o.branches:
        return 6, "UNSTARTED", "no matching remote branch", "worktree + branch; dispatch /implement"
    # 7
    if (o.commits_ahead or 0) > 0 and o.open_pr_count == 0:
        return 7, "NO_PR", "branch has commits, no PR", "mechanically open a draft PR"
    # 8
    if pr and pr["isDraft"]:
        return 8, "IMPLEMENTING", "PR isDraft", "dispatch implementer /implement"
    # 9
    if pr and not pr["isDraft"] and not o.ever_reviewed:
        return 9, "NEEDS_PR_AUTHORING", "PR ready, never reviewed", "dispatch implementer /create-pr"
    # 10 / 11
    req = _required(o, cfg)
    failed = [c for c in req if c["status"] == "completed" and c["conclusion"] not in ("success", "neutral", "skipped")]
    if failed:
        return 10, "CI_FAILED", f"failed at head: {[c['name'] for c in failed]}", "convert PR to draft"
    unresolved = [c for c in req if c["status"] != "completed"] + [
        name for name in cfg["required_checks"] if name not in {c["name"] for c in req}
    ]
    if unresolved:
        return 11, "CI_PENDING", f"unresolved at head: {unresolved}", "wait"
    # 12
    rev = latest_from(o, roles["reviewer"], {"COMMENTED"})
    if o.ci_ok and not (rev and current(rev, o)):
        return 12, "NEEDS_REVIEW", "no current reviewer COMMENT", "dispatch reviewer /review"
    # 13
    verdict = latest_from(o, roles["judge"], FORMAL_REVIEW_STATES)
    if o.ci_ok and not (verdict and current(verdict, o)):
        return 13, "NEEDS_JUDGMENT", "no current judge verdict", "dispatch judge /judge"
    # 14
    if verdict["state"] == "CHANGES_REQUESTED":
        return 14, "REVISION_REQUIRED", "current judge CHANGES_REQUESTED", "convert PR to draft"
    # 15
    if cfg["require_approval_to_merge"]:
        human = [r for r in o.reviews if r["state"] == "APPROVED" and r["author_id"] not in known]
        if not any(current(r, o) for r in human):
            return 15, "NEEDS_HUMAN_APPROVAL", "flag set, no current human APPROVED", "wait"
    # 16
    return 16, "MERGEABLE", "current judge APPROVED, ci_ok", "squash-merge under the judge's identity"


# --------------------------------------------------------------------------- workspace

def paths(cfg):
    slug = cfg["repo"].replace("/", "-")
    state_dir = cfg["state_root"] / slug / str(cfg["issue"])
    return state_dir, state_dir / "worktree", state_dir / "handoffs"


def branch_name(cfg, title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"my-team/{cfg['issue']}-{s[:50].rstrip('-')}"


def ensure_worktree(cfg, branch):
    state_dir, wt, handoffs = paths(cfg)
    handoffs.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        print(f"  worktree already present: {wt}")
        return wt, handoffs
    repo = cfg["local_repo"]
    print(f"  git fetch origin {cfg['base']}")
    sh(["git", "-C", repo, "fetch", "origin", cfg["base"]])
    print(f"  git worktree add -b {branch} {wt} origin/{cfg['base']}")
    sh(["git", "-C", repo, "worktree", "add", "-b", branch, str(wt), f"origin/{cfg['base']}"])
    return wt, handoffs


def read_handoffs(handoffs):
    if not handoffs.exists():
        return []
    return sorted(p for p in handoffs.glob("*.md"))


# --------------------------------------------------------------------------- prompts

def implement_prompt(cfg, o, branch, handoffs):
    docs = read_handoffs(handoffs)
    if o.pr:
        pr_clause = (
            f"- An open **draft** pull request already exists for this branch: "
            f"#{o.pr['number']} ({o.pr['url']}). When this round of work is complete -- the "
            f"acceptance criteria are met and the tests pass -- run `gh pr ready "
            f"{o.pr['number']}`. That command is your declaration that the round is finished. "
            f"Nothing else you write is read by the orchestrator: not your final message, not "
            f"a commit message, not a comment. If the work is NOT finished, leave the pull "
            f"request as a draft."
        )
    else:
        pr_clause = (
            "- No pull request exists yet. The orchestrator opens one mechanically once you "
            "have pushed a commit. Do not open one yourself."
        )

    if cfg["required_checks"]:
        observed = {c["name"]: c["conclusion"] or c["status"] for c in o.checks}
        ci_clause = f"- CI at the current head: {observed or 'nothing reported yet'}."
    else:
        ci_clause = (
            "- This repository has no CI yet. Run the tests locally before you declare the "
            "round finished."
        )

    handoff_clause = ""
    if docs:
        bodies = "\n\n".join(f"### {p.name}\n\n{p.read_text()}" for p in docs)
        handoff_clause = (
            "\n## Handoff from a previous session\n\n"
            "A previous copy of your role stopped before finishing and left this for you.\n\n"
            f"{bodies}\n"
        )

    return f"""{IMPLEMENTER_PERSONA}

## Your task

Implement issue #{cfg['issue']} in `{cfg['repo']}`.

### #{cfg['issue']} -- {o.issue_title}

{o.issue_body}
{handoff_clause}
## Working agreement

- You are in a git worktree of `{cfg['repo']}` on branch `{branch}`. Work here. This is not
  the human's checkout; you have it to yourself.
- Invoke the `/implement` skill. **Ignore its final step telling you to run `/code-review`** --
  a separate reviewer role does that on the pull request after you hand off.
- Commit with a Conventional Commits message, then `git push -u origin {branch}`.
{pr_clause}
{ci_clause}
- If you run low on context before the work is done, write a handoff document into
  `{handoffs}` and stop. That directory sits beside the worktree, outside git, on purpose --
  nothing you put there can ever be committed. Do not mark the pull request ready.
"""


def create_pr_prompt(cfg, o, branch):
    return f"""{IMPLEMENTER_PERSONA}

## Your task

Pull request #{o.pr['number']} ({o.pr['url']}) was opened mechanically with a placeholder
title. Rewrite its title and description so they read as the squashed commit that will land
on `{cfg['base']}`.

- The title is a Conventional Commit subject line: `<type>(<optional scope>): <subject>`,
  imperative mood, lowercase after the colon, no trailing period.
- The body is the commit body: what changed and why, in prose. It must keep a line linking
  the issue -- `Closes #{cfg['issue']}` -- so the merge closes it.
- Read the diff (`git log origin/{cfg['base']}..{branch}`, `git diff origin/{cfg['base']}...HEAD`)
  and describe what is actually there.
- Apply it with `gh pr edit {o.pr['number']} --title ... --body ...`, then stop. Do not
  change any code.
"""


# --------------------------------------------------------------------------- actions

def act(row, state, o, cfg, timeout):
    state_dir, wt, handoffs = paths(cfg)
    log_dir = state_dir / "streams"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    if row == 6:
        branch = branch_name(cfg, o.issue_title)
        wt, handoffs = ensure_worktree(cfg, branch)
        print(f"\n  dispatching implementer /implement in {wt}")
        d = harness.dispatch(
            implement_prompt(cfg, o, branch, handoffs),
            cwd=wt,
            add_dirs=[handoffs],
            allowed_tools=ALLOWED_TOOLS,
            timeout=timeout,
            log_path=log_dir / f"{stamp}-row6-implement.jsonl",
        )
        print("\n" + harness.summarise(d))
        return d

    if row == 7:
        branch = o.branches[0]["name"]
        title = f"chore: implementing issue {cfg['issue']}"
        body = f"Closes #{cfg['issue']}\n\nOpened mechanically by my-team. Title and description are placeholders."
        print(f"  gh pr create --draft --head {branch}")
        p = sh([
            "gh", "pr", "create", "--repo", cfg["repo"], "--draft",
            "--base", cfg["base"], "--head", branch,
            "--title", title, "--body", body,
        ], check=False)
        print("  " + (p.stdout or p.stderr).strip())
        return None

    if row == 8:
        branch = o.branches[0]["name"]
        wt, handoffs = ensure_worktree(cfg, branch)
        print(f"\n  dispatching implementer /implement in {wt}")
        d = harness.dispatch(
            implement_prompt(cfg, o, branch, handoffs),
            cwd=wt,
            add_dirs=[handoffs],
            allowed_tools=ALLOWED_TOOLS,
            timeout=timeout,
            log_path=log_dir / f"{stamp}-row8-implement.jsonl",
        )
        print("\n" + harness.summarise(d))
        return d

    if row == 9:
        branch = o.branches[0]["name"]
        wt, handoffs = ensure_worktree(cfg, branch)
        print(f"\n  dispatching implementer /create-pr in {wt}")
        d = harness.dispatch(
            create_pr_prompt(cfg, o, branch),
            cwd=wt,
            add_dirs=[handoffs],
            allowed_tools=ALLOWED_TOOLS + ["Bash(gh pr edit:*)", "Bash(gh pr diff:*)"],
            timeout=timeout,
            log_path=log_dir / f"{stamp}-row9-createpr.jsonl",
        )
        print("\n" + harness.summarise(d))
        return d

    print(f"  [not wired up in this spike] row {row} {state}")
    return None


# --------------------------------------------------------------------------- reporting

def report(o, cfg, row, state, why, action):
    print("=" * 78)
    print(f"OBSERVATION  {cfg['repo']}#{cfg['issue']}  at {o.at}")
    print("=" * 78)
    print(f"  issue      : {o.issue_state}  labels={o.issue_labels}")
    print(f"  branches   : {[b['name'] for b in o.branches] or '(none)'}")
    print(f"  ahead      : {o.commits_ahead}")
    if o.pr:
        print(
            f"  pr         : #{o.pr['number']} {o.pr['state']} draft={o.pr['isDraft']} "
            f"merged={o.pr['merged']} mergeable_state={o.pr['mergeable_state']}"
        )
        print(f"               head={o.pr['headRefOid'][:12]}  {o.pr['title']!r}")
    else:
        print(f"  pr         : (none)   open_pr_count={o.open_pr_count}")
    for r in o.reviews:
        print(
            f"  review     : {r['state']:<18} by {r['author_login']} (id={r['author_id']}) "
            f"@{(r['commit_id'] or '')[:12]} current={current(r, o)}"
        )
    print(f"  checks     : {o.checks or '(none at head)'}   required={cfg['required_checks']}")
    for e in o.draft_events:
        print(f"  latch      : {e['event']:<18} by {e['actor']} at {e['at']} (id={e['id']})")
    print(f"  ci_ok={o.ci_ok}  ever_reviewed={o.ever_reviewed}")
    print("-" * 78)
    print(f"STATE  row {row}: {state}")
    print(f"  because : {why}")
    print(f"  action  : {action}")
    print("=" * 78)


# --------------------------------------------------------------------------- entry point

def calibrate(cfg, timeout):
    """Cheapest possible real dispatch: does the stream look like #3 said it would?"""
    state_dir, wt, handoffs = paths(cfg)
    target = wt if wt.exists() else cfg["local_repo"]
    handoffs.mkdir(parents=True, exist_ok=True)
    log = state_dir / "streams"
    log.mkdir(parents=True, exist_ok=True)
    print(f"  calibration dispatch in {target}")
    d = harness.dispatch(
        "Run `git status --short` and `git rev-parse --abbrev-ref HEAD`, then reply with "
        "the branch name and nothing else. Do not change any files.",
        cwd=target,
        add_dirs=[handoffs],
        allowed_tools=ALLOWED_TOOLS,
        timeout=timeout,
        log_path=log / f"{time.strftime('%Y%m%d-%H%M%S')}-calibrate.jsonl",
    )
    print("\n" + harness.summarise(d))
    print(f"\n  result text: {d.result_text[:400]!r}")
    print(f"  /implement present in slash_commands: {'implement' in ' '.join(d.slash_commands)}")
    print(f"  slash_commands sample: {sorted(d.slash_commands)[:15]}")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--act", action="store_true", help="take the derived action")
    ap.add_argument("--calibrate", action="store_true", help="cheap dispatch, no ladder")
    ap.add_argument("--issue", type=int, help="override the configured issue")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--json", action="store_true", help="dump the raw observation too")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.issue:
        cfg["issue"] = args.issue

    if args.calibrate:
        calibrate(cfg, args.timeout)
        return

    o = observe(cfg)
    row, state, why, action = derive(o, cfg)
    report(o, cfg, row, state, why, action)
    if args.json:
        print(json.dumps(asdict(o), indent=2, default=str))

    if not args.act:
        print("\n(dry run -- nothing mutated. Re-run with --act to take the action.)")
        return
    act(row, state, o, cfg, args.timeout)


if __name__ == "__main__":
    main()
