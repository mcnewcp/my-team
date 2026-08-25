"""Everything `doctor` asks the world, so that deciding what it means can be pure.

The I/O half of the command: `probe` gathers `Facts` and
[`core.doctor.evaluate`](core/doctor.py) reads nothing else. Two rules shape it:

- **It never mutates.** Every call here is a read, which is why the role check
  *resolves* an installation rather than minting a token from it — minting creates a
  credential, and the same JWT proving the GET would prove the POST.
- **A check whose prerequisite failed carries `Unavailable` and says which one.** The
  cascade lives here rather than in `evaluate`, because knowing it could not proceed is
  something only the thing doing the work knows.

Three identities are in play and they do different work. `gh` reads as the **human**,
whose login `doctor` blocks on. Each **role** proves itself with its own App JWT. And
the bot user behind a role is looked up as the human again, because `/users/...` is not
an endpoint an App JWT may reach.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from my_team.config_file import load_config
from my_team.core.app_jwt import PrivateKeyError
from my_team.core.config import KEY_MODE, ROLE_NAMES, Config, ConfigError, RoleConfig
from my_team.core.doctor import (
    Facts,
    GhFacts,
    HarnessFacts,
    InstallationFacts,
    ProductOwnerFacts,
    Protection,
    RepoFacts,
    RoleFacts,
    Unavailable,
    Unprotected,
)
from my_team.credentials import (
    AppApiError,
    CredentialError,
    app_get,
    app_jwt_for,
    key_file,
    key_mode,
    repo_containing,
)
from my_team.github_cli import GH, GhError, gh_json, run_gh

HARNESS_BINARY: Final = "claude"
"""The binary the harness seam spawns. v0.1 ships one harness, so this is a constant
rather than a config key; the seam takes ownership of it when a second one arrives."""


def probe(repo_root: Path, *, now: int) -> Facts:
    """Read every precondition `doctor` reports on. Writes nothing, anywhere."""
    gh = _gh()
    # Who `gh` is logged in as, or why nobody is. Missing, unauthenticated and unreachable
    # block everything below alike, so they become one value here rather than at each
    # place that asks — one that still says which of the three it was.
    account = _account(gh)
    config = _config(repo_root)
    repository = _repository(account, repo_root)
    repo = _repo(repository, repo_root)
    return Facts(
        gh=gh,
        harness=_harness(),
        config=config,
        product_owner=_product_owner(config, repository, repo_root),
        repo=repo,
        protection=_protection(repo, repo_root),
        roles=_roles(config, account, repository, now=now),
    )


def _gh() -> GhFacts | Unavailable:
    path = shutil.which(GH)
    if path is None:
        return Unavailable(f"`{GH}` is not on PATH — see cli.github.com")
    try:
        account = run_gh(["api", "user", "--jq", ".login"]).strip()
    except GhError as error:
        # `gh` ran and did not answer. A timeout, a `502` and an expired token are three
        # conditions and one of them is "log in again", so the reason travels rather
        # than collapsing into the logged-in-as-nobody line below.
        return GhFacts(path=path, account=Unavailable(error.reason))
    return GhFacts(path=path, account=account or None)


def _account(gh: GhFacts | Unavailable) -> str | Unavailable:
    """The human's login, or the one reason everything needing it goes unchecked."""
    if isinstance(gh, Unavailable):
        return gh
    if isinstance(gh.account, Unavailable):
        return gh.account
    if gh.account is None:
        return Unavailable(f"`{GH}` reported no account")
    return gh.account


def _harness() -> HarnessFacts | Unavailable:
    path = shutil.which(HARNESS_BINARY)
    if path is None:
        return Unavailable(f"`{HARNESS_BINARY}` is not on PATH")
    return HarnessFacts(binary=HARNESS_BINARY, path=path)


def _config(repo_root: Path) -> Config | Unavailable:
    try:
        return load_config(repo_root)
    except ConfigError as error:
        return Unavailable(str(error))


