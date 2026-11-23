/**
 * Go-live gate 1, single sign-on: who is asking comes from the client's identity provider, never from the request body.
 *
 * AGENT_IDENTITY chooses how:
 *   demo   a laptop demo: the caller names a demo user (X-Demo-User). Refused when APP_ENV or ENVIRONMENT says production.
 *   oidc   the caller sends the identity provider's access token (Authorization: Bearer ...). It is checked here, with
 *          Node's own crypto: an RS256 signature by one of the provider's published keys (AGENT_OIDC_JWKS_URL), the
 *          issuer (AGENT_OIDC_ISSUER), the audience (AGENT_OIDC_AUDIENCE), expiry and not-before. The groups claim
 *          (AGENT_GROUPS_CLAIM, default groups) names the person's groups.
 *   proxy  an identity-aware proxy signs people in (oauth2-proxy, Azure App Service authentication, Cloud Run IAP, an AWS
 *          load balancer with OIDC) and passes who they are in headers, trusted only from the proxy's own addresses
 *          (AGENT_TRUSTED_PROXIES); from anywhere else the request is refused.
 * Groups are read on every request, so a person removed in the identity provider loses access at once.
 */
import { createPublicKey, verify, type webcrypto } from "node:crypto";
import { BlockList, isIPv6 } from "node:net";

type JsonWebKey = webcrypto.JsonWebKey & { kid?: string };   // a JWKS entry names its key (kid)

export class Refused extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
export type Who = { user: string; groups: string[]; via: string };
const LEEWAY_S = 60;
const PRODUCTION = new Set(["prod", "production", "prd", "live"]);
let cache: { url: string; at: number; keys: JsonWebKey[] } | null = null;

const b64 = (s: string): Buffer => Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");

export async function jwks(url: string, ttlMs = 3_600_000): Promise<JsonWebKey[]> {
  if (cache && cache.url === url && Date.now() - cache.at < ttlMs) return cache.keys;
  if (!url.startsWith("https://")) throw new Refused(500, "AGENT_OIDC_JWKS_URL must be an https:// address");
  const r = await fetch(url, { signal: AbortSignal.timeout(10_000) });
  const keys = ((await r.json()) as { keys?: JsonWebKey[] }).keys ?? [];
  cache = { url, at: Date.now(), keys };
  return keys;
}

/** The claims of a JWT signed with RS256 by one of `keys` (a JWKS keys list). Anything else is refused. */
export function verifyRs256(token: string, keys: JsonWebKey[]): Record<string, any> {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Refused(401, "the token is not a JWT");
  let head: Record<string, any>, claims: Record<string, any>;
  try {
    head = JSON.parse(b64(parts[0]).toString("utf8"));
    claims = JSON.parse(b64(parts[1]).toString("utf8"));
  } catch {
    throw new Refused(401, "the token is not a JWT");
  }
  if (head.alg !== "RS256") throw new Refused(401, "only RS256 tokens are accepted");
  for (const k of keys) {
    if (k.kty !== "RSA" || (k.use ?? "sig") !== "sig" || (head.kid && k.kid !== head.kid)) continue;
    const key = createPublicKey({ key: k, format: "jwk" });
    if ((key.asymmetricKeyDetails?.modulusLength ?? 0) < 2048) continue;
    if (verify("RSA-SHA256", Buffer.from(`${parts[0]}.${parts[1]}`), key, b64(parts[2]))) return claims;
  }
  throw new Refused(401, "the token's signature does not match the identity provider's keys");
}

export function checkClaims(claims: Record<string, any>, issuer: string, audience: string, now = Date.now() / 1000): void {
  if (!issuer || claims.iss !== issuer) throw new Refused(401, "the token is from another issuer");
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!audience || !aud.includes(audience)) throw new Refused(401, "the token is for another audience");
  if (typeof claims.exp !== "number" || claims.exp + LEEWAY_S < now) throw new Refused(401, "the token has expired");
  if (typeof claims.nbf === "number" && claims.nbf - LEEWAY_S > now) throw new Refused(401, "the token is not valid yet");
}

function groupsOf(raw: unknown): string[] {
  return (Array.isArray(raw) ? raw : String(raw ?? "").split(",")).map((g) => String(g).trim()).filter(Boolean);
}

