"""Speaking as a role: the private key, the App JWT, and the installation token.

`gh` has no GitHub App support, so everything an App identity does starts here. The
sequence is fixed and short: read the role's key, sign a JWT with it
([`core.app_jwt`](core/app_jwt.py)), and exchange that for an **installation token**,
which GitHub expires after an hour. The token is handed to exactly one subprocess
through its environment and is never written down.

Keys live at `~/.config/my-team/keys/<role>.pem`, mode `0600`, **outside every repo**:
never a path inside the target repo, so there is nothing to `.gitignore` and nothing
for a dispatched agent to stage by accident. `read_private_key` refuses any other mode
rather than merely reporting it — `doctor` is the report, and this is the refusal.

⚠️ A risk accepted knowingly and recorded rather than papered over: a dispatched agent
runs as the same OS user, so it *can* read these keys. The Apps sit on repos the owner
controls and revocation takes seconds.
"""

from __future__ import annotations

import http.client
import json
import stat
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from my_team.core.app_jwt import app_jwt
from my_team.core.config import KEY_MODE, RoleConfig

GITHUB_API: Final = "https://api.github.com"

TOKEN_VARIABLE: Final = "GH_TOKEN"
"""The variable an installation token travels in. `gh` documents it as taking
precedence over stored credentials, which is what makes a role a per-subprocess fact
rather than a global one — see `my_team.github_cli`."""

API_TIMEOUT_SECONDS: Final = 30.0


class CredentialError(RuntimeError):
    """A role credential that will not work, and why."""


class AppApiError(CredentialError):
    """GitHub refused a call made as the App.

    Carries the status because a `404` and an outage are different findings: an
    installation that does not resolve is something to report about the config, and a
    network failure is something to report about the run.
    """

    def __init__(self, status: int, path: str, body: str) -> None:
        super().__init__(f"{path}: GitHub returned {status} — {body.strip()[:200]}")
        self.status = status
        self.path = path


@dataclass(frozen=True, slots=True)
class InstallationToken:
    """A role's credential for one hour. Never persisted, never logged.

    Never logged is enforced rather than remembered: a dataclass prints every field it
    has, and `repr` is what a traceback frame, a failed assertion and an idle `print`
    all reach for. Keeping the secret out of it makes the rule a property of the type.
    """

    token: str = field(repr=False)
    expires_at: str


def key_file(role: RoleConfig) -> Path:
    """The role's key path with `~` expanded — the one place expansion happens.

    `RoleConfig` keeps the path exactly as the file wrote it so that parsing does not
    depend on `$HOME`; this is where that dependency is allowed to exist.
    """
    return role.key_path.expanduser()


def key_mode(path: Path) -> int | None:
    """A regular file's permission bits, or `None` when there is no key file there.

    Only a regular file counts. A directory at the key's path has permission bits like
    anything else, and a `0600` one would otherwise clear the mode check and fail as an
    `IsADirectoryError` two calls later — a traceback where a named precondition
    belongs. A path the filesystem refuses to stat at all is the same answer for the
    same reason: whatever is there, it is not a key anything can read.
    """
    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_mode & 0o777 if stat.S_ISREG(found.st_mode) else None


def read_private_key(path: Path) -> str:
    """The PEM at `path`, refusing anything a role key must not be."""
    mode = key_mode(path)
    if mode is None:
        raise CredentialError(f"no private key at {path}")
    if mode != KEY_MODE:
        raise CredentialError(f"{path} is mode {mode:04o} — role keys are {KEY_MODE:04o}")
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError) as error:
        # A key is text or it is not a key. Both halves — the file that will not open
        # and the bytes that will not decode — are the same finding to a caller, and
        # neither is a traceback out of a diagnostic.
        raise CredentialError(f"{path} could not be read — {error}") from error


def app_jwt_for(role: RoleConfig, *, now: int) -> str:
    """Sign this role's App identity. Minted per use; nothing caches one."""
    return app_jwt(read_private_key(key_file(role)), app_id=role.app_id, now=now)


def app_get(jwt: str, path: str) -> Mapping[str, Any]:
    """A GET made as the App itself. `gh api` cannot do this — it sends
    `Authorization: token`, and an App identity needs `Bearer`."""
    return _api(path, jwt, method="GET")


def installation_token(role: RoleConfig, *, now: int) -> InstallationToken:
    """Mint this role's token for the next hour.

    Minted per use rather than cached: GitHub expires them after an hour, so a cache
    would be a second clock to get wrong, and the token would then have to live
    somewhere.
    """
    path = f"/app/installations/{role.installation_id}/access_tokens"
    minted = _api(path, app_jwt_for(role, now=now), method="POST")
    token, expires_at = minted.get("token"), minted.get("expires_at")
    if not isinstance(token, str) or not isinstance(expires_at, str):
        raise CredentialError(f"{path}: GitHub answered without a token and an expiry")
    return InstallationToken(token=token, expires_at=expires_at)


def token_env(token: InstallationToken) -> dict[str, str]:
    """The environment overlay that makes one subprocess act as a role.

    Takes the token rather than the string inside it: this is the boundary the secret
    exists to cross, so it is the one place that unwraps one. A caller that had to say
    `.token` to pass it along would be carrying a bare `str` through every frame in
    between, which is exactly where the redacted `repr` was meant to keep it out of.

    Deliberately not a mutation of `os.environ`, and deliberately not `gh auth switch`:
    both would make the acting identity a property of the machine rather than of the
    call, and two ticks under different roles would then race.
    """
    return {TOKEN_VARIABLE: token.token}


def _api(path: str, jwt: str, *, method: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "my-team",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise AppApiError(error.code, path, error.read().decode(errors="replace")) from error
    except urllib.error.URLError as error:
        raise CredentialError(f"{path}: could not reach GitHub — {error.reason}") from error
    except (OSError, ValueError, http.client.HTTPException) as error:
        # A status GitHub is happy with says nothing about the body arriving intact. A
        # proxy or a maintenance page answers `200` with HTML, and a connection that
        # drops mid-body raises `IncompleteRead`, which descends from none of the
        # families above it — both are the same finding, and neither is a traceback out
        # of the command whose job is naming the unmet condition.
        raise CredentialError(f"{path}: GitHub's answer could not be read — {error}") from error
    if not isinstance(payload, dict):
        # Every caller here reads what came back by key, so a JSON array would surface
        # several frames later as an `AttributeError` naming a method rather than a call.
        raise CredentialError(
            f"{path}: GitHub answered with {type(payload).__name__} rather than an object"
        )
    return payload