def _repository(account: str | Unavailable, repo_root: Path) -> str | Unavailable:
    """`owner/repo`, which everything below needs and nothing else supplies."""
    if isinstance(account, Unavailable):
        return Unavailable(f"not checked — {account.reason}")
    try:
        name = run_gh(
            ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo_root
        ).strip()
    except GhError as error:
        return Unavailable(error.reason)
    return name or Unavailable(f"{repo_root} does not resolve to a GitHub repository")


def _repo(repository: str | Unavailable, repo_root: Path) -> RepoFacts | Unavailable:
    if isinstance(repository, Unavailable):
        return repository
    try:
        data = gh_json(["api", f"repos/{repository}"], cwd=repo_root)
    except GhError as error:
        return Unavailable(error.reason)
    try:
        return RepoFacts(
            name_with_owner=repository,
            default_branch=_field(data, "default_branch", str),
            allow_squash_merge=_field(data, "allow_squash_merge", bool),
            allow_merge_commit=_field(data, "allow_merge_commit", bool),
            allow_rebase_merge=_field(data, "allow_rebase_merge", bool),
            delete_branch_on_merge=_field(data, "delete_branch_on_merge", bool),
            labels=_labels(repository, repo_root),
        )
    except (KeyError, TypeError) as error:
        return Unavailable(f"{repository}: GitHub described the repo unrecognisably — {error}")


def _field[T](data: Any, name: str, kind: type[T]) -> T:
    """One field of the repo response, or the error a missing one already raises.

    A `200` is not a description: GitHub can answer with the field null, and coercing
    that is the failure. `bool(None)` is `False`, which reports a merge policy nobody
    set, and `quote(None)` is a traceback out of the one command whose whole job is
    naming the unmet precondition. Absent and unrecognisable are one diagnosis, so this
    raises what the caller already catches rather than adding a second way to fail.
    """
    value = data[name]
    if type(value) is not kind:
        raise TypeError(f"`{name}` is {value!r}")
    return value


def _labels(repository: str, repo_root: Path) -> tuple[str, ...] | Unavailable:
    """The repo's label names — a second request, so a second answer.

    Folding this into the repo object made a failed label listing erase a merge policy
    GitHub had already described, and skip protection, which needs nothing from here but
    the default branch. Two requests fail in two ways and are reported as two.

    Called from inside `_repo`'s own `try` deliberately: it raises neither of the two
    types that handler catches, and asking GitHub a second question after it answered
    the first unrecognisably buys nothing.
    """
    try:
        # One name per line, so split on lines and not on whitespace: `good first issue`
        # is one label.
        listed = run_gh(
            ["api", f"repos/{repository}/labels", "--paginate", "--jq", ".[].name"], cwd=repo_root
        )
    except GhError as error:
        return Unavailable(error.reason)
    return tuple(listed.splitlines())


def _product_owner(
    config: Config | Unavailable, repository: str | Unavailable, repo_root: Path
) -> ProductOwnerFacts | Unavailable:
    """The one round trip to the `permission` API the design allows itself.

    Without it a mistyped login makes the human's own guidance silently invisible to
    every prompt — a failure with no symptom, which is the kind worth a network call.
    """
    if isinstance(config, Unavailable):
        return Unavailable("not checked — the config did not parse")
    if isinstance(repository, Unavailable):
        return repository
    login = config.product_owner
    try:
        permission = run_gh(
            ["api", f"repos/{repository}/collaborators/{login}/permission", "--jq", ".permission"],
            cwd=repo_root,
        ).strip()
    except GhError as error:
        return Unavailable(f"{login}: {error.reason}")
    return ProductOwnerFacts(login=login, permission=permission)


