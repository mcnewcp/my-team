"""The App JWT: the credential a role signs for itself, and the only cryptography here.

`gh` has no GitHub App support — it sends `Authorization: token`, and an App identity
needs a `Bearer` JWT signed by the App's private key — so the orchestrator mints the
JWT itself. Three ways to sign RS256 were open, and each of the other two costs
something the package has decided not to pay:

- **A dependency** (`PyJWT`, `cryptography`) — `pyproject.toml` declares no runtime
  dependencies at all, deliberately: the orchestrator shells out to `gh` and to a
  harness binary and is otherwise standard library. `cryptography` is a wheel with a
  compiled Rust extension, which is a real install-time cost for one signature.
- **`openssl dgst -sign`** — a third binary on the critical path, and therefore a
  fourth blocking `doctor` check that §1 does not list.

So it is signed here, in about eighty lines of standard library. RSASSA-PKCS1-v1_5 is
deterministic and takes no randomness, and the private key is one the process already
holds, so neither of the two things usually worth fearing in hand-written signing —
a bad nonce and a timing side channel against a key the attacker does not have — is
in play. What *is* in play is getting the padding or the DER wrong, and that is what
`tests/test_app_jwt.py` checks by handing every signature back to `openssl` to verify.

See [ADR 0011](../../../docs/adr/0011-the-app-jwt-is-signed-in-process.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

JWT_SKEW_SECONDS: Final = 60
"""How far `iat` is backdated, so a clock a minute fast does not mint a future token."""

JWT_LIFETIME_SECONDS: Final = 480
"""How long the JWT is good for. GitHub rejects a window wider than 600 seconds, and
the backdating above is spent out of the same budget — 60 + 480 leaves a minute spare."""


class PrivateKeyError(ValueError):
    """A PEM that will not sign. The message says which of the four ways it failed."""


@dataclass(frozen=True, slots=True)
class _RsaPrivateKey:
    modulus: int
    private_exponent: int


def app_jwt(private_key_pem: str, *, app_id: int, now: int) -> str:
    """A signed JWT asserting `app_id`, valid from a minute ago for eight minutes.

    `now` is a parameter rather than a clock read here, for the same reason the ladder
    takes one: it is what makes the window assertable without waiting for it.
    """
    key = _rsa_private_key(private_key_pem)
    header = _segment({"alg": "RS256", "typ": "JWT"})
    payload = _segment(
        {
            "iat": now - JWT_SKEW_SECONDS,
            "exp": now + JWT_LIFETIME_SECONDS,
            "iss": str(app_id),
        }
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_b64url(_sign(key, signing_input.encode()))}"


def _segment(claims: dict[str, object]) -> str:
    return _b64url(json.dumps(claims, separators=(",", ":")).encode())


def _b64url(raw: bytes) -> str:
    """Base64url with the padding stripped, which is what JWS specifies."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# DigestInfo for SHA-256, DER-encoded: the SEQUENCE, the algorithm OID, its NULL
# parameters and the OCTET STRING header the 32-byte digest is appended to. Fixed by
# RFC 8017 §9.2, which is why it is a constant rather than something built at runtime.
_SHA256_DIGEST_INFO: Final = bytes.fromhex("3031300d060960864801650304020105000420")

# The smallest modulus that leaves PKCS#1 v1.5 its mandatory eight padding bytes. Any
# real App key is 2048 bits; this only stops a key too small to pad from being signed
# with silently.
_MINIMUM_MODULUS_BYTES: Final = len(_SHA256_DIGEST_INFO) + hashlib.sha256().digest_size + 11


def _sign(key: _RsaPrivateKey, message: bytes) -> bytes:
    """RSASSA-PKCS1-v1_5 over SHA-256 — deterministic, so the same input always signs
    to the same bytes."""
    size = (key.modulus.bit_length() + 7) // 8
    digest_info = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), key.private_exponent, key.modulus)
    return signature.to_bytes(size, "big")


_PEM_BLOCK: Final = re.compile(
    r"-----BEGIN (?P<label>[A-Z0-9 ]+)-----(?P<body>.*?)-----END (?P=label)-----",
    re.DOTALL,
)
_PKCS1_LABEL: Final = "RSA PRIVATE KEY"
_PKCS8_LABEL: Final = "PRIVATE KEY"


