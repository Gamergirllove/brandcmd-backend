"""
pkce.py — PKCE (Proof Key for Code Exchange) helpers for OAuth 2.0 flows.

Used by Twitter (X) and TikTok which require PKCE.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re


def generate_code_verifier(length: int = 64) -> str:
    """
    Generate a cryptographically random code verifier.

    The verifier is a high-entropy random string of unreserved URL characters:
    [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"

    Args:
        length: Number of random bytes to use as entropy (default 64).
                The resulting base64url string will be ~86 characters.

    Returns:
        A URL-safe base64-encoded string with no padding.
    """
    raw = os.urandom(length)
    verifier = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    # Trim to a max of 128 chars (RFC 7636 allows 43–128 chars)
    return verifier[:128]


def generate_code_challenge(verifier: str) -> str:
    """
    Derive the S256 code challenge from a code verifier.

    challenge = BASE64URL(SHA256(ASCII(verifier)))

    Args:
        verifier: The plain code verifier string.

    Returns:
        A URL-safe base64-encoded SHA-256 digest with no padding.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return challenge


def validate_verifier(verifier: str) -> bool:
    """
    Verify that a code verifier meets RFC 7636 requirements.

    Returns True if valid, False otherwise.
    """
    pattern = r"^[A-Za-z0-9\-._~]{43,128}$"
    return bool(re.match(pattern, verifier))
