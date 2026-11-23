package agent

import (
	"bytes"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"math/big"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// The HTTP interface, offline: ask, receive the pending approval, approve it over the API and get the result; nobody
// approves their own request; the waiting run survives a restart of the server; who asks comes from the identity
// provider, and a token is checked before it is believed.

func call(t *testing.T, base, method, path string, body any, user string) (int, map[string]any) {
	t.Helper()
	var r *bytes.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	} else {
		r = bytes.NewReader(nil)
	}
	req, _ := http.NewRequest(method, base+path, r)
	req.Header.Set("Content-Type", "application/json")
	if user != "" {
		req.Header.Set("X-Demo-User", user)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	out := map[string]any{}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

func serve(t *testing.T, keys []JWK) string {
	t.Helper()
	t.Setenv("AGENT_IDENTITY", "demo")
	srv := httptest.NewServer(NewServer(keys))
	t.Cleanup(srv.Close)
	return srv.URL
}

func TestAskWaitApproveOverTheAPI(t *testing.T) {
	fresh(t)
	base := serve(t, nil)
	if st, h := call(t, base, "GET", "/health", nil, ""); st != 200 || h["status"] != "ok" || h["waiting"] != float64(0) {
		t.Fatalf("health %d %v", st, h)
	}
	st, r := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk}, "sam")
	if st != 202 || r["awaiting_approval"] != true {
		t.Fatalf("ask %d %v", st, r)
	}
	thread, _ := r["thread_id"].(string)
	_, run := call(t, base, "GET", "/runs/"+thread, nil, "ana")
	waiting, _ := run["waiting_for"].([]any)
	if run["status"] != "awaiting_approval" || len(waiting) != 1 || waiting[0].(map[string]any)["name"] != "issue_refund" {
		t.Fatalf("run %v", run)
	}
	if _, h := call(t, base, "GET", "/health", nil, ""); h["waiting"] != float64(1) {
		t.Fatalf("health %v", h)
	}
	if st, _ := call(t, base, "POST", "/runs/"+thread+"/approve", nil, "sam"); st != 403 {
		t.Fatalf("sam is no approver: %d", st)
	}
	if st, _ := call(t, base, "POST", "/runs/"+thread+"/approve", nil, "vic"); st != 403 {
		t.Fatalf("vic is no approver: %d", st)
	}
	st, done := call(t, base, "POST", "/runs/"+thread+"/approve", nil, "ana")
	if st != 200 || done["outcome"] != "acted" || !strings.Contains(done["output"].(string), "RF-") || done["answered_by"] != "ana" {
		t.Fatalf("approve %d %v", st, done)
	}
	if st, _ := call(t, base, "POST", "/runs/"+thread+"/approve", nil, "ana"); st != 409 {
		t.Fatalf("a second answer: %d", st)
	}
	if _, run := call(t, base, "GET", "/runs/"+thread, nil, "ana"); run["status"] != "done" {
		t.Fatalf("run %v", run)
	}
}

func TestNobodyApprovesTheirOwnRequest(t *testing.T) {
	fresh(t)
	base := serve(t, nil)
	st, r := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk}, "ana")
	if st != 202 {
		t.Fatalf("ask %d", st)
	}
	st, e := call(t, base, "POST", "/runs/"+r["thread_id"].(string)+"/approve", nil, "ana")
	if st != 403 || !strings.Contains(e["error"].(string), "a request they made") {
		t.Fatalf("self approval %d %v", st, e)
	}
}

func TestAWaitingRunSurvivesARestartOfTheServer(t *testing.T) {
	fresh(t)
	_, r := call(t, serve(t, nil), "POST", "/ask", map[string]any{"message": refundAsk}, "sam")
	second := serve(t, nil)
	st, done := call(t, second, "POST", "/runs/"+r["thread_id"].(string)+"/decline", nil, "ana")
	if st != 200 || done["outcome"] != "declined" || strings.Contains(done["output"].(string), "RF-") {
		t.Fatalf("decline after a restart %d %v", st, done)
	}
}

func TestWhoAsksComesFromTheIdentityNotTheBody(t *testing.T) {
	fresh(t)
	base := serve(t, nil)
	if st, _ := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk}, ""); st != 401 {
		t.Fatalf("no identity: %d", st)
	}
	if st, _ := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk, "user": "ana", "role": "support"}, ""); st != 401 {
		t.Fatalf("an identity in the body: %d", st)
	}
	st, r := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk}, "vic")
	if st != 200 || !strings.Contains(r["output"].(string), "role does not have") {
		t.Fatalf("viewer %d %v", st, r)
	}
	if st, _ := call(t, base, "GET", "/runs/"+r["thread_id"].(string), nil, "sam"); st != 404 {
		t.Fatalf("another person's run: %d", st)
	}
	t.Setenv("APP_ENV", "production")
	if st, _ := call(t, base, "POST", "/ask", map[string]any{"message": refundAsk}, "sam"); st != 503 {
		t.Fatalf("demo identities in production: %d", st)
	}
	if st, _ := call(t, base, "GET", "/health", nil, ""); st != 200 {
		t.Fatalf("health needs no sign-in: %d", st)
	}
}

