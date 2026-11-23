package agent

// Go-live gate 1, single sign-on: who is asking comes from the client's identity provider, never from the request body.
//
// AGENT_IDENTITY chooses how:
//
//	demo   a laptop demo: the caller names a demo user (X-Demo-User). Refused when APP_ENV or ENVIRONMENT says production.
//	oidc   the caller sends the identity provider's access token (Authorization: Bearer ...). It is checked here, with
//	       Go's own crypto/rsa: an RS256 signature by one of the provider's published keys (AGENT_OIDC_JWKS_URL), the
//	       issuer (AGENT_OIDC_ISSUER), the audience (AGENT_OIDC_AUDIENCE), expiry and not-before. The groups claim
//	       (AGENT_GROUPS_CLAIM, default groups) names the person's groups.
//	proxy  an identity-aware proxy signs people in (oauth2-proxy, Azure App Service authentication, Cloud Run IAP, an AWS
//	       load balancer with OIDC) and passes who they are in headers, trusted only from the proxy's own addresses
//	       (AGENT_TRUSTED_PROXIES); from anywhere else the request is refused.
//
// Groups are read on every request, so a person removed in the identity provider loses access at once.

import (
	"context"
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/netip"
	"os"
	"strings"
	"sync"
	"time"
)

// Refused is a request turned away, with the HTTP status that says why.
type Refused struct {
	Status int
	Reason string
}

func (e Refused) Error() string { return e.Reason }

// Caller is who is asking, as the identity provider says.
type Caller struct {
	User   string
	Groups []string
	Via    string
}

// JWK is one of the identity provider's published signing keys (an entry of its JWKS).
type JWK struct {
	Kty string `json:"kty"`
	Use string `json:"use"`
	Kid string `json:"kid"`
	Alg string `json:"alg"`
	N   string `json:"n"`
	E   string `json:"e"`
}

// Identity is how callers are identified: AGENT_IDENTITY with the AGENT_OIDC_* and AGENT_TRUSTED_PROXIES settings.
type Identity struct {
	Mode, Issuer, Audience, JWKSURL, GroupsClaim string
	TrustedProxies                               []string
}

const (
	leewaySeconds = 60   // clock difference allowed on exp and nbf
	minKeyBits    = 2048 // a shorter RSA key never verifies a token
)

var production = map[string]bool{"prod": true, "production": true, "prd": true, "live": true}

// IdentityFromEnv reads the settings.
func IdentityFromEnv() Identity {
	get := func(k, d string) string {
		if v := os.Getenv(k); v != "" {
			return v
		}
		return d
	}
	nets := []string{}
	for _, n := range strings.Split(get("AGENT_TRUSTED_PROXIES", "127.0.0.1/32,::1/128"), ",") {
		if n = strings.TrimSpace(n); n != "" {
			nets = append(nets, n)
		}
	}
	return Identity{Mode: strings.ToLower(get("AGENT_IDENTITY", "demo")), Issuer: os.Getenv("AGENT_OIDC_ISSUER"),
		Audience: os.Getenv("AGENT_OIDC_AUDIENCE"), JWKSURL: os.Getenv("AGENT_OIDC_JWKS_URL"), GroupsClaim: get("AGENT_GROUPS_CLAIM", "groups"),
		TrustedProxies: nets}
}

var jwksCache struct {
	sync.Mutex
	url  string
	at   time.Time
	keys []JWK
}