def _protection(
    repo: RepoFacts | Unavailable, repo_root: Path
) -> Protection | Unprotected | Unavailable:
    """Read the branch first, then its protection only if there is any.

    Asking for `/protection` on an unprotected branch answers `404`, and telling that
    apart from a real failure would mean reading `gh`'s error prose. The branch object
    already says whether it is protected, so nothing has to.
    """
    if isinstance(repo, Unavailable):
        return repo
    branch = repo.default_branch
    # One path segment, percent-encoded. A branch may legally be called `release#1`, and
    # interpolated raw the `#` starts a URL fragment — so the request asks about
    # `release`, GitHub answers about a different branch, and the diagnosis is confidently
    # wrong. Encoding the `/` in `release/1.0` too is measured rather than assumed:
    # `gh api repos/cli/cli/branches/af%2F12325-pr-view-project-null` and the same path
    # with a raw `/` return the same branch, so one segment is safe for both shapes.
    ref = quote(branch, safe="")
    try:
        protected = run_gh(
            ["api", f"repos/{repo.name_with_owner}/branches/{ref}", "--jq", ".protected"],
            cwd=repo_root,
        ).strip()
        if protected == "false":
            return Unprotected(branch=branch)
        if protected != "true":
            return Unavailable(
                f"{branch}: GitHub described the branch's `protected` flag "
                f"unrecognisably — {protected!r}"
            )
        data = gh_json(
            ["api", f"repos/{repo.name_with_owner}/branches/{ref}/protection"], cwd=repo_root
        )
    except GhError as error:
        return Unavailable(error.reason)
    return _protection_of(branch, data)


def _protection_of(branch: str, data: Any) -> Protection | Unavailable:
    try:
        reviews = data.get("required_pull_request_reviews")
        count = None
        last_push = False
        if reviews is not None:
            reviews = _field(data, "required_pull_request_reviews", dict)
            count = _field(reviews, "required_approving_review_count", int)
            last_push = _field(reviews, "require_last_push_approval", bool)
        enforce_admins = _field(data, "enforce_admins", dict)
        return Protection(
            branch=branch,
            required_approving_review_count=count,
            enforce_admins=_field(enforce_admins, "enabled", bool),
            require_last_push_approval=last_push,
        )
    except (AttributeError, KeyError, TypeError) as error:
        return Unavailable(f"{branch}: GitHub described the protection unrecognisably — {error}")


def _roles(
    config: Config | Unavailable,
    account: str | Unavailable,
    repository: str | Unavailable,
    *,
    now: int,
) -> Mapping[str, RoleFacts | Unavailable]:
    if isinstance(config, Unavailable):
        return dict.fromkeys(ROLE_NAMES, Unavailable("not checked — the config did not parse"))
    named = None if isinstance(repository, Unavailable) else repository
    return {
        name: _role(getattr(config.roles, name), account, named, now=now) for name in ROLE_NAMES
    }


def _role(
    role: RoleConfig,
    account: str | Unavailable,
    repository: str | None,
    *,
    now: int,
) -> RoleFacts | Unavailable:
    path = key_file(role)
    mode = key_mode(path)
    repo = repo_containing(path)

    def found(
        *,
        app_slug: str | None = None,
        installation: InstallationFacts | None = None,
        installation_reaches_repo: bool | Unavailable | None = None,
        bot_user_id: int | Unavailable | None = None,
    ) -> RoleFacts:
        """What is known so far. Each step below adds one field and stops on failure."""
        return RoleFacts(
            declared=role,
            key_path=path,
            key_mode=mode,
            key_repo=repo,
            app_slug=app_slug,
            installation=installation,
            installation_reaches_repo=installation_reaches_repo,
            bot_user_id=bot_user_id,
        )

    if mode is None or repo is not None or mode != KEY_MODE:
        return found()

    try:
        jwt = app_jwt_for(role, now=now)
    except (CredentialError, PrivateKeyError) as error:
        return Unavailable(f"{path}: {error}")

    try:
        slug = app_get(jwt, "/app").get("slug")
    except AppApiError as error:
        if error.status != HTTPStatus.UNAUTHORIZED:
            # A rate limit or a 5xx says nothing about whose key this is. Reporting one
            # as a credential mismatch would name the wrong unmet condition, which is
            # the single thing this command exists not to do.
            return Unavailable(str(error))
        # The key parsed and GitHub refused it, which is exactly the claim the finding
        # makes: this key is not app_id's key.
        return found()
    except CredentialError as error:
        return Unavailable(str(error))
    if not isinstance(slug, str):
        return Unavailable(f"{role.app_id}: GitHub described the App without a slug")

    try:
        described = app_get(jwt, f"/app/installations/{role.installation_id}")
    except AppApiError as error:
        if error.status != HTTPStatus.NOT_FOUND:
            return Unavailable(str(error))
        return found(app_slug=slug)
    except CredentialError as error:
        return Unavailable(str(error))
    # Two last questions, asked of two different services and reported apart. Coverage
    # is a check §1 does not enumerate and the bot id is one it requires, so letting
    # either return early for the other put an addition in front of a requirement — and
    # made a transient failure read as an unexamined role.
    return found(
        app_slug=slug,
        installation=_installation(described, role),
        installation_reaches_repo=_reaches(jwt, repository, role),
        bot_user_id=_bot_user(account, slug),
    )


