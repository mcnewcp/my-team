# GitHub primitives for pipeline artifacts and Principal authority

Research date: 2026-08-30

## Question and evidence boundary

This note inventories the current GitHub-native primitives that could carry the planned
Contract, Audit report, review verdict, Ledger, pipeline State, and Principal authority. It does
not choose the v0.1 architecture. It records constraints that the downstream design tickets must
resolve.

Claims are separated as follows:

- **Documented** — guaranteed or described by current official GitHub documentation and REST API
  schemas (API version `2026-03-10` where shown).
- **Repo evidence** — behavior already measured in this repository's ADRs.
- **Inference** — a design consequence of documented or measured behavior, not a GitHub
  guarantee.
- **Prototype needed** — a precise fact for which current first-party sources are contradictory
  or incomplete.

## Decision-relevant summary

| Planned artifact or authority | Native primitive with the closest fit | Constraint the design must absorb |
| --- | --- | --- |
| Contract | General issue comment, addressed by numeric comment ID and permalink | A comment is mutable and deletable by its author or another write-capable actor. GitHub has no immutable-comment mode, so “frozen” must be a protocol invariant that detects replacement or mutation. |
| Audit report | Check run at the audited head SHA; commit status is the simpler fallback | A check run has structured conclusion, rich output, annotations, an external reference, and App attribution. A commit status is append-only and only carries state, context, short description, and URL. Current GitHub docs contradict each other about whether a fine-grained PAT may write check runs. |
| Reviewer verdict | Submitted pull-request review with explicit `commit_id` and `APPROVE` or `REQUEST_CHANGES` | Reviews are attributable and commit-pinned, but review bodies can be updated and review state can be dismissed. Creation has no documented idempotency key. The merge effect of a GitHub App's `REQUEST_CHANGES` in the planned two-Principal Reviewer/Judge shape needs measurement. |
| Ledger | One general issue comment on the pull request, updated by comment ID | Updating a known comment is a natural setter, but first creation can duplicate after an ambiguous retry. GitHub's new pin endpoint is documented for issue comments, not clearly for comments on pull requests. |
| Pipeline State | Current labels plus raw artifact facts and issue/PR timeline events | Labels are a set, not an exclusive state field. Current membership has no actor; attribution lives in timeline events. Paired remove/add transitions are not documented as atomic. |
| Principal | GitHub App bot identity using short-lived installation tokens; a PAT remains a user identity | One App is one attributed bot Principal even if its minted tokens are scoped differently. Endpoint permissions are granular, but `Contents: write` authorizes both Git push and PR merge. On personal-account repositories, branch restrictions cannot narrow base-branch updates to only the Integrator App. |

The strongest platform-backed shape available is therefore **raw artifact identity + explicit
head SHA + numeric actor/App identity + required-check source binding**. GitHub supplies useful
objects, attribution, and merge gates; it does not supply cross-object transactions or a generic
idempotency key.

## Contract and Ledger comments

### What GitHub represents