function trusted(addr: string, nets: string[]): boolean {
  const ip = addr.replace(/^::ffff:/, "");
  const list = new BlockList();
  for (const n of nets) {
    const [net, bits] = n.split("/");
    try {
      list.addSubnet(net, Number(bits ?? (isIPv6(net) ? 128 : 32)), isIPv6(net) ? "ipv6" : "ipv4");
    } catch { /* a malformed entry trusts nothing */ }
  }
  return list.check(ip, isIPv6(ip) ? "ipv6" : "ipv4");
}

/** Azure App Service authentication's X-MS-CLIENT-PRINCIPAL: base64 JSON with the token's claims. */
function principal(header: string): { user: string; groups: string[] } {
  try {
    const p = JSON.parse(Buffer.from(header, "base64").toString("utf8")) as { claims?: Array<{ typ?: string; val?: string }>; name_typ?: string; role_typ?: string };
    const claims = p.claims ?? [];
    const nameTyp = p.name_typ || "name";
    const roleTyp = p.role_typ || "roles";
    const user = claims.find((x) => [nameTyp, "preferred_username", "email"].includes(String(x.typ)))?.val ?? "";
    return { user: String(user), groups: claims.filter((x) => [roleTyp, "groups", "roles"].includes(String(x.typ)) && x.val).map((x) => String(x.val)) };
  } catch {
    throw new Refused(401, "the proxy's X-MS-CLIENT-PRINCIPAL is not readable");
  }
}

export type IdentityConf = { mode: string; issuer: string; audience: string; jwksUrl: string; groupsClaim: string; trustedProxies: string[] };

export function conf(): IdentityConf {
  const e = process.env;
  return { mode: (e.AGENT_IDENTITY ?? "demo").toLowerCase(), issuer: e.AGENT_OIDC_ISSUER ?? "", audience: e.AGENT_OIDC_AUDIENCE ?? "",
    jwksUrl: e.AGENT_OIDC_JWKS_URL ?? "", groupsClaim: e.AGENT_GROUPS_CLAIM ?? "groups",
    trustedProxies: (e.AGENT_TRUSTED_PROXIES ?? "127.0.0.1/32,::1/128").split(",").map((x) => x.trim()).filter(Boolean) };
}

/** Who is asking: headers are the request's headers (lower-case names), client the caller's address. */
export async function who(c: IdentityConf, headers: Record<string, string | string[] | undefined>, client: string,
                          demoUser = "", demoGroups: string[] = [], keys?: JsonWebKey[]): Promise<Who> {
  const h = (n: string): string => String(headers[n] ?? "");
  if (c.mode === "demo") {
    if (PRODUCTION.has((process.env.APP_ENV ?? process.env.ENVIRONMENT ?? "").toLowerCase()))
      throw new Refused(503, "demo identities are off in production: set AGENT_IDENTITY to oidc or proxy");
    return { user: demoUser, groups: demoGroups, via: "demo" };
  }
  if (c.mode === "oidc") {
    const auth = h("authorization");
    if (!auth.startsWith("Bearer ")) throw new Refused(401, "sign in first: send the identity provider's token (Authorization: Bearer ...)");
    const claims = verifyRs256(auth.slice(7).trim(), keys ?? await jwks(c.jwksUrl));
    checkClaims(claims, c.issuer, c.audience);
    const user = String(claims.preferred_username || claims.email || claims.upn || claims.sub || "");
    if (!user) throw new Refused(401, "the token does not say who is asking");
    return { user, groups: groupsOf(claims[c.groupsClaim]), via: "oidc" };
  }
  if (c.mode === "proxy") {
    if (!trusted(client, c.trustedProxies)) throw new Refused(403, "identity headers are accepted only from the identity-aware proxy");
    let user = "";
    let groups: string[] = [];
    if (h("x-ms-client-principal")) ({ user, groups } = principal(h("x-ms-client-principal")));
    else {
      user = h("x-forwarded-email") || h("x-auth-request-email") || h("x-forwarded-user") || h("x-auth-request-user");
      groups = groupsOf(h("x-forwarded-groups") || h("x-auth-request-groups"));
    }
    if (!user) throw new Refused(401, "the proxy did not say who is asking");
    return { user, groups, via: "proxy" };
  }
  throw new Refused(500, `unknown AGENT_IDENTITY ${c.mode}: demo, oidc or proxy`);
}