def _installation(described: Mapping[str, Any], role: RoleConfig) -> InstallationFacts:
    """What the installation grants, out of the response that proved it resolves.

    An installation that resolves is not yet one a role can act with: GitHub suspends an
    installation without removing it, and the permissions it was accepted with are the
    ones it actually has — not the ones the App now asks for. Both arrive in this
    response, so neither costs a request.

    A grant that cannot be read goes into `permissions` rather than being returned in
    place of the whole role. What an installation grants is one of the checks §1 does
    not enumerate, and returning `Unavailable` here left a role whose key, App and bot
    id were all provable reported as if none of them had been looked at.
    """
    granted = described.get("permissions")
    permissions: Mapping[str, str] | Unavailable = Unavailable(
        f"GitHub described installation {role.installation_id} unrecognisably"
    )
    if isinstance(granted, dict) and all(isinstance(level, str) for level in granted.values()):
        permissions = granted
    return InstallationFacts(
        suspended=described.get("suspended_at") is not None, permissions=permissions
    )


def _reaches(jwt: str, repository: str | None, role: RoleConfig) -> bool | Unavailable | None:
    """Whether the configured installation is the one covering the target repo.

    An installation that exists but does not cover this repo passes every other check
    here and then fails the role's first write. Asking the repo which installation it
    has answers both halves at once — not installed at all is a `404`, and installed
    under a different id is a mismatch.

    `None` when the repo could not be named: everything else about a role is provable
    with its own key, and that stays worth reporting when `gh` is the thing at fault.
    """
    if repository is None:
        return None
    try:
        covering = app_get(jwt, f"/repos/{repository}/installation").get("id")
    except AppApiError as error:
        if error.status == HTTPStatus.NOT_FOUND:
            return False
        return Unavailable(str(error))
    except CredentialError as error:
        return Unavailable(str(error))
    if not isinstance(covering, int):
        # A definite *no* blocks a run, so it is claimed only on an answer that says so.
        return Unavailable(f"{repository}: GitHub named its installation without an id")
    return covering == role.installation_id


def _bot_user(account: str | Unavailable, slug: str) -> int | Unavailable | None:
    """The numeric id reviews are matched on, which is not derivable from `app_id`.

    Looked up as the human: `/users/...` is not an endpoint an App JWT may reach — so
    when `gh` is the thing that failed, `gh` is what gets reported. Collapsing that to
    "the bot did not resolve" named three bot accounts as the problem when the problem
    was one login. The slug is percent-encoded because the account really is called
    `<slug>[bot]`.
    """
    if isinstance(account, Unavailable):
        return account
    try:
        return int(run_gh(["api", f"/users/{slug}%5Bbot%5D", "--jq", ".id"]).strip())
    except GhError as error:
        # The lookup itself failed. Which is a fact about `gh` or about GitHub, never
        # about a bot account nobody managed to ask after — so it is reported as one.
        return Unavailable(error.reason)
    except ValueError:
        # `gh` succeeded and printed something that is not a number, which is the one
        # answer that really is about the account: there is no id under that login.
        return None
