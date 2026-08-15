# Per-role GitHub identities

Research resolving issue #5: *How hard is it to give each agent role its own GitHub
identity, and is it cheap enough to adopt for v0.1?*

Researched 2026-08-15. All claims cited to primary sources inline. Claims that could not be
tied to a primary source are marked **UNVERIFIED** — inference is never presented as fact.

---

## Verdict

**Adopt per-role identities in v0.1, implemented as one GitHub App per role.**

The honest cost is higher than it first looks. Registering one App is **~28 realistic
click-through actions** end to end (38 literal steps across GitHub's three doc pages,
de-duplicated for navigation you don't repeat; ~17 if you disable webhooks and skip every
optional field). Call it **6–8 minutes per role once you've done one**, and **~30–45 minutes
total for three or four roles**, in a single sitting, never repeated.

That is not "trivially cheap." It is still worth doing, and the reason is not the setup
number — it is these three:

1. **Ongoing cost is genuinely zero.** *"Private keys do not expire and instead need to be
   manually revoked"*
   ([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)),
   and installation tokens are minted per use and *"will expire after 1 hour"*
   ([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)).
   No email address, no 2FA enrolment, no account, no rotation calendar, no seat.
2. **The machine-user alternative costs more up front *and* breaks the Terms of Service at
   N≥2.** The ToS caps you at one: *"You may maintain no more than one free machine account in
   addition to your free Personal Account"*
   ([ToS §B.3](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)).
   Three-to-five roles means paying for GitHub Pro seats on the extras — plus N email
   addresses, N 2FA enrolments, and permanent PAT rotation. Its setup is ~45–60 min and its
   ongoing cost never reaches zero.
