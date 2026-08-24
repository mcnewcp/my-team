"""Hand-built DER, for the key shapes `openssl` will not produce.

Real keys come from `openssl genrsa`. Two things it cannot give are written out by
hand instead: the structures a key parser must *refuse* — a modulus too small to pad, a
length field wider than an integer, a value claiming more bytes than there are — and a
parseable non-key that reaches the signer without being a real pair. Both encode the
same subtle tag, length and integer rules, so they encode them in one place: two copies
of this drift apart silently, and the drift shows up as a test passing for the wrong
reason.
"""

from __future__ import annotations

import base64


def der(tag: int, value: bytes) -> bytes:
    """One tag-length-value triple, in DER's long length form once the value needs it."""
    if len(value) < 0x80:
        return bytes([tag, len(value)]) + value
    length = len(value).to_bytes((len(value).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(length)]) + length + value


def der_integer(value: int) -> bytes:
    """A DER INTEGER, always with a spare leading byte so nothing reads as negative."""
    return der(0x02, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big"))


def as_pem(label: str, body: bytes) -> str:
    """DER wrapped in the armour a PEM reader looks for."""
    encoded = base64.encodebytes(body).decode()
    return f"-----BEGIN {label}-----\n{encoded}-----END {label}-----\n"