def _rsa_private_key(text: str) -> _RsaPrivateKey:
    """Parse either PEM encoding of an RSA private key.

    GitHub hands out PKCS#1 (`BEGIN RSA PRIVATE KEY`); anything that has been through
    a modern `openssl` comes back as PKCS#8 (`BEGIN PRIVATE KEY`). Both parse, because
    a key that survived a round trip is still the key.
    """
    block = _PEM_BLOCK.search(text)
    if block is None:
        raise PrivateKeyError("no PEM block: expected a -----BEGIN ...----- header")

    label = block.group("label")
    if label not in (_PKCS1_LABEL, _PKCS8_LABEL):
        raise PrivateKeyError(f"a {label} block is not an RSA private key")

    body = "".join(block.group("body").split())
    if not body:
        raise PrivateKeyError(f"the {label} block is empty")
    try:
        der = base64.b64decode(body, validate=True)
    except ValueError as error:
        raise PrivateKeyError(f"the {label} block is not valid base64 — {error}") from error

    key = _from_pkcs1(der) if label == _PKCS1_LABEL else _from_pkcs8(der)
    if (key.modulus.bit_length() + 7) // 8 < _MINIMUM_MODULUS_BYTES:
        raise PrivateKeyError("the modulus is too small to sign a SHA-256 digest")
    return key


_SEQUENCE: Final = 0x30
_INTEGER: Final = 0x02
_OCTET_STRING: Final = 0x04
_OBJECT_IDENTIFIER: Final = 0x06

# 1.2.840.113549.1.1.1 — rsaEncryption. A PKCS#8 wrapper around an EC key has exactly
# the same shape, so this is the only thing that tells them apart before the arithmetic
# starts producing nonsense.
_RSA_ENCRYPTION_OID: Final = bytes.fromhex("2a864886f70d010101")


def _from_pkcs1(der: bytes) -> _RsaPrivateKey:
    """RSAPrivateKey ::= SEQUENCE { version, modulus, publicExponent, privateExponent, ... }"""
    body, _ = _take(der, _SEQUENCE)
    _, body = _take(body, _INTEGER)
    modulus, body = _take(body, _INTEGER)
    _, body = _take(body, _INTEGER)
    private_exponent, _ = _take(body, _INTEGER)
    return _RsaPrivateKey(
        modulus=int.from_bytes(modulus, "big"),
        private_exponent=int.from_bytes(private_exponent, "big"),
    )


def _from_pkcs8(der: bytes) -> _RsaPrivateKey:
    """PrivateKeyInfo ::= SEQUENCE { version, algorithm, privateKey OCTET STRING }"""
    body, _ = _take(der, _SEQUENCE)
    _, body = _take(body, _INTEGER)
    algorithm, body = _take(body, _SEQUENCE)
    oid, _ = _take(algorithm, _OBJECT_IDENTIFIER)
    if oid != _RSA_ENCRYPTION_OID:
        raise PrivateKeyError("the PKCS#8 wrapper does not hold an RSA key")
    inner, _ = _take(body, _OCTET_STRING)
    return _from_pkcs1(inner)


def _take(data: bytes, tag: int) -> tuple[bytes, bytes]:
    """The value of the DER element at the front of `data`, and whatever follows it."""
    if len(data) < 2:
        raise PrivateKeyError("malformed DER: the key ends where a value was expected")
    if data[0] != tag:
        raise PrivateKeyError(f"malformed DER: expected tag 0x{tag:02x}, found 0x{data[0]:02x}")
    marker = data[1]
    if marker < 0x80:
        length, start = marker, 2
    else:
        width = marker & 0x7F
        if not 1 <= width <= 4 or len(data) < 2 + width:
            raise PrivateKeyError("malformed DER: unreadable length")
        length, start = int.from_bytes(data[2 : 2 + width], "big"), 2 + width
    end = start + length
    if end > len(data):
        raise PrivateKeyError("malformed DER: a value runs past the end of the key")
    return data[start:end], data[end:]