// FetchJWKS reads the identity provider's published keys, kept for an hour.
func FetchJWKS(ctx context.Context, url string) ([]JWK, error) {
	jwksCache.Lock()
	defer jwksCache.Unlock()
	if jwksCache.url == url && time.Since(jwksCache.at) < time.Hour {
		return jwksCache.keys, nil
	}
	if !strings.HasPrefix(url, "https://") {
		return nil, Refused{500, "AGENT_OIDC_JWKS_URL must be an https:// address"}
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("the identity provider's keys answered %d", resp.StatusCode)
	}
	var set struct {
		Keys []JWK `json:"keys"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&set); err != nil {
		return nil, err
	}
	jwksCache.url, jwksCache.at, jwksCache.keys = url, time.Now(), set.Keys
	return set.Keys, nil
}

func b64(s string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(strings.TrimRight(s, "="))
}

func (k JWK) publicKey() (*rsa.PublicKey, error) {
	n, err := b64(k.N)
	if err != nil {
		return nil, err
	}
	e, err := b64(k.E)
	if err != nil {
		return nil, err
	}
	exp := new(big.Int).SetBytes(e)
	if !exp.IsInt64() || exp.Int64() < 3 || exp.Int64() > 1<<31-1 {
		return nil, errors.New("the key's exponent is out of range")
	}
	return &rsa.PublicKey{N: new(big.Int).SetBytes(n), E: int(exp.Int64())}, nil
}

// VerifyRS256 returns the claims of a JWT signed with RS256 by one of keys (a JWKS keys list). Anything else is refused.
func VerifyRS256(token string, keys []JWK) (map[string]any, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, Refused{401, "the token is not a JWT"}
	}
	var head, claims map[string]any
	hb, err1 := b64(parts[0])
	cb, err2 := b64(parts[1])
	sig, err3 := b64(parts[2])
	if err1 != nil || err2 != nil || err3 != nil || json.Unmarshal(hb, &head) != nil || json.Unmarshal(cb, &claims) != nil {
		return nil, Refused{401, "the token is not a JWT"}
	}
	if alg, _ := head["alg"].(string); alg != "RS256" {
		return nil, Refused{401, "only RS256 tokens are accepted"}
	}
	kid, _ := head["kid"].(string)
	sum := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	for _, k := range keys {
		if k.Kty != "RSA" || (k.Use != "" && k.Use != "sig") || (kid != "" && k.Kid != kid) {
			continue
		}
		pub, err := k.publicKey()
		if err != nil || pub.N.BitLen() < minKeyBits {
			continue
		}
		if rsa.VerifyPKCS1v15(pub, crypto.SHA256, sum[:], sig) == nil {
			return claims, nil
		}
	}
	return nil, Refused{401, "the token's signature does not match the identity provider's keys"}
}

// CheckClaims refuses a token from another issuer, for another audience, expired, or not valid yet.
func CheckClaims(claims map[string]any, issuer, audience string, at time.Time) error {
	if iss, _ := claims["iss"].(string); issuer == "" || iss != issuer {
		return Refused{401, "the token is from another issuer"}
	}
	aud := []any{claims["aud"]}
	if list, ok := claims["aud"].([]any); ok {
		aud = list
	}
	found := false
	for _, a := range aud {
		if s, _ := a.(string); audience != "" && s == audience {
			found = true
		}
	}
	if !found {
		return Refused{401, "the token is for another audience"}
	}
	t := float64(at.Unix())
	if exp, ok := claims["exp"].(float64); !ok || exp+leewaySeconds < t {
		return Refused{401, "the token has expired"}
	}
	if nbf, ok := claims["nbf"].(float64); ok && nbf-leewaySeconds > t {
		return Refused{401, "the token is not valid yet"}
	}
	return nil
}

func groupsOf(raw any) []string {
	var items []string
	switch v := raw.(type) {
	case []any:
		for _, g := range v {
			items = append(items, fmt.Sprint(g))
		}
	case string:
		items = strings.Split(v, ",")
	}
	out := []string{}
	for _, g := range items {
		if g = strings.TrimSpace(g); g != "" {
			out = append(out, g)
		}
	}
	return out
}

// principal reads Azure App Service authentication's X-MS-CLIENT-PRINCIPAL: base64 JSON with the token's claims.
func principal(header string) (string, []string, error) {
	b, err := base64.StdEncoding.DecodeString(header)
	if err != nil {
		return "", nil, err
	}
	var p struct {
		NameTyp string `json:"name_typ"`
		RoleTyp string `json:"role_typ"`
		Claims  []struct {
			Typ string `json:"typ"`
			Val string `json:"val"`
		} `json:"claims"`
	}
	if err := json.Unmarshal(b, &p); err != nil {
		return "", nil, err
	}
	if p.NameTyp == "" {
		p.NameTyp = "name"
	}
	if p.RoleTyp == "" {
		p.RoleTyp = "roles"
	}
	user, groups := "", []string{}
	for _, c := range p.Claims {
		switch {
		case user == "" && (c.Typ == p.NameTyp || c.Typ == "preferred_username" || c.Typ == "email"):
			user = c.Val
		case c.Val != "" && (c.Typ == p.RoleTyp || c.Typ == "groups" || c.Typ == "roles"):
			groups = append(groups, c.Val)
		}
	}
	return user, groups, nil
}

// trusted says whether remote (host:port, or a bare address) is inside one of nets.
func trusted(remote string, nets []string) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		host = remote
	}
	ip, err := netip.ParseAddr(host)
	if err != nil {
		return false
	}
	ip = ip.Unmap()
	for _, n := range nets {
		p, err := netip.ParsePrefix(n)
		if err != nil {
			a, err := netip.ParseAddr(n)
			if err != nil {
				continue // a malformed entry trusts nothing
			}
			p = netip.PrefixFrom(a, a.BitLen())
		}
		if p.Contains(ip) {
			return true
		}
	}
	return false
}

// Identify says who is asking. remote is the caller's address; keys, when given, stand in for the provider's
// published keys (tests).
func Identify(ctx context.Context, c Identity, h http.Header, remote, demoUser string, demoGroups []string, keys []JWK) (Caller, error) {
	switch c.Mode {
	case "demo":
		env := os.Getenv("APP_ENV")
		if env == "" {
			env = os.Getenv("ENVIRONMENT")
		}
		if production[strings.ToLower(env)] {
			return Caller{}, Refused{503, "demo identities are off in production: set AGENT_IDENTITY to oidc or proxy"}
		}
		return Caller{User: demoUser, Groups: demoGroups, Via: "demo"}, nil
	case "oidc":
		auth := h.Get("Authorization")
		if !strings.HasPrefix(auth, "Bearer ") {
			return Caller{}, Refused{401, "sign in first: send the identity provider's token (Authorization: Bearer ...)"}
		}
		if keys == nil {
			var err error
			if keys, err = FetchJWKS(ctx, c.JWKSURL); err != nil {
				var r Refused
				if errors.As(err, &r) {
					return Caller{}, r
				}
				return Caller{}, Refused{503, "the identity provider's keys could not be read"}
			}
		}
		claims, err := VerifyRS256(strings.TrimSpace(auth[len("Bearer "):]), keys)
		if err != nil {
			return Caller{}, err
		}
		if err := CheckClaims(claims, c.Issuer, c.Audience, time.Now()); err != nil {
			return Caller{}, err
		}
		user := ""
		for _, k := range []string{"preferred_username", "email", "upn", "sub"} {
			if s, _ := claims[k].(string); s != "" {
				user = s
				break
			}
		}
		if user == "" {
			return Caller{}, Refused{401, "the token does not say who is asking"}
		}
		return Caller{User: user, Groups: groupsOf(claims[c.GroupsClaim]), Via: "oidc"}, nil
	case "proxy":
		if !trusted(remote, c.TrustedProxies) {
			return Caller{}, Refused{403, "identity headers are accepted only from the identity-aware proxy"}
		}
		first := func(names ...string) string {
			for _, n := range names {
				if v := strings.TrimSpace(h.Get(n)); v != "" {
					return v
				}
			}
			return ""
		}
		var user string
		var groups []string
		if p := first("X-MS-CLIENT-PRINCIPAL"); p != "" {
			var err error
			if user, groups, err = principal(p); err != nil {
				return Caller{}, Refused{401, "the proxy's X-MS-CLIENT-PRINCIPAL is not readable"}
			}
		} else {
			user = first("X-Forwarded-Email", "X-Auth-Request-Email", "X-Forwarded-User", "X-Auth-Request-User")
			groups = groupsOf(first("X-Forwarded-Groups", "X-Auth-Request-Groups"))
		}
		if user == "" {
			return Caller{}, Refused{401, "the proxy did not say who is asking"}
		}
		return Caller{User: user, Groups: groups, Via: "proxy"}, nil
	}
	return Caller{}, Refused{500, "unknown AGENT_IDENTITY " + c.Mode + ": demo, oidc or proxy"}
}
