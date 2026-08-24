"""Fixtures shared by more than one test module."""

from __future__ import annotations

import pytest

from der_encoding import as_pem, der, der_integer


@pytest.fixture(scope="session")
def rsa_pem() -> str:
    """An RSA private key *structure*: parseable, big enough to pad, not a real pair.

    What a signature is worth is `tests/test_app_jwt.py`'s question, and it asks
    openssl. Everything else only needs bytes that reach the signer — so the key is
    built here rather than committed, since a real PEM in a repo is secret-scanner bait
    for no gain.
    """
    return as_pem(
        "RSA PRIVATE KEY",
        der(
            0x30,
            der_integer(0) + der_integer(2**1023 + 5) + der_integer(65537) + der_integer(65537),
        ),
    )
