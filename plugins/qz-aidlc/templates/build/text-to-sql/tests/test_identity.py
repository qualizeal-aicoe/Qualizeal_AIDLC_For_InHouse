"""Go-live gate 1: who is asking comes from the identity provider, never from the request body. Offline: a test key
(numbers only, made for these tests) signs the tokens, and the provider's published keys are passed in."""
import base64
import hashlib
import json
import time

import http.client
import threading

import pytest

from sqlagent import config, identity  # noqa: E402
from sqlagent.graph import Agent  # noqa: E402
from sqlagent.web import make_server  # noqa: E402

N = int((
    "bef010cab34d6fdc710c4769e7bbb0d918c7dd0577a958611b92fe4bb8b4b3f82827ffb1a9d6e0fefe1c4288ba7e7caf3f3b"
    "ce927097521dc7b893396f2c7bc1605d6f67015ef6717a3a52e966ba6ecc0e9dde645c5c1332cc07d86559e1d8d4c4031f87"
    "9fc1a56256f9987a8cf326e14ee0a9c16a5324cbb062e2d438446597b44d12c500c3494a3576276bf20ad710445a9f525531"
    "6a16ecf76de633fc0fc618d135296acfc8cd39f28fdf1de8d8e83de0679a9d8352bbdc6225af3fc25e5b5c3cb53dc49b98ea"
    "484870d83042df0d8db9447f39f9f96175b4132647c873ebbf585ad1f9413b9c074a2ae014faaa12902b591d2c5cb67f063f"
    "ad49d9f1cfbb"
), 16)
D = int((
    "59ce7e8768a86e89c7de57a4976b6f75dd32fc613af43aee89d2acab1ef85781cc196c29bb51a748286b505c1123b72f9255"
    "6606f8d023be8016efa05f0b14365345ff44fa9f18d92cfd4bcc1e166850b03b4ec3f3b117129866c4407f733bd26f536cbc"
    "14c7372bb6eef4ea076bc288ccd9dcde6d4d280c6a2d48b53ab5e8f60eb982016e4b778101957823228bbfe7f569bfb06f60"
    "6a742c25c10fb558f32b3c2ada62030982072fc0628d8ef6edd39cc920d7c52d20ff74b9606c4ff3aeabcee584a1accf03b4"
    "564ea1182f06efc2028a0ce808005ef9d85fa959b76f063e056a75c95d141eddbbc83bc7917329ae0d825f60454965c48c94"
    "16891d592b61"
), 16)
ISSUER, AUDIENCE = "https://login.example.org/tenant/v2.0", "api://data-desk"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


KEYS = [{"kty": "RSA", "kid": "k1", "use": "sig", "n": b64(N.to_bytes(256, "big")), "e": b64((65537).to_bytes(3, "big"))}]
CONF = {"mode": "oidc", "issuer": ISSUER, "audience": AUDIENCE, "group_map": {"g-hr": ["all", "hr"]}}


def token(claims: dict, kid: str = "k1", alg: str = "RS256") -> str:
    h = b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    b = b64(json.dumps(claims).encode())
    em = b"\x00\x01" + b"\xff" * (256 - 3 - 19 - 32) + b"\x00" + identity.SHA256_INFO + hashlib.sha256(f"{h}.{b}".encode()).digest()
    return f"{h}.{b}.{b64(pow(int.from_bytes(em, 'big'), D, N).to_bytes(256, 'big'))}"


def claims(**kw) -> dict:
    now = int(time.time())
    return {"iss": ISSUER, "aud": AUDIENCE, "exp": now + 600, "nbf": now - 10, "preferred_username": "asha@example.org",
            "groups": ["g-hr"], **kw}


def test_a_signed_token_names_the_person_and_their_groups():
    w = identity.who(CONF, {"Authorization": "Bearer " + token(claims())}, "10.0.0.5", keys=KEYS)
    assert (w.user, w.groups, w.via) == ("asha@example.org", ["all", "hr"], "oidc")


@pytest.mark.parametrize("bad", ["expired", "issuer", "audience", "tampered", "alg", "unknown key", "no token"])
def test_anything_else_is_refused(bad):
    t = {"expired": token(claims(exp=int(time.time()) - 3600)), "issuer": token(claims(iss="https://elsewhere.example")),
         "audience": token(claims(aud="api://another-app")), "alg": token(claims(), alg="HS256"),
         "unknown key": token(claims(), kid="k2")}.get(bad)
    if bad == "tampered":
        h, _, s = token(claims()).split(".")
        t = ".".join([h, b64(json.dumps(claims(groups=["g-admin"])).encode()), s])
    with pytest.raises(identity.Refused):
        identity.who(CONF, {"Authorization": "Bearer " + t} if t else {}, "10.0.0.5", keys=KEYS)


def test_proxy_headers_count_only_from_the_proxy():
    conf = {"mode": "proxy", "trusted_proxies": ["10.1.0.0/24"]}
    hdr = {"X-Forwarded-Email": "asha@example.org", "X-Forwarded-Groups": "all,hr"}
    assert identity.who(conf, hdr, "10.1.0.7").groups == ["all", "hr"]
    with pytest.raises(identity.Refused):
        identity.who(conf, hdr, "203.0.113.9")
    principal = base64.b64encode(json.dumps({"claims": [{"typ": "name", "val": "asha@example.org"}, {"typ": "roles", "val": "hr"}]}).encode()).decode()
    assert identity.who(conf, {"X-MS-CLIENT-PRINCIPAL": principal}, "10.1.0.8").groups == ["hr"]


def test_demo_users_are_refused_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(identity.Refused):
        identity.who({"mode": "demo"}, {}, "127.0.0.1", "employee", ["all"])



@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLAGENT_HOME", str(tmp_path))
    monkeypatch.setenv("SQLAGENT_DB", str(tmp_path / "northwind.db"))
    return Agent(config.load())


def test_the_page_takes_the_role_from_the_identity_provider(agent):
    agent.cfg["identity"] = {**agent.cfg["identity"], "mode": "proxy", "trusted_proxies": ["127.0.0.1/32"]}
    srv = make_server(agent, 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def ask(headers: dict) -> tuple[int, dict]:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        c.request("POST", "/api/ask", body=json.dumps({"question": "How many customers do we have?"}),
                  headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **headers})
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8"))
    try:
        status, body = ask({"X-Forwarded-Email": "asha@example.org", "X-Forwarded-Groups": "everyone,support"})
        assert status == 200 and body["role"] == "support" and body["answer"] == "Customers: 30."
        assert ask({"X-Forwarded-Email": "asha@example.org", "X-Forwarded-Groups": "everyone"})[0] == 403
        assert ask({})[0] == 401
        audit = [json.loads(x) for x in (open(agent.cfg["store"]["audit"], encoding="utf-8").read().splitlines())]
        assert audit[-1]["actor"] == "asha@example.org" and audit[-1]["role"] == "support"
    finally:
        srv.shutdown()
        srv.server_close()