**Documented.** The issue-comment API manages general comments on both issues and pull requests.
Each comment has a numeric `id`, `node_id`, stable API and HTML URLs, body, author object including
numeric user ID, `created_at`, `updated_at`, `author_association`, and (in the current schema) a
`pin` value. Listing comments is ordered by ascending ID by default. A comment can be fetched or
updated directly by ID. Creating or updating a general comment needs `Issues: write` or
`Pull requests: write`; reading needs either permission at read level. See the
[issue-comment REST endpoints](https://docs.github.com/en/rest/issues/comments?apiVersion=2026-03-10).

**Documented.** Comments are not immutable. Anyone with repository write access can edit or
delete comments on issues and pull requests. The GraphQL `IssueComment` surface exposes
`editor`, `lastEditedAt`, `viewerCanUpdate`, and edit history; its update-reason enum says the
viewer must be the author or have write access. Anyone with read access can inspect a comment's
edit history, but the author or a write-capable actor can remove sensitive content from that
history, and only 100 edits are retained. See
[managing comments](https://docs.github.com/en/communities/moderating-comments-and-conversations/managing-disruptive-comments),
[the GraphQL Issues reference](https://docs.github.com/en/graphql/reference/issues), and
[tracking comment edits](https://docs.github.com/en/communities/moderating-comments-and-conversations/tracking-changes-in-a-comment).

**Documented.** GitHub added pinned issue comments in February 2026. The current REST API exposes
`PUT` and `DELETE /issues/comments/{comment_id}/pin`. A pinned comment response records
`pinned_at` and the numeric identity in `pinned_by`; the endpoint requires `Issues: write`.
Official prose and the endpoint both say “issues,” while the surrounding issue-comment API
otherwise explicitly says it manages issues *and pull requests*. See the
[pinned-comments announcement](https://github.blog/changelog/2026-02-05-pinned-comments-on-github-issues/)
and [pin/unpin endpoint schema](https://docs.github.com/en/rest/issues/comments?apiVersion=2026-03-10#pin-an-issue-comment).

### Consequences for the planned artifacts

**Inference.** A Contract comment can be permanently addressed by its returned comment ID and
permalink, but “frozen” cannot mean “GitHub prevents edits.” At minimum, the Contract design must
record or derive the expected author Principal, comment ID, creation identity, and a digest of the
canonical body, then reject a missing or changed object. Edit metadata is useful evidence, not an
unalterable audit log.

**Inference.** A Ledger can be updated deterministically once its comment ID is known. In a
stateless recovery path, a unique machine marker plus expected Principal and pull-request number
can rediscover it. The create endpoint has no documented client idempotency-key parameter, so a
crash after GitHub accepts creation but before the caller receives the ID can leave duplicates.
The Ledger design must specify duplicate detection and a canonical-winner rule rather than assume
exactly-once creation.

**Repo evidence.** [ADR 0005](../adr/0005-the-label-act-is-the-authorization.md) already treats
comments as editable by their author or a write-capable actor and therefore does not apply the
issue-body freshness rule to trusted comments. That observation remains useful, but the new
Contract and Ledger are machine-consumed artifacts, not narration: their integrity now needs an
explicit invariant.

**Prototype needed.** Current documentation does not establish whether the new pin endpoint
accepts a general issue comment whose subject is a pull request, which permission combination is
actually sufficient, or whether repeated pin/unpin requests are retry-safe. That fact determines
whether “single pinned PR comment” is a supported Ledger location or merely a UI aspiration.

## Audit report: check run versus commit status

### Check runs

**Documented.** A check run is created for a specific `head_sha` and returns a unique ID. It can
carry a stable name, `external_id`, `details_url`, lifecycle status, conclusion, timestamps,
Markdown title/summary/text, and structured line annotations. Its response identifies the
creating GitHub App. A known run can be updated by ID; annotations append across update calls.
GitHub retains checks for 400 days, archives them, then deletes them ten days later. GitHub also
limits same-name runs in a suite to 1,000 and deletes older runs beyond that limit. See the
[check-run endpoints](https://docs.github.com/en/rest/checks/runs?apiVersion=2026-03-10),
[Checks API guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks),
and [status-check retention](https://docs.github.com/en/pull-requests/reference/status-checks#retention-of-checks).

**Documented, but contradictory.** The Checks guide and the top of the check-run endpoint page
say write access is exclusive to GitHub Apps and direct non-App callers cannot create runs. On
the same endpoint page, the generated fine-grained-token section lists GitHub App user tokens,
installation tokens, *and fine-grained PATs* with `Checks: write`. The PAT documentation still
lists calling the Checks API as a fine-grained-PAT limitation. These first-party claims cannot all
describe the same current behavior. See the
[check-run endpoint permission text](https://docs.github.com/en/rest/checks/runs?apiVersion=2026-03-10#create-a-check-run)
and [fine-grained PAT limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations).

### Commit statuses

**Documented.** A commit status is created for a SHA and carries one of `error`, `failure`,
`pending`, or `success`, plus a case-insensitive context, short description, optional target URL,
and creator identity. It requires only `Commit statuses: write` and explicitly supports App
tokens and fine-grained PATs. Statuses are returned reverse chronologically; the combined status
uses the latest status for each context. Each creation appends a resource, and GitHub rejects more
than 1,000 statuses for one SHA/context. See the
[commit-status endpoints](https://docs.github.com/en/rest/commits/statuses?apiVersion=2026-03-10).

### Required-check and recovery semantics

**Documented.** Required status checks can be either checks or commit statuses. They must succeed
on the latest applicable SHA; depending on what CI reports, GitHub may require the pull request's
test-merge commit rather than its head commit. `success`, `skipped`, and `neutral` satisfy a
required check. If a check run and commit status share a required name, both must pass. A branch
rule can bind a required name to a specific GitHub App ID; without that binding, another
write-capable person or integration can set the same status name. See
[troubleshooting required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks),
[protected-branch required checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging),
and the [`checks[].app_id` branch-protection schema](https://docs.github.com/en/rest/branches/branch-protection?apiVersion=2026-03-10#update-branch-protection).

**Inference.** A check run is the only candidate here that can hold a useful GitHub-visible Audit
report rather than merely point to one. Its `external_id` can carry a deterministic pipeline
identity, but GitHub does not document it as unique. Check-run creation also has no documented
idempotency key. Recovery can list runs by ref/name/App and compare `external_id`, but the design
cannot assume that repeating create returns the original run.

**Inference.** A commit status is simpler to retry because the latest same-context value controls
the combined status, but each retry still appends an object and consumes the 1,000-status limit.
It cannot carry the planned machine-readable criterion-to-test traceability except indirectly via
`target_url`, so another GitHub artifact would remain necessary.

**Repo evidence.** [ADR 0002](../adr/0002-draft-flag-is-the-implementer-latch.md),
[ADR 0004](../adr/0004-two-fidelity-github-fakes.md), and
[ADR 0009](../adr/0009-github-is-the-sole-source-of-truth.md) measured that pull-request head SHA
can lag a push for several seconds while mergeability is unsettled. An Audit report must be
accepted only against a coherent current head, not merely because a same-name green object exists.

**Prototype needed.** The fixture repo should establish (a) whether a fine-grained PAT can
currently create and update a check run, (b) whether a repeated create with identical
name/head/external ID deduplicates or creates another run, and (c) which result GitHub treats as
required when same-App, same-name runs on one SHA have conflicting conclusions. These facts are
load-bearing for both auth selection and crash-safe Audit recovery.

## Native pull-request reviews

**Documented.** A submitted native review records a unique review ID, reviewer object with numeric
ID, body, `APPROVED`/`CHANGES_REQUESTED`/`COMMENTED` state, HTML URL, `submitted_at`,
`author_association`, and `commit_id`. `APPROVE` and `REQUEST_CHANGES` are explicit create/submit
events; omitting the event creates a pending review. Creating or submitting requires
`Pull requests: write`. Specifying `commit_id` avoids silently defaulting the review to whichever
head GitHub considers current at request time. See the
[pull-request-review endpoints](https://docs.github.com/en/rest/pulls/reviews?apiVersion=2026-03-10).

**Documented.** Submitted reviews cannot be deleted, but their summary body can be updated and an
authorized actor can dismiss a review, changing its state to `DISMISSED`. Pull-request authors
cannot approve their own pull requests. When protected-branch review requirements apply, a
write-capable reviewer's request for changes can block merge until that reviewer approves or the
review is dismissed; stale-approval dismissal and last-push approval are configurable and distinct
rules. See [approving with required reviews](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews),
[dismissing a review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/dismissing-a-pull-request-review),
and [ruleset review behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-a-pull-request-before-merging).

**Inference.** A review is a strong verdict envelope, not an immutable findings store. The Ledger
must retain stable finding identity and dispositions even if the review body is edited or its
platform state later becomes `DISMISSED`. Creation has no documented client idempotency key, so a
retry can create a second submitted review; recovery needs a deterministic round identity and a
rule for multiple reviews from the same Principal.

**Repo evidence.** [ADR 0002](../adr/0002-draft-flag-is-the-implementer-latch.md) and
[ADR 0010](../adr/0010-verify-by-observation.md) measured that `reviewDecision` can be `null` while
an `APPROVED` review is present, REST and GraphQL disagree about the `[bot]` login suffix, reviews
accumulate, and the platform's stale state can disagree with the reviewed head. They therefore
read raw reviews by numeric Principal ID and compare each review's pinned SHA to the coherent PR
head. Those empirical rules remain applicable to the new Reviewer verdict.

**Prototype needed.** Official docs describe human repository roles and generic App endpoint
permissions but do not establish the complete merge effect of a distinct Reviewer App's
`REQUEST_CHANGES`. A fixture must test whether it blocks under the intended v0.1 protection
settings, whether a Judge App can dismiss it with the proposed least privilege, and what raw
review/merge fields remain after dismissal or a later push. Without that fact, the planned
Reviewer → Judge → Integrator path may retain a platform blocker after the Judge disposes every
finding.

## Labels and pipeline State

**Documented.** GitHub's Issues label endpoints are shared by issues and pull requests. They can
list current labels, add to the existing set, replace the entire set, remove one, or remove all.
Read/write accepts either the relevant `Issues` or `Pull requests` permission. `Set labels`
explicitly removes previous labels; labels themselves can be renamed or deleted by write-capable
actors. See the [label endpoints](https://docs.github.com/en/rest/issues/labels?apiVersion=2026-03-10)
and [label permissions](https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/managing-labels).

**Documented.** A current label list contains label identity and presentation, not who applied
it. The issue/timeline event APIs expose `labeled` and `unlabeled` events for both issues and pull
requests. Each event has a unique event ID, actor object, timestamp, and label. See
[issue event types](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types#labeled)
and [issue-event endpoints](https://docs.github.com/en/rest/issues/events?apiVersion=2026-03-10).

**Inference.** Labels can make State phone-visible and crash-resumable, but they do not form a
single-valued state register. GitHub documents no compare-and-swap or transaction spanning remove
and add. A crash or concurrent actor can therefore leave zero or multiple `agent:*` labels. The
State design must define authoritative corroborating artifacts, precedence, transition ownership,
and deterministic repair. Using `Set labels` as an atomic-looking replacement would clobber
unrelated human labels.

**Repo evidence.** [ADR 0003](../adr/0003-escalation-swaps-the-labels.md) already derives reset
counters from `labeled` timeline events, and [ADR 0002](../adr/0002-draft-flag-is-the-implementer-latch.md)
measured timeline timestamps colliding at second resolution. Event ordering should therefore use
the unique/monotonic event identity rather than timestamps alone.

## Principal identity, credentials, and least privilege

### Attribution and token lifetime

**Documented.** Installation-token API calls are attributed to the GitHub App. An App installation
token expires after one hour and can be minted for a subset of the installation's repositories
and permissions, never more than the installation has. HTTP Git with an installation token needs
`Contents` permission. One App's installation token identifies the App's built-in bot account,
for example `app-slug[bot]`. See
[installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)
and [App versus user identification](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps#token-based-identification).

**Documented.** PAT actions are actions by the issuing user and cannot exceed that user's access.
Fine-grained PATs can be limited to one resource owner, selected repositories, exact permissions,
and an expiration (including infinite unless policy forbids it); organization approval may be
required. They remain tied to the user's lifecycle and currently have listed feature gaps.
Classic PATs are broader, and GitHub recommends fine-grained PATs or a GitHub App for long-lived
automation. See [managing PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
and [when to use a GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app#choosing-between-a-github-app-or-a-personal-access-token).

**Inference.** Per-token permission reduction does not create a new Principal: all installation
tokens minted from one App remain attributed to that App bot. Distinct GitHub attribution between
Implementer, Reviewer, Judge, and Integrator therefore requires distinct Apps (or distinct user
accounts), not merely four tokens from one App. Multiple Roles may intentionally share a Principal,
but GitHub cannot recover which Role used a shared credential.

**Repo evidence.** [ADR 0005](../adr/0005-the-label-act-is-the-authorization.md) measured an
installed App review reporting `author_association: NONE` despite write permissions. App
Principals must be recognized by configured numeric bot/App identity, not `author_association` or
login spelling. That evidence supports the new separation between Role responsibility and
Principal credential.

### Endpoint permission floor

The current documented minimum repository permission for each planned write is:

| Write | Minimum permission |
| --- | --- |
| Create/update Contract issue comment; create follow-up issue | `Issues: write` |
| Create/update general PR Ledger comment | `Pull requests: write` **or** `Issues: write` |
| Pin an issue comment | `Issues: write` |
| Add/remove issue or PR labels | `Issues: write` **or** `Pull requests: write` |
| Submit or dismiss a native review | `Pull requests: write` (dismissal policy may additionally restrict the actor) |
| Create a commit status | `Commit statuses: write` |
| Create/update a check run | `Checks: write`, with the token-type contradiction above |
| Push through HTTP Git | `Contents: write` |
| Merge a pull request | `Contents: write` |
| Configure branch protection or its actor/check restrictions | `Administration: write` (setup-time authority, not a run-time Role permission) |

Endpoint permissions come from the linked REST references above and the
[merge endpoint](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2026-03-10#merge-a-pull-request).

### The Integrator-only merge constraint

**Documented.** `PUT /pulls/{number}/merge` needs `Contents: write`; its optional `sha` rejects a
moved head with `409`. GitHub CLI exposes the same precondition as `--match-head-commit`. Branch
protection can require pull requests, reviews, checks, and can restrict who may push or merge to a
matching branch. However, actor restrictions are available only on organization-owned
repositories. Allowed actors can include installed Apps, and allowed actors still must satisfy
required checks and pull-request rules. See the
[merge endpoint](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2026-03-10#merge-a-pull-request),
[`gh pr merge`](https://cli.github.com/manual/gh_pr_merge), and
[protected-branch actor restrictions](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#restrict-who-can-push-to-matching-branches).

**Inference.** App permission scopes alone cannot enforce “only the Integrator may merge” while an
Implementer App also needs `Contents: write` to push its feature branch. Both tokens meet the
merge endpoint's permission floor. An organization-owned target repo can additionally restrict
base-branch updates to the Integrator App; a personal-account target repo cannot use that branch
restriction. The credentials design must therefore choose an enforceable topology or explicitly
change one of its premises—it cannot derive merge-only authority from `Contents: write`.

**Repo evidence.** [ADR 0010](../adr/0010-verify-by-observation.md) measured that GitHub refuses
self-approval, draft PR merges, and merges whose matched head moved. Those platform gates remain
valuable, but none distinguishes two different `Contents: write` Principals on a personal repo.

## Idempotency and crash recovery inventory

GitHub documents object IDs, setters, histories, and conditional merge; it does not expose a
generic idempotency key on the mutation schemas reviewed here.

| Mutation | Documented behavior | Recovery implication (inference) |
| --- | --- | --- |
| Create Contract/Ledger comment | Creates and returns a new comment ID | Search by deterministic marker and Principal before create; detect and reconcile duplicates after ambiguous failures. |
| Update comment | Replaces body at known comment ID | Repeating the same body is a natural idempotent setter, but integrity still requires re-read and author/editor checks. |
| Pin/unpin comment | `PUT` pin / `DELETE` unpin | HTTP method choice suggests target-state semantics, but repeated-call status and PR support need the pin prototype. |
| Create check run | Creates and returns a new run ID | Rediscover by head/name/App/external ID; duplicate resolution needs the check prototype. |
| Update check run | Updates known run ID; annotations append | Repeating the scalar output can converge, but repeating annotations does not. |
| Create commit status | Appends status; latest status per context controls combined state | Same-value retry converges semantically while consuming history and the 1,000-entry limit. |
| Submit review | Creates/submits an attributable review | Derive round identity and canonical review from raw list; do not assume exactly once. |
| Add/remove labels | Mutates a set; replace operation overwrites all labels | Re-read and repair zero/multiple state labels; never use replace-all without preserving unrelated labels. |
| Merge with expected `sha` | `200` on success; `409` if head differs | Observe `merged` first and always supply the audited head SHA, closing the check-to-merge race. |

## Reconciliation with existing ADRs

This research does not decide which old ADRs survive the rewritten v0.1, but it exposes where the
new binding skeleton cannot coexist with them unchanged.

- **Compatible empirical foundation:** [ADR 0001](../adr/0001-isolated-worktree-and-handoffs-outside-git.md),
  [ADR 0004](../adr/0004-two-fidelity-github-fakes.md), and most of
  [ADR 0009](../adr/0009-github-is-the-sole-source-of-truth.md) establish that GitHub—not local
  workspace state—is observed, and that real fixture captures must bind fakes to the platform.
  The three prototype questions below follow that precedent.
- **Direct State conflict:** ADR 0009 explicitly rejects labels written by the orchestrator as
  “a state file wearing a GitHub costume,” while the new binding skeleton requires label-backed,
  operator-visible pipeline State. [How GitHub should represent and recover pipeline State](https://github.com/mcnewcp/my-team/issues/91)
  must supersede that paragraph or make labels a non-authoritative projection corroborated by raw
  artifacts. Leaving both claims in force is not coherent.
- **Reusable review evidence, changed ownership:** ADR 0002's raw-review, numeric-Principal,
  explicit-head, and unsettled-observation rules remain supported. Its Judge-owned formal verdict
  and draft-latch round model are not automatically compatible with the new separate Reviewer
  verdict and Judge Ledger disposition.
- **Authorization evidence survives vocabulary change:** ADR 0005's measured App attribution and
  trusted-human boundary remain relevant. Its statement that a Role *is* a credential is
  superseded by the map's Role/Principal split and will need textual reconciliation.
- **Direct declaration conflict:** [ADR 0010](../adr/0010-verify-by-observation.md) says there are
  exactly two declarations and that no prose is parsed into State. The new Contract and Ledger
  are structured, machine-consumed GitHub prose, and the Reviewer—not Judge—owns the native review
  verdict. The verify-by-observation principle survives; the exact declaration count and artifact
  ownership do not survive unchanged.
- **Label-history evidence survives:** ADR 0003's label-swap and timeline-derived reset behavior
  remains evidence for attribution and recovery, not a ready-made taxonomy for the larger state
  machine.

## Focused prototypes now made precise

1. **Audit check-run retry and token semantics:** test fine-grained PAT write access, duplicate
   creation with one head/name/external ID, and required-check selection among conflicting duplicate
   runs from one App.
2. **Pinned Ledger comments on pull requests:** test whether a PR conversation comment can be
   pinned through the issue-comment endpoint, the exact App permission needed, returned pin actor
   metadata, and repeated pin/unpin behavior.
3. **Distinct-App review blocking:** test the merge effect of a Reviewer App's
   `REQUEST_CHANGES`, the least permission with which a Judge App can clear it, and raw review/head
   state after dismissal and a later push.

No other architectural choice in the research question requires an experiment before the current
design tickets can proceed. Labels' non-atomic multi-call transition is already a design constraint;
Integrator-only merge on personal repositories is already ruled out by the documented permission
and branch-restriction model rather than waiting on measurement.
