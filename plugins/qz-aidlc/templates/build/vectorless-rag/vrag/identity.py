"""Go-live gate 1, single sign-on: who is asking comes from the client's identity provider, never from the request body.

The [identity] settings choose how:
  demo   a laptop demo: the page picks a demo user. Refused when APP_ENV or ENVIRONMENT says production.
  oidc   the caller sends the identity provider's access token (Authorization: Bearer ...). It is checked here, on the
         standard library: an RS256 signature by one of the provider's published keys (jwks_url), the issuer, the
         audience, expiry and not-before. The groups claim names the person's groups.
  proxy  an identity-aware proxy signs people in (oauth2-proxy, Azure App Service authentication, Cloud Run IAP, an AWS
         load balancer with OIDC) and passes who they are in headers. They are trusted only from the proxy's own
         addresses (trusted_proxies); from anywhere else the request is refused.
A SAML identity provider signs people in through its own OIDC side, or a broker such as Keycloak. Groups are read on
every request, so a person removed in the identity provider loses access at once: the app keeps no accounts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field

SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")     # DER prefix of a SHA-256 DigestInfo
LEEWAY_S = 60
MIN_BITS = 2048
PRODUCTION = ("prod", "production", "prd", "live")


class Refused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Who:
    user: str
    groups: list[str] = field(default_factory=list)
    via: str = "demo"


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


_KEYS: dict[str, tuple[float, list[dict]]] = {}
_LOCK = threading.Lock()


def jwks(url: str, ttl_s: int = 3600) -> list[dict]:
    """The identity provider's signing keys, fetched over HTTPS and kept for an hour."""
    with _LOCK:
        hit = _KEYS.get(url)
        if hit and time.time() - hit[0] < ttl_s:
            return hit[1]
    if not url.startswith("https://"):
        raise Refused(500, "[identity] jwks_url must be an https:// address")
    with urllib.request.urlopen(url, timeout=10) as r:     # noqa: S310  https only, checked above
        keys = json.loads(r.read(1_000_000)).get("keys", [])
    with _LOCK:
        _KEYS[url] = (time.time(), keys)
    return keys


def verify_rs256(token: str, keys: list[dict]) -> dict:
    """The claims of a JWT signed with RS256 by one of `keys` (a JWKS keys list). Anything else is refused."""
    try:
        h64, b64, s64 = token.split(".")
        head, claims, sig = json.loads(_b64(h64)), json.loads(_b64(b64)), _int(_b64(s64))
    except ValueError:
        raise Refused(401, "the token is not a JWT") from None
    if head.get("alg") != "RS256":
        raise Refused(401, "only RS256 tokens are accepted")
    digest = hashlib.sha256(f"{h64}.{b64}".encode("ascii")).digest()
    for k in keys:
        if k.get("kty") != "RSA" or k.get("use", "sig") != "sig" or (head.get("kid") and k.get("kid") != head.get("kid")):
            continue
        n, e = _int(_b64(k["n"])), _int(_b64(k["e"]))
        if n.bit_length() < MIN_BITS or not 0 < sig < n:
            continue
        size = (n.bit_length() + 7) // 8
        expected = b"\x00\x01" + b"\xff" * (size - 3 - len(SHA256_INFO) - len(digest)) + b"\x00" + SHA256_INFO + digest
        if hmac.compare_digest(pow(sig, e, n).to_bytes(size, "big"), expected):     # the whole block, not a parse
            return claims
    raise Refused(401, "the token's signature does not match the identity provider's keys")


def check_claims(claims: dict, issuer: str, audience: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    if not issuer or claims.get("iss") != issuer:
        raise Refused(401, "the token is from another issuer")
    aud = claims.get("aud")
    if not audience or audience not in (aud if isinstance(aud, list) else [aud]):
        raise Refused(401, "the token is for another audience")
    exp, nbf = claims.get("exp"), claims.get("nbf")
    if not isinstance(exp, (int, float)) or exp + LEEWAY_S < now:
        raise Refused(401, "the token has expired")
    if isinstance(nbf, (int, float)) and nbf - LEEWAY_S > now:
        raise Refused(401, "the token is not valid yet")


def _groups(raw, group_map: dict) -> list[str]:
    names = [str(g).strip() for g in (raw if isinstance(raw, list) else str(raw or "").split(",")) if str(g).strip()]
    if not group_map:
        return names
    out: list[str] = []
    for g in names:
        mapped = group_map.get(g)
        for m in ([mapped] if isinstance(mapped, str) else mapped or []):
            if m not in out:
                out.append(m)
    return out


def _trusted(addr: str, nets: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        return any(ip in ipaddress.ip_network(str(n), strict=False) for n in nets)
    except ValueError:
        return False


def _principal(header: str) -> tuple[str, list[str]]:
    """Azure App Service authentication's X-MS-CLIENT-PRINCIPAL: base64 JSON with the token's claims."""
    p = json.loads(base64.b64decode(header))
    claims = p.get("claims") or []
    name_typ, role_typ = p.get("name_typ") or "name", p.get("role_typ") or "roles"
    user = next((c.get("val") for c in claims if c.get("typ") in (name_typ, "preferred_username", "email")), "")
    return str(user or ""), [str(c.get("val")) for c in claims if c.get("typ") in (role_typ, "groups", "roles") and c.get("val")]


def who(conf: dict, headers, client: str, demo_user: str = "", demo_groups=None, keys=None, now: float | None = None) -> Who:
    """Who is asking. conf is the [identity] settings, headers the request's headers, client the caller's address."""
    mode = str(conf.get("mode") or "demo").lower()
    if mode == "demo":
        if (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").lower() in PRODUCTION:
            raise Refused(503, "demo identities are off in production: set [identity] mode to oidc or proxy")
        return Who(demo_user, list(demo_groups or []), "demo")
    gmap = conf.get("group_map") or {}
    if mode == "oidc":
        auth = headers.get("Authorization") or ""
        if not auth.startswith("Bearer "):
            raise Refused(401, "sign in first: send the identity provider's token (Authorization: Bearer ...)")
        claims = verify_rs256(auth[7:].strip(), keys if keys is not None else jwks(str(conf.get("jwks_url") or "")))
        check_claims(claims, str(conf.get("issuer") or ""), str(conf.get("audience") or ""), now)
        user = str(claims.get("preferred_username") or claims.get("email") or claims.get("upn") or claims.get("sub") or "")
        if not user:
            raise Refused(401, "the token does not say who is asking")
        return Who(user, _groups(claims.get(conf.get("groups_claim") or "groups"), gmap), "oidc")
    if mode == "proxy":
        if not _trusted(client, list(conf.get("trusted_proxies") or [])):
            raise Refused(403, "identity headers are accepted only from the identity-aware proxy")
        if headers.get("X-MS-CLIENT-PRINCIPAL"):
            user, groups = _principal(headers.get("X-MS-CLIENT-PRINCIPAL"))
        else:
            user = (headers.get("X-Forwarded-Email") or headers.get("X-Auth-Request-Email") or headers.get("X-Forwarded-User")
                    or headers.get("X-Auth-Request-User") or "")
            groups = headers.get("X-Forwarded-Groups") or headers.get("X-Auth-Request-Groups") or ""
        if not user:
            raise Refused(401, "the proxy did not say who is asking")
        return Who(str(user), _groups(groups, gmap), "proxy")
    raise Refused(500, f"unknown [identity] mode {mode!r}: demo, oidc or proxy")