3. **GitHub Apps can submit formal approving reviews.** The "bots can't approve" rule everyone
   remembers is a repository setting scoped to the built-in Actions `GITHUB_TOKEN`, not a
   property of app identities, and `my-team` runs locally with its own apps' tokens. See
   [The approval question](#the-approval-question).

**Re-argued against the true number:** the fallback (comment-prefix `**Randy** — reviewer`
under one account, approval faked with a label) costs zero minutes but permanently forfeits
real `APPROVE` / `REQUEST_CHANGES` reviews and makes every artifact in the loop read as
`mcnewcp`. Trading one ~30–45 minute sitting, once, for the actual thing the ticket wants is a
good trade. The decision rule trips toward **adopt**.

**Mitigation that makes it cheaper still:** you do not have to register all N at once. Start
with the roles that must be visibly distinct — implementer, reviewer, judge — for ~20–25
minutes, and add roles later. Apps are independent, so N grows without rework, and the cap is
generous: *"A user or organization can register up to 100 GitHub Apps."*

**One caveat that shapes the design, not the verdict:** whether a *custom* app's approving
review satisfies a branch-protection *required-approvals* count is **UNVERIFIED**. It does not
matter for v0.1 — the target repo's `main` is unprotected (verified below), so `my-team` is
the gate.

---

## Cost evidence

### Path A — one GitHub App per role (recommended)

The flow spans three doc pages. Literal rendered step counts:

| Phase | Source | Steps as rendered |
|---|---|---|
| Register the App | [registering-a-github-app](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) | **22** |
| Generate a private key | [managing-private-keys](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps) | **7** |
| Install on one repo | [installing-your-own-github-app](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app) | **9** |
| | **Literal total** | **38** |

Those 38 overstate it: phases 2 and 3 begin by repeating the same five navigation steps you
are already past, because **Create GitHub App** lands you on the App's settings page which
already holds both *Generate a private key* and *Install App*.

| | |
|---|---|
| Literal doc steps | 38 |
| **Realistic de-duplicated actions** | **~28** (22 + 2 + 4) |
| Absolute minimum, webhooks off, all optional fields skipped | **~17** |
| Mandatory subset of the 22 registration steps | **11** (the other 11 are marked "Optionally" or are conditional on webhooks being Active) |
| Time per role | ~6–8 min once practised; the first is slower (~15 min) while you read the form |
| **Total for N=4** | **~30–45 min, once** |
| Email addresses needed | **0** — the registration form has no email field |
| 2FA enrolments needed | **0** |
| **Ongoing cost** | **~0** — keys never expire; tokens self-expire hourly |

The registration path in order: profile picture → Settings → Developer settings → GitHub Apps
→ New GitHub App → name (≤34 chars) → **Homepage URL (required)** → **deselect Active to
disable webhooks** → **Permissions** → **install scope: Only on this account** → Create GitHub
App.

Notes that materially reduce the count:

- **Webhooks can be turned off**, which removes four conditional fields: *"Optionally, if you
  do not want your app to receive webhook events, deselect **Active**."* `my-team` polls; it
  does not receive. Turn them off.
- **Homepage URL is required** but has an escape hatch: *"If you don't have a dedicated URL and
  your app's code is stored in a public repository, you can use that repository URL."*
- **No seat is consumed**: *"GitHub Apps are not tied to a user account and do not consume a
  seat"*
  ([deciding when to build a GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app)).

**Private keys.** One click under "Private keys" → *Generate a private key*; no CSR, no
external tooling, no approval. The download is PEM — *"If you're using a library that requires
a specific file format, the PEM file you download will be in `PKCS#1 RSAPrivateKey` format."*
They **never expire** (*"Private keys do not expire and instead need to be manually
revoked"*), and rotation is supported without downtime: *"You can create up to 25 private keys
for an app. You should use multiple keys in order to rotate keys without downtime in the event
of a key compromise."* GitHub keeps only the public half; the PEM downloads exactly once.

**Install-scope caveat, quoted:** choosing "Only select repositories" does **not** fully
constrain the App — *"the app will always have at least read-only access to all public
repositories on GitHub."* Worth knowing, though it is a read-only floor and the target repo is
public anyway.

**Orchestrator-side code.** Sign a short-lived RS256 JWT with the role's private key, `POST
/app/installations/{id}/access_tokens`, use the result as `GH_TOKEN`. Installation ID is looked
up once via `GET /repos/{owner}/{repo}/installation`. Perhaps 30 lines of Python (`PyJWT` plus
one HTTP call). This is the only real code cost of Path A, and it is written once for all
roles.

**Is registering an App free?** No price is stated on the registering, private-keys, or
installing pages — but the docs never say "free" either. **UNVERIFIED** as a quotable
statement, though no payment step exists anywhere in the flow.

### Path B — one machine user per role (not recommended)

Per role, one-time:

1. Create a new email address / alias that GitHub will accept
2. Sign up, verify email, clear the signup challenge
3. Enrol 2FA (TOTP), store the secret and the recovery codes durably
4. Create a PAT scoped to the target repo
5. Store the PAT
6. From `mcnewcp`, invite the account as a collaborator with **write** access
7. Log in *as the machine account* to accept the invitation
8. Log back out

| | |
|---|---|
| Steps per role | ~8, but each is heavy (email round-trip, 2FA device, session juggling) |
| Time per role | ~10–15 min |
| **Total for N=4** | **~45–60 min, once** |
| Email addresses needed | **N** |
| 2FA enrolments needed | **N** |
| Money | GitHub Pro for every machine account past the first, to stay ToS-compliant |
| **Ongoing cost** | PAT expiry rotation, N TOTP secrets and recovery-code sets to keep alive forever, N accounts that can be locked out |

2FA is not optional. *"Unattended or shared access accounts in your organization, such as bots
and service accounts, that are selected for mandatory two-factor authentication, must enroll in
2FA"*
([docs](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-two-factor-authentication-for-your-organization/managing-bots-and-service-accounts-with-two-factor-authentication)).
Tokens keep working once 2FA is on — *"Enabling 2FA will not revoke or change the behavior of
tokens issued for the service account"* — but enrolment and secret custody are permanent work
per account. (The exact maximum expiry allowed for a fine-grained PAT is **UNVERIFIED** — the
source could not be retrieved — but PATs expire and Apps' private keys do not, which is the
comparison that matters.)

**Setup time is comparable; everything else is not.** Path B is ~1.5× the setup, needs N email
addresses and N 2FA devices, never reaches zero ongoing cost, and is **non-compliant with the
ToS at N≥2** without paying. That, not the click count, is what decides it.

---

## The approval question

The ticket asks this precisely, so here is the chain, link by link.

### (a) Can a GitHub App installation token submit a review with `event: APPROVE`?

**Yes on the balance of documented evidence — but the direct sentence does not exist, so the
inference is flagged.**

- The endpoint `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` documents `APPROVE`,
  `REQUEST_CHANGES` and `COMMENT` as submittable `event` values, with no app-specific carve-out
  anywhere on the page
  ([REST: pull request reviews](https://docs.github.com/en/rest/pulls/reviews?apiVersion=2022-11-28)).
- The only documented actor restriction is on the **author**: *"Pull request authors cannot
  approve their own pull requests"*
  ([docs](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews)).
  It is an identity check against the PR author, not a human-versus-bot check.
- App installation activity is attributed to the app as a **distinct actor**: *"API requests
  made by an app installation are attributed to the app"*
  ([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)).
- The famous "bots can't approve" behaviour is a **setting scoped to `GITHUB_TOKEN`**. GitHub's
  own words: the *"Allow GitHub Actions to create and approve pull requests"* setting determines
  *"whether `GITHUB_TOKEN` can create and approve pull requests"*, and *"By default, when you
  create a new repository in your personal account, workflows are not allowed to create or
  approve pull requests"*
  ([docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)).
  A per-repo toggle over the built-in Actions token — and it can be turned on.

`my-team` runs **locally**, not in Actions. It authenticates with its own apps' installation
tokens, which are not `GITHUB_TOKEN` and are not governed by that setting.

GitHub documents the capability by documenting the switch that removes it from Actions. No
primary source says "a GitHub App may submit an approving review" outright — **UNVERIFIED** as
a direct statement, strong as an inference, and cheap to settle empirically (see step 6 of the
recommended shape).

### (b) Does "cannot approve your own PR" apply between an App and its owner, or between two Apps?

The restriction is written against the PR **author**. Because installation activity is
attributed to the app as its own actor rather than to the human who owns it, the cases fall out
as:

| PR opened by | Review submitted by | Same actor? | Expected |
|---|---|---|---|
| implementer App | reviewer App | no | allowed |
| `mcnewcp` | reviewer App | no | allowed |
| reviewer App | reviewer App | **yes** | blocked |

**The docs are silent on the app-vs-app and app-vs-owner cases specifically — UNVERIFIED.**
GitHub nowhere states that an app inherits its owner's identity for self-approval purposes, and
the attribution documentation says the opposite. The design consequence is simply: **never let
one role both open a PR and approve it.** That is already `my-team`'s shape — the implementer
opens, the reviewer and judge review.

### (c) Private personal repositories, and branch protection

**The premise needs correcting.** The v0.1 target repo is **public**, not private (verified on
this machine — see below). That removes the awkward part of the question.

- Protected branches are a **paid** feature for private repos on a personal account. GitHub's
  plans page lists "Protected branches" under **Pro**, in the group *"Advanced tools and
  insights in private repositories"*
  ([GitHub's plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans)).
  A private repo on GitHub Free therefore **cannot** enforce required reviews at all — on that
  path, approval is decorative no matter which identity submits it.
- Rulesets are narrower still: *"A ruleset is a named list of rules that applies to a repository
  or to multiple repositories in an organization for customers on GitHub Team and GitHub
  Enterprise plans"*
  ([about rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)).
- Because the target repo is **public**, classic branch protection *is* available on Free, so
  required approvals can be enforced there if wanted.

Do app reviews satisfy a required-approvals count? GitHub documents this **only for Actions**: a
policy setting named *"Allow GitHub Actions reviews to count towards required approval"* exists
and is *"enabled by default"*
([changelog, 2022-01-14](https://github.blog/changelog/2022-01-14-github-actions-prevent-github-actions-from-approving-pull-requests/)).
Its existence proves bot-identity reviews *can* count. Whether a **custom** app's review counts
is **UNVERIFIED** — no primary source states it either way. Note the contrasting precedent that
Copilot's reviews explicitly do *not* count, so GitHub does treat some bot reviewers as
non-counting.

Moot for v0.1: `main` on the target repo is unprotected, so `my-team` gates merges itself.

---

## Machine accounts and the Terms of Service

Quoted in full from **§B.3 Account Requirements**
([GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)):

> * You must be a human to create an Account. Accounts registered by "bots" or other automated
>   methods are not permitted. We do permit machine accounts:
> * A machine account is an Account set up by an individual human who accepts the Terms on
>   behalf of the Account, provides a valid email address, and is responsible for its actions.
>   A machine account is used exclusively for performing automated tasks. Multiple users may
>   direct the actions of a machine account, but the owner of the Account is ultimately
>   responsible for the machine's actions. **You may maintain no more than one free machine
>   account in addition to your free Personal Account.**
> * One person or legal entity may maintain no more than one free Account (if you choose to
>   control a machine account as well, that's fine, but it can only be used for running a
>   machine).

Reading it straight:

- Machine accounts are **explicitly permitted** for personal automation. The widely repeated
  folklore that "bot accounts violate GitHub's ToS" is wrong — the ToS carves them out by name.
- But the allowance is **singular and free-tier-capped**: *one* free machine account. N=3–5
  roles as machine accounts exceeds it; staying compliant means paying for the extras.
- Each must be *"set up by an individual human who accepts the Terms on behalf of the Account"*
  and *"provides a valid email address"* — N distinct working email addresses, accepted by hand.
  Whether GitHub accepts `+`-addressing aliases (`mcnewcp+randy@gmail.com`) for distinct
  accounts is **UNVERIFIED** as policy.

Nothing in the [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)
prohibits this kind of personal automation. The nearest clauses target *"excessive automated
bulk activity, to place undue burden on our servers through automated means"* and *"inauthentic
interactions, such as fake accounts and automated inauthentic activity"* (§4, Spam and
Inauthentic Activity). A single-developer loop driving one issue at a time on their own repo is
neither. GitHub Apps sidestep the question entirely — an app is not an account.

---

## Credential handling

The requirement: `my-team` runs **from the target repo root**, so nothing secret may land inside
the target repo or be visible to a harness that has the target repo checked out.

**`GH_TOKEN` is the whole mechanism.** The gh CLI documents it as *"an authentication token that
will be used when a command targets either `github.com` or a subdomain of `ghe.com`. Setting
this avoids being prompted to authenticate and **takes precedence over previously stored
credentials**"* ([gh environment](https://cli.github.com/manual/gh_help_environment)).

That gives a clean design:

- Per-role private keys live **outside the target repo**, at `~/.config/my-team/keys/<role>.pem`,
  mode `0600`. Never a path inside the target repo, so there is nothing to `.gitignore` and
  nothing for an agent to accidentally stage.
- For each action, the orchestrator mints a fresh installation token for that role and passes it
  **in the subprocess environment only** — `GH_TOKEN=<token> gh pr review ...`. Never written to
  disk, never in a config file.
- Because installation tokens expire in **1 hour**, even a leaked token is time-boxed. That is a
  genuine security improvement over a machine user's PAT, which is long-lived by construction.
- `GH_TOKEN` precedence means **no shared mutable auth state**. `my-team` must *not* use
  `gh auth switch`, which mutates a global config and would race between concurrent roles.
  Per-process env vars have no such problem.
- `mcnewcp`'s own `gh` login is untouched — it stays in the macOS keychain (*"an authentication
  token will be stored securely in the system credential store"*,
  [gh auth login](https://cli.github.com/manual/gh_auth_login)) and is simply not consulted when
  `GH_TOKEN` is set.
- Key compromise has a clean remedy: up to 25 private keys per app means a role's key can be
  rotated and the old one revoked without downtime.

**`gh` has no native GitHub App support.** The orchestrator must mint installation tokens itself
(JWT → `POST /app/installations/{id}/access_tokens`) and inject them; `gh auth login` cannot do
it. Confirmed by the maintainers in
[cli/cli discussion #5095](https://github.com/cli/cli/discussions/5095).

For git access specifically, the same token works as an HTTP password: *"You can also use an
installation access token to authenticate for HTTP-based Git access. Your app must have the
'Contents' repository permission. You can then use the installation access token as the HTTP
password"*, via
`git clone https://x-access-token:TOKEN@github.com/owner/repo.git`
([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)).

---

## Attribution: do commits also need per-role identity?

**Comments and reviews need attribution; commits do not — but the mechanism has a sharp edge
worth designing around.**

### The sharp edge: identical credential, opposite outcomes

The *same* installation token produces completely different commit attribution depending on how
you commit:

| How the commit is made | Attributed to | Verified badge |
|---|---|---|
| **REST API, author/committer omitted** | the **App** | **Yes** |
| **REST API, explicit `author` or `committer` supplied** | whatever you supplied | **No — forfeited** |
| **`git push` over HTTPS with the token** | whatever **local git config** says | **No** — unsigned |

Sources:

- Defaults on the commit-writing endpoints resolve to the authenticated identity — which for an
  installation token is the App. *Create or update file contents*: `committer` is *"The person
  that committed the file. **Default: the authenticated user.**"* and `author` is *"**Default:
  The committer or the authenticated user if you omit committer.**"*
  ([REST: contents](https://docs.github.com/en/rest/repos/contents)). *Create a commit*: *"**By
  default, the author will be the authenticated user and the current date**"* and *"**By
  default, committer will use the information set in author.**"*
  ([REST: git commits](https://docs.github.com/en/rest/git/commits)). Note both sub-fields become
  hard-required if the object *is* supplied — a 422 if `name` or `email` is omitted.
- Bots can be signed and marked Verified: *"Organizations and GitHub Apps that require commit
  signing can use bots to sign commits. If a commit or tag has a bot signature that is
  cryptographically verifiable, GitHub marks the commit or tag as verified."* **But** —
  *"Signature verification for bots will only work if the request is verified and authenticated
  as the GitHub App or bot and **contains no custom author information, custom committer
  information, and no custom signature information, such as Commits API**"*
  ([about commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)).
- For `git push`, attribution is by **email match, not by credential**: *"GitHub links a commit
  to a user by matching the email address in the commit header to an email address on a GitHub
  account"*
  ([troubleshooting commits](https://docs.github.com/en/pull-requests/how-tos/commit-changes/troubleshooting-commits)),
  and *"GitHub uses the email address set in your local Git configuration to associate commits
  pushed from the command line with your account on GitHub"*
  ([setting your commit email address](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)).
  No single sentence states this for the installation-token push case specifically —
  **UNVERIFIED** as a direct statement, established indirectly by the two above. That
  git-pushed commits are unsigned under an installation token is likewise **inference,
  UNVERIFIED**.

### Recommendation

**Keep `git push` for v0.1 and do not chase per-role commit identity.** Reasoning:

- The ticket's goal is that artifacts read properly — *"Randy requested changes"*, *"Percy
  approved"*. Those are review and comment events; App identity delivers them exactly.
- Only one role — the implementer — writes commits. Every commit on a branch came from the
  implementer, so per-role commit attribution encodes what the PR already implies.
- Chasing App-attributed Verified commits would mean routing every write through the REST
  contents/git endpoints instead of `git push` — a much heavier implementation for a harness
  that naturally works on a checkout, and it forfeits the badge the moment you want to set an
  author anyway.
- Under `git push`, set local `user.name` / `user.email` deliberately (e.g. `mcnewcp`) so
  commits attribute cleanly, rather than leaving it to whatever the harness inherits.
- If per-commit role attribution is ever wanted, the cheap route is a `Co-authored-by:` trailer,
  documented as first-class: syntax `Co-authored-by: name <name@example.com>`, *"Add one
  `Co-authored-by:` trailer for each co-author"*, after an empty line following the description,
  and *"For the commit to count as a contribution, use an email address associated with their
  account on GitHub.com"*
  ([creating a commit with multiple authors](https://docs.github.com/en/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/creating-a-commit-with-multiple-authors)).
  Defer it.

This repo's own convention — conventional commits over squash merge — means the PR title and
body become the commit that lands on `main`. The PR is already the unit of attribution, which
reinforces leaving commits alone.

---

## Rate limits

Not a constraint at `my-team`'s volume, and per-role apps *help*.

- A GitHub App installation on a personal-account repo gets *"the installation's minimum rate
  limit of 5,000 requests per hour"*
  ([rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28)).
- That limit is **per installation**, so N apps means N × 5,000/hr rather than sharing
  `mcnewcp`'s single 5,000/hr personal budget. Splitting roles across apps increases headroom.
- The real ceiling is the **secondary** limit on content creation: *"no more than 80
  content-generating requests per minute and no more than 500 content-generating requests per
  hour."* The reviews endpoint carries an explicit warning: *"This endpoint triggers
  notifications. Creating content too quickly using this endpoint may result in secondary rate
  limiting."* A tick posting a handful of comments is far below this, but a bulk line-comment
  review should batch its comments into a single review submission rather than posting them one
  at a time.

---

## Verified state of this machine

Checked read-only on 2026-08-15; nothing was created or modified.

- `gh` version **2.97.0**.
- `gh auth status`: logged in to github.com as **`mcnewcp`**, token in the **keyring**, active
  account. Scopes: `gist`, `project`, `read:org`, `repo`, `workflow`.
- Target repo `mcnewcp/personal-assistant` is **public**, owner type `User`, default branch
  `main`, and `mcnewcp` holds admin.
- `GET /repos/mcnewcp/personal-assistant/branches/main/protection` returns **404 "Branch not
  protected"** — no branch protection on `main` today.

The last point is why the required-approvals uncertainty does not block v0.1.

---

## Recommended shape for v0.1

1. Register one GitHub App per role under `mcnewcp`. Start with implementer, reviewer, judge
   (~20–25 min for three); add roles later — the cap is 100 apps per account.
2. During registration: **deselect Active** to disable webhooks (removes four fields), use the
   repo URL as the required Homepage URL, and choose "Only on this account".
3. Permissions: Contents R/W, Issues R/W, Pull requests R/W for the implementer. Reviewer and
   judge need only Contents **read** plus Issues and Pull requests R/W.
4. Generate a private key per app; store at `~/.config/my-team/keys/<role>.pem`, mode `0600`,
   outside the target repo. The PEM downloads once — back it up before moving on.
5. Mint an installation token per action; pass it as `GH_TOKEN` in the subprocess env. Never use
   `gh auth switch`.
6. Enforce in the orchestrator that the role which opened a PR is never the role that approves
   it.
7. Commit via `git push` with the installation token as HTTP password and a deliberate local
   `user.email`. Do not route commits through the REST API for v0.1.
8. **Smoke-test before committing the design**: register one app, open a throwaway PR as
   `mcnewcp`, and confirm `GH_TOKEN=<installation-token> gh pr review --approve` succeeds. That
   one test converts the biggest **UNVERIFIED** items below into settled fact for ~10 minutes of
   work.

---

## Open questions marked UNVERIFIED

1. ~~No primary source directly states "a GitHub App may submit an approving review."~~
   **Settled empirically 2026-08-15 — see "Settled by smoke test" below.**
2. ~~The self-approval restriction's behaviour for app-vs-app and app-vs-owner is not
   documented.~~ **Settled empirically 2026-08-15 — see below.**
3. Whether a **custom** app's approving review counts toward branch-protection required
   approvals (only the Actions case is documented).
4. Whether registering a GitHub App is free — no price statement exists either way, though no
   payment step appears in the flow.
5. That a GitHub App has no 2FA of its own — true by construction (no 2FA step exists in the
   flow; it authenticates by private-key-signed JWT), but not stated in a quotable sentence.
6. ~~The literal `app-slug[bot]` login-suffix convention.~~ **Observed 2026-08-15**: a review
   submitted by app slug `my-team-reviewer-mcnewcp` is attributed to login
   `my-team-reviewer-mcnewcp[bot]`, `user.type: "Bot"`, `user.id: 317436782`. Still convention
   rather than a documented guarantee, but no longer merely assumed.
7. The bot noreply email pattern `<ID>+<app-slug>[bot]@users.noreply.github.com`. Only the human
   form is documented — *"your `noreply` email address is an ID number and your username in the
   form of `ID+USERNAME@users.noreply.github.com`"*
   ([email addresses reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference)).
   Treat the bot form as convention; derive the ID empirically if it must be load-bearing.
8. That a git+HTTPS push with an installation token takes its commit author from local git
   config, and that such commits are unsigned. Established indirectly by the email-matching docs.
9. Whether GitHub accepts `+`-addressed email aliases for separate accounts.
10. The maximum expiry allowed for a fine-grained PAT (source could not be retrieved).

### Resolved since first draft

- **Cap on GitHub Apps per personal account: 100.** *"A user or organization can register up to
  100 GitHub Apps."* (Previously listed as "none found".)
- **Commit attribution under an installation token** — fully answered above; see the
  REST-vs-`git push` table.

### Settled by smoke test — [#15](https://github.com/mcnewcp/my-team/issues/15), 2026-08-15

Run against `mcnewcp/personal-assistant` with the reviewer App (`app_id` 4608397). Both
throwaway PRs were closed and their branches deleted; `main` was unchanged.

- **A GitHub App installation token *can* submit a formal approving review.** `gh pr review
  --approve` produced a review with `state: "APPROVED"`, `user.login:
  "my-team-reviewer-mcnewcp[bot]"`, `user.type: "Bot"`, and GitHub's own `reviewDecision:
  "APPROVED"`. The PR carried **zero** issue comments, so it did not silently degrade into a
  comment. Question 1 above is now fact, not inference.
- **"Cannot approve your own pull request" applies to Apps, in both directions.** An App
  approving a PR authored by `mcnewcp` **succeeds** — the App is a distinct actor from its
  owner. The same App approving a PR **it** authored fails with `422 Unprocessable Entity`,
  `errors: ["Review Can not approve your own pull request"]`. Design consequence: the
  never-open-and-approve rule is **enforced by GitHub**, so an orchestrator bug cannot
  manufacture a bogus approval. Enforce it locally anyway, to fail fast with a clear message.
- **`gh` exit code is not evidence.** `gh pr review --approve` exits 0; only the reviews
  endpoint establishes what actually landed. Another instance of the *verify by observation*
  rule that governs the state machine.

Provisioning is repeatable via `scripts/register-role-app.sh` in the orchestrator repo.
