"""Fixtures shared by more than one test module."""

from __future__ import annotations

import base64

import pytest


def _der(tag: int, value: bytes) -> bytes:
    if len(value) < 0x80:
        return bytes([tag, len(value)]) + value
    length = len(value).to_bytes((len(value).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(length)]) + length + value


def _integer(value: int) -> bytes:
    return _der(0x02, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big"))


@pytest.fixture(scope="session")
def rsa_pem() -> str:
    """An RSA private key *structure*: parseable, big enough to pad, not a real pair.

    What a signature is worth is `tests/test_app_jwt.py`'s question, and it asks
    openssl. Everything else only needs bytes that reach the signer — so the key is
    built here rather than committed, since a real PEM in a repo is secret-scanner bait
    for no gain.
    """
    body = _der(
        0x30,
        _integer(0) + _integer(2**1023 + 5) + _integer(65537) + _integer(65537),
    )
    encoded = base64.encodebytes(body).decode()
    return f"-----BEGIN RSA PRIVATE KEY-----\n{encoded}-----END RSA PRIVATE KEY-----\n"
