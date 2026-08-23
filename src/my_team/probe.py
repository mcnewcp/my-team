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
from pathlib import Path
from typing import Any, Final

from my_team.config_file import load_config
from my_team.core.app_jwt import PrivateKeyError
from my_team.core.config import KEY_MODE, ROLE_NAMES, Config, ConfigError, RoleConfig
from my_team.core.doctor import (
    Facts,
    GhFacts,
    HarnessFacts,
    OwnerFacts,
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
)
from my_team.github_cli import GH, GhError, gh_json, run_gh

HARNESS_BINARY: Final = "claude"
"""The binary the harness seam spawns. v0.1 ships one harness, so this is a constant
rather than a config key; the seam takes ownership of it when a second one arrives."""


def probe(repo_root: Path, *, now: int) -> Facts:
    """Read every precondition `doctor` reports on. Writes nothing, anywhere."""
    gh = _gh()
    config = _config(repo_root)
    repository = _repository(gh, repo_root)
    repo = _repo(repository, repo_root)
    return Facts(
        gh=gh,
        harness=_harness(),
        config=config,
        owner=_owner(config, repository, repo_root),
        repo=repo,
        protection=_protection(repo, repo_root),
        roles=_roles(config, repo_root, now=now),
    )


def _gh() -> GhFacts | Unavailable:
    path = shutil.which(GH)
    if path is None:
        return Unavailable(f"`{GH}` is not on PATH — see cli.github.com")
    try:
        account = run_gh(["api", "user", "--jq", ".login"]).strip()
    except GhError:
        return GhFacts(path=path, account=None)
    return GhFacts(path=path, account=account or None)


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


def _repository(gh: GhFacts | Unavailable, repo_root: Path) -> str | Unavailable:
    """`owner/repo`, which everything below needs and nothing else supplies."""
    if isinstance(gh, Unavailable) or gh.account is None:
        return Unavailable("not checked — `gh` could not identify an account")
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
        labels = run_gh(
            ["api", f"repos/{repository}/labels", "--paginate", "--jq", ".[].name"], cwd=repo_root
        )
    except GhError as error:
        return Unavailable(error.reason)
    try:
        return RepoFacts(
            name_with_owner=repository,
            default_branch=data["default_branch"],
            allow_squash_merge=bool(data["allow_squash_merge"]),
            allow_merge_commit=bool(data["allow_merge_commit"]),
            allow_rebase_merge=bool(data["allow_rebase_merge"]),
            delete_branch_on_merge=bool(data["delete_branch_on_merge"]),
            labels=tuple(labels.split()),
        )
    except (KeyError, TypeError) as error:
        return Unavailable(f"{repository}: GitHub described the repo unrecognisably — {error}")


def _owner(
    config: Config | Unavailable, repository: str | Unavailable, repo_root: Path
) -> OwnerFacts | Unavailable:
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
    return OwnerFacts(login=login, permission=permission)


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
    try:
        protected = run_gh(
            ["api", f"repos/{repo.name_with_owner}/branches/{branch}", "--jq", ".protected"],
            cwd=repo_root,
        ).strip()
        if protected != "true":
            return Unprotected(branch=branch)
        data = gh_json(
            ["api", f"repos/{repo.name_with_owner}/branches/{branch}/protection"], cwd=repo_root
        )
    except GhError as error:
        return Unavailable(error.reason)
    return _protection_of(branch, data)


def _protection_of(branch: str, data: Any) -> Protection | Unavailable:
    try:
        reviews = data.get("required_pull_request_reviews") or {}
        return Protection(
            branch=branch,
            required_approving_review_count=reviews.get("required_approving_review_count"),
            enforce_admins=bool((data.get("enforce_admins") or {}).get("enabled")),
            require_last_push_approval=bool(reviews.get("require_last_push_approval")),
        )
    except AttributeError as error:
        return Unavailable(f"{branch}: GitHub described the protection unrecognisably — {error}")


def _roles(
    config: Config | Unavailable, repo_root: Path, *, now: int
) -> Mapping[str, RoleFacts | Unavailable]:
    if isinstance(config, Unavailable):
        return dict.fromkeys(ROLE_NAMES, Unavailable("not checked — the config did not parse"))
    return {name: _role(getattr(config.roles, name), repo_root, now=now) for name in ROLE_NAMES}


def _role(role: RoleConfig, repo_root: Path, *, now: int) -> RoleFacts | Unavailable:
    path = key_file(role)
    mode = key_mode(path)
    inside = path.resolve().is_relative_to(repo_root.resolve())

    def unproven(**overrides: Any) -> RoleFacts:
        return RoleFacts(
            declared=role,
            key_path=path,
            key_mode=mode,
            key_inside_repo=inside,
            **{
                "app_slug": None,
                "installation_resolved": False,
                "bot_user_id": None,
                **overrides,
            },
        )

    if mode is None or inside or mode != KEY_MODE:
        return unproven()

    try:
        jwt = app_jwt_for(role, now=now)
    except (CredentialError, PrivateKeyError) as error:
        return Unavailable(f"{path}: {error}")

    try:
        slug = app_get(jwt, "/app").get("slug")
    except AppApiError:
        # The key parsed and GitHub refused it, which is exactly the claim the finding
        # makes: this key is not app_id's key.
        return unproven()
    except CredentialError as error:
        return Unavailable(str(error))
    if not isinstance(slug, str):
        return Unavailable(f"{role.app_id}: GitHub described the App without a slug")

    try:
        app_get(jwt, f"/app/installations/{role.installation_id}")
    except AppApiError as error:
        if error.status != 404:
            return Unavailable(str(error))
        return unproven(app_slug=slug)
    except CredentialError as error:
        return Unavailable(str(error))

    return unproven(app_slug=slug, installation_resolved=True, bot_user_id=_bot_user(slug))


def _bot_user(slug: str) -> int | None:
    """The numeric id reviews are matched on, which is not derivable from `app_id`.

    Looked up as the human: `/users/...` is not an endpoint an App JWT may reach. The
    login is percent-encoded because the account really is called `<slug>[bot]`.
    """
    try:
        return int(run_gh(["api", f"/users/{slug}%5Bbot%5D", "--jq", ".id"]).strip())
    except (GhError, ValueError):
        return None
