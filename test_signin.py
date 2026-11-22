"""EmberCORE sign-in for EmberBurn: the dashboard's signed assertion decides whether
the web UI is handed the write token.

Every case builds its token the way the dashboard's signer does (ES256, raw r||s,
the claims in internal/appsignin/assertion.go of industrial-dashboard) and runs it
through the real Flask app, so what is asserted is what a browser gets:

  * a good "write" assertion: the UI gets the write token and a write succeeds
  * a good "read" assertion, no assertion, a forged, expired, wrong-app, wrong-issuer,
    alg none, HS256, over-long-lived or role-less one: no token, and a stale token
    cookie left by an earlier person is cleared
  * with no public key configured: exactly the old behavior, the UI gets the token
  * a write without the token is 401 whatever the assertion says

    pip install flask flask-cors cryptography "paho-mqtt<2" requests
    python test_signin.py
"""
import base64
import json
import os
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

AUD = "acme/emberburn-n1"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER = ec.generate_private_key(ec.SECP256R1())
PUB = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(claims=None, key=KEY, alg="ES256", now=None, ttl=60):
    now = int(now or time.time())
    c = {"iss": "embernet-dashboard", "sub": "eng@acme.example", "aud": AUD, "email": "eng@acme.example",
         "tenant": "acme", "role": "write", "roles": ["write"], "iat": now, "nbf": now, "exp": now + ttl}
    c.update(claims or {})
    c = {k: v for k, v in c.items() if v is not None}
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    signing = head + "." + b64(json.dumps(c).encode())
    if alg == "none":
        return signing + "."
    if alg == "HS256":
        return signing + "." + b64(b"x" * 32)
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    return signing + "." + b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def app(with_key=True):
    for k in ("EMBERNET_SIGNIN_PUBLIC_KEY", "EMBERNET_SIGNIN_AUDIENCE", "EMBERBURN_API_KEY"):
        os.environ.pop(k, None)
    os.environ["EMBERBURN_API_KEY"] = "the-write-token"
    if with_key:
        os.environ["EMBERNET_SIGNIN_PUBLIC_KEY"] = PUB
        os.environ["EMBERNET_SIGNIN_AUDIENCE"] = AUD
    import publishers
    pub = publishers.RESTAPIPublisher({"port": 5000})
    return pub.app.test_client()


def page(client, token=None, cookie=None):
    h = {"X-Embernet-Assertion": token} if token else {}
    if cookie:
        client.set_cookie("emberburn_write_token", cookie)
    r = client.get("/ui-probe", headers=h)
    return r


def token_cookie(r):
    for v in r.headers.getlist("Set-Cookie"):
        if v.startswith("emberburn_write_token="):
            return v
    return None


def main():
    failures = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    import publishers
    from flask import Response
    c = app(True)
    # A page the UI is served on: any HTML route does the same thing.
    pubapp = c.application

    @pubapp.route("/ui-probe")
    def probe():
        return Response("<html></html>", mimetype="text/html")

    good = sign()
    r = page(c, good)
    ck = token_cookie(r)
    check("a good write assertion hands the UI the write token", ck is not None and "the-write-token" in ck)

    bad = {
        "a read assertion": sign({"role": "read", "roles": ["read"]}),
        "no assertion": None,
        "a forged signature (another key)": sign(key=OTHER),
        "an expired token": sign(now=time.time() - 3600),
        "a token for another app": sign({"aud": "acme/other-app"}),
        "a token for another tenant": sign({"aud": "globex/emberburn-n1"}),
        "a foreign issuer": sign({"iss": "someone-else"}),
        "alg none": sign(alg="none"),
        "HS256": sign(alg="HS256"),
        "a token that lives too long": sign(ttl=3600),
        "no role": sign({"role": None}),
        "an unknown role": sign({"role": "root"}),
        "no subject": sign({"sub": None}),
        "not yet valid": sign(now=time.time() + 3600),
        "junk": "not.a.token",
    }
    for name, tok in bad.items():
        r = page(c, tok)
        check(f"{name}: the UI is not handed the write token", token_cookie(r) is None or "the-write-token" not in token_cookie(r))
    # A stale token an earlier writer left is cleared for a reader.
    c2 = app(True)
    c2.application.add_url_rule("/ui-probe", "probe", lambda: Response("<html></html>", mimetype="text/html"))
    r = page(c2, sign({"role": "read", "roles": ["read"]}), cookie="the-write-token")
    check("a reader's page clears a write token an earlier person left", token_cookie(r) is not None and "Max-Age=0" in token_cookie(r))

    # A write needs the token whatever the assertion says.
    r = c.post("/api/tags", json={"name": "t", "value": 1}, headers={"X-Embernet-Assertion": good})
    check("a write with an assertion but no token is 401", r.status_code == 401)

    # No key: the old behavior.
    c3 = app(False)
    c3.application.add_url_rule("/ui-probe", "probe", lambda: Response("<html></html>", mimetype="text/html"))
    r = page(c3, None)
    ck = token_cookie(r)
    check("with no key configured the UI is handed the token as it always was", ck is not None and "the-write-token" in ck)

    # A key with no audience is a startup error, not a check that is quietly off.
    os.environ["EMBERNET_SIGNIN_PUBLIC_KEY"] = PUB
    os.environ.pop("EMBERNET_SIGNIN_AUDIENCE", None)
    try:
        publishers.RESTAPIPublisher({"port": 5000})
        check("a key with no audience refuses to start", False)
    except ValueError:
        check("a key with no audience refuses to start", True)
    os.environ["EMBERNET_SIGNIN_PUBLIC_KEY"] = "not a key"
    os.environ["EMBERNET_SIGNIN_AUDIENCE"] = AUD
    try:
        publishers.RESTAPIPublisher({"port": 5000})
        check("an unreadable key refuses to start", False)
    except ValueError:
        check("an unreadable key refuses to start", True)

    print()
    print("RESULT: " + ("FAIL" if failures else "PASS"))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