func signRS256(t *testing.T, key *rsa.PrivateKey, kid string, claims map[string]any) string {
	t.Helper()
	enc := base64.RawURLEncoding
	h, _ := json.Marshal(map[string]any{"alg": "RS256", "typ": "JWT", "kid": kid})
	c, _ := json.Marshal(claims)
	signing := enc.EncodeToString(h) + "." + enc.EncodeToString(c)
	sum := sha256.Sum256([]byte(signing))
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, sum[:])
	if err != nil {
		t.Fatal(err)
	}
	return signing + "." + enc.EncodeToString(sig)
}

func TestAnOIDCTokenIsCheckedBeforeItIsBelieved(t *testing.T) {
	fresh(t)
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	enc := base64.RawURLEncoding
	jwks := []JWK{{Kty: "RSA", Use: "sig", Kid: "k1", Alg: "RS256", N: enc.EncodeToString(key.N.Bytes()), E: enc.EncodeToString(big.NewInt(int64(key.E)).Bytes())}}
	srv := httptest.NewServer(NewServer(jwks))
	t.Cleanup(srv.Close)
	t.Setenv("AGENT_IDENTITY", "oidc")
	t.Setenv("AGENT_OIDC_ISSUER", "https://login.example.org")
	t.Setenv("AGENT_OIDC_AUDIENCE", "orders-agent")
	good := map[string]any{"iss": "https://login.example.org", "aud": "orders-agent", "exp": time.Now().Add(time.Hour).Unix(),
		"preferred_username": "asha@example.org", "groups": []string{"order-viewers"}}
	ask := func(token string) int {
		req, _ := http.NewRequest("POST", srv.URL+"/ask", strings.NewReader(`{"message": "Where is my order ORD-1001?"}`))
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp.StatusCode
	}
	if st := ask(signRS256(t, key, "k1", good)); st != 200 {
		t.Fatalf("a good token: %d", st)
	}
	other, _ := rsa.GenerateKey(rand.Reader, 2048)
	with := func(k string, v any) map[string]any {
		c := map[string]any{}
		for kk, vv := range good {
			c[kk] = vv
		}
		c[k] = v
		return c
	}
	for name, token := range map[string]string{
		"another key":      signRS256(t, other, "k1", good),
		"another audience": signRS256(t, key, "k1", with("aud", "someone-else")),
		"another issuer":   signRS256(t, key, "k1", with("iss", "https://evil.example.net")),
		"expired":          signRS256(t, key, "k1", with("exp", time.Now().Add(-time.Hour).Unix())),
		"no user":          signRS256(t, key, "k1", with("preferred_username", "")),
		"not a JWT":        "not-a-token",
		"HS256":            enc.EncodeToString([]byte(`{"alg":"HS256"}`)) + "." + enc.EncodeToString([]byte(`{}`)) + ".x",
	} {
		if st := ask(token); st != 401 {
			t.Fatalf("%s: %d", name, st)
		}
	}
	t.Setenv("AGENT_IDENTITY", "proxy")
	easyAuth := base64.StdEncoding.EncodeToString([]byte(`{"name_typ":"name","claims":[{"typ":"name","val":"ana"},{"typ":"groups","val":"order-support"}]}`))
	pr, _ := http.NewRequest("POST", srv.URL+"/ask", strings.NewReader(`{"message": "Where is my order ORD-1001?"}`))
	pr.Header.Set("X-MS-CLIENT-PRINCIPAL", easyAuth)
	presp, err := http.DefaultClient.Do(pr)
	if err != nil {
		t.Fatal(err)
	}
	presp.Body.Close()
	if presp.StatusCode != 200 {
		t.Fatalf("Azure App Service authentication from the proxy: %d", presp.StatusCode)
	}
	t.Setenv("AGENT_TRUSTED_PROXIES", "10.9.9.9/32")
	req, _ := http.NewRequest("POST", srv.URL+"/ask", strings.NewReader(`{"message": "Where is my order ORD-1001?"}`))
	req.Header.Set("X-Forwarded-Email", "ana")
	req.Header.Set("X-Forwarded-Groups", "order-support,refund-approvers")
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	if resp.StatusCode != 403 {
		t.Fatalf("identity headers from outside the proxy: %d", resp.StatusCode)
	}
}
