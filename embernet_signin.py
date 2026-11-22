"""
EmberCORE sign-in for EmberBurn (Wave 5 of the store-app sign-in plan).

A person who opens EmberBurn from the EmberCORE dashboard arrives with
X-Embernet-Assertion on every request: an ES256 token, good for about a minute,
signed with a private key only the dashboard holds. It names the person, the one
app it was made for (aud, "<tenant>/<Service name>") and the role the tenant maps
their dashboard role to: "write" or "read". EmberBurn checks it with the
dashboard's public key and lets the web UI write only for a person it says may.

Off unless a public key is configured (EMBERNET_SIGNIN_PUBLIC_KEY). With no key,
EmberBurn behaves exactly as before: the UI is handed the write token.

What a good assertion does: its role decides whether the UI is handed the write
token. What a bad one, a missing one, or one for another app does: the UI is
read-only, never an error, so a dashboard that has not been told about this app
cannot lock anyone out of reading it. Automation that holds EMBERBURN_API_KEY
writes as it always did; the assertion only decides what the browser UI may do.
"""
import base64
import json
import logging
import os
import time
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ISSUER = "embernet-dashboard"
HEADER = "X-Embernet-Assertion"
# The dashboard's tokens live a minute; anything that claims more than this was
# not made by it.
MAX_LIFETIME_SECONDS = 600
LEEWAY_SECONDS = 5
WRITE_ROLE = "write"
READ_ROLE = "read"

log = logging.getLogger(__name__)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Verifier:
    """Checks the dashboard's assertions for one app in one tenant."""

    def __init__(self, public_key_pem: str, audience: str, issuer: str = ISSUER, header: str = HEADER):
        key = serialization.load_pem_public_key(public_key_pem.strip().encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
            raise ValueError("the dashboard's public key must be ECDSA P-256")
        if not audience:
            raise ValueError("an audience is required with a public key")
        self._key = key
        self.audience = audience
        self.issuer = issuer
        self.header = header

    def verify(self, token: str, now: Optional[float] = None) -> Optional[dict]:
        """The token's claims, or None for anything that is not good."""
        try:
            parts = (token or "").split(".")
            if len(parts) != 3:
                return None
            if json.loads(_b64d(parts[0])).get("alg") != "ES256":
                return None
            sig = _b64d(parts[2])
            if len(sig) != 64:
                return None
            r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
            self._key.verify(encode_dss_signature(r, s), (parts[0] + "." + parts[1]).encode(),
                             ec.ECDSA(hashes.SHA256()))
            c = json.loads(_b64d(parts[1]))
            now = time.time() if now is None else now
            if c.get("iss") != self.issuer or not c.get("sub") or c.get("aud") != self.audience:
                return None
            exp, nbf = float(c.get("exp", 0)), float(c.get("nbf", 0))
            if now + LEEWAY_SECONDS < nbf or now - LEEWAY_SECONDS >= exp:
                return None
            if exp - nbf > MAX_LIFETIME_SECONDS:
                return None
            return c
        except (InvalidSignature, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def may_write(self, token: str, now: Optional[float] = None) -> bool:
        """True only for a good assertion whose role is "write"."""
        c = self.verify(token, now)
        return bool(c) and c.get("role") == WRITE_ROLE


def from_env() -> Optional[Verifier]:
    """A Verifier from the environment, or None when sign-in is off."""
    pem = os.getenv("EMBERNET_SIGNIN_PUBLIC_KEY", "").strip()
    if not pem:
        return None
    return Verifier(
        pem,
        os.getenv("EMBERNET_SIGNIN_AUDIENCE", "").strip(),
        os.getenv("EMBERNET_SIGNIN_ISSUER", ISSUER).strip() or ISSUER,
        os.getenv("EMBERNET_SIGNIN_HEADER", HEADER).strip() or HEADER,
    )
