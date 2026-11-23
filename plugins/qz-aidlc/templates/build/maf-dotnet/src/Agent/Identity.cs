using System.Buffers.Text;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace OrderAgent;

/// <summary>A request turned away, with the HTTP status that says why.</summary>
public sealed class Refused(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}

/// <summary>Who is asking, as the identity provider says.</summary>
public sealed record Caller(string User, List<string> Groups, string Via);

/// <summary>One of the identity provider's published signing keys (an entry of its JWKS).</summary>
public sealed record Jwk(string? kty = null, string? use = null, string? kid = null, string? alg = null, string? n = null, string? e = null);

/// <summary>How callers are identified: AGENT_IDENTITY with the AGENT_OIDC_* and AGENT_TRUSTED_PROXIES settings.</summary>
public sealed record IdentityConf(string Mode, string Issuer, string Audience, string JwksUrl, string GroupsClaim, List<string> TrustedProxies)
{
    public static IdentityConf FromEnv()
    {
        static string Get(string k, string d = "") => Environment.GetEnvironmentVariable(k) is { Length: > 0 } v ? v : d;
        return new(Get("AGENT_IDENTITY", "demo").ToLowerInvariant(), Get("AGENT_OIDC_ISSUER"), Get("AGENT_OIDC_AUDIENCE"), Get("AGENT_OIDC_JWKS_URL"),
            Get("AGENT_GROUPS_CLAIM", "groups"), [.. Get("AGENT_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").Split(',').Select(x => x.Trim()).Where(x => x.Length > 0)]);
    }
}

/// <summary>
/// Go-live gate 1, single sign-on: who is asking comes from the client's identity provider, never from the request body.
///
/// AGENT_IDENTITY chooses how:
///   demo   a laptop demo: the caller names a demo user (X-Demo-User). Refused when APP_ENV or ENVIRONMENT says production.
///   oidc   the caller sends the identity provider's access token (Authorization: Bearer ...). It is checked here, with
///          .NET's own System.Security.Cryptography: an RS256 signature by one of the provider's published keys
///          (AGENT_OIDC_JWKS_URL), the issuer (AGENT_OIDC_ISSUER), the audience (AGENT_OIDC_AUDIENCE), expiry and
///          not-before. The groups claim (AGENT_GROUPS_CLAIM, default groups) names the person's groups.
///   proxy  an identity-aware proxy signs people in (oauth2-proxy, Azure App Service authentication, Cloud Run IAP, an AWS
///          load balancer with OIDC) and passes who they are in headers, trusted only from the proxy's own addresses
///          (AGENT_TRUSTED_PROXIES); from anywhere else the request is refused.
/// Groups are read on every request, so a person removed in the identity provider loses access at once.
/// </summary>
public static class Identity
{
    private const int LeewaySeconds = 60;
    private const int MinKeyBits = 2048;
    private static readonly HashSet<string> Production = ["prod", "production", "prd", "live"];
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };
    private static readonly SemaphoreSlim CacheLock = new(1, 1);
    private static (string Url, DateTime At, List<Jwk> Keys)? _cache;

    /// <summary>The identity provider's published keys, kept for an hour.</summary>
    public static async Task<List<Jwk>> JwksAsync(string url)
    {
        await CacheLock.WaitAsync();
        try
        {
            if (_cache is { } c && c.Url == url && DateTime.UtcNow - c.At < TimeSpan.FromHours(1)) return c.Keys;
            if (!url.StartsWith("https://", StringComparison.Ordinal)) throw new Refused(500, "AGENT_OIDC_JWKS_URL must be an https:// address");
            using JsonDocument doc = JsonDocument.Parse(await Http.GetStringAsync(url));
            List<Jwk> keys = doc.RootElement.TryGetProperty("keys", out JsonElement k) ? k.Deserialize<List<Jwk>>() ?? [] : [];
            _cache = (url, DateTime.UtcNow, keys);
            return keys;
        }
        finally
        {
            CacheLock.Release();
        }
    }

    private static byte[] B64(string s) => Base64Url.DecodeFromChars(s.TrimEnd('='));

    /// <summary>The claims of a JWT signed with RS256 by one of keys (a JWKS keys list). Anything else is refused.</summary>
    public static Dictionary<string, JsonElement> VerifyRs256(string token, IReadOnlyList<Jwk> keys)
    {
        string[] parts = token.Split('.');
        if (parts.Length != 3) throw new Refused(401, "the token is not a JWT");
        Dictionary<string, JsonElement> head, claims;
        byte[] sig;
        try
        {
            head = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(B64(parts[0])) ?? [];
            claims = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(B64(parts[1])) ?? [];
            sig = B64(parts[2]);
        }
        catch (Exception e) when (e is FormatException or JsonException)
        {
            throw new Refused(401, "the token is not a JWT");
        }

        if (!head.TryGetValue("alg", out JsonElement alg) || alg.ValueKind != JsonValueKind.String || alg.GetString() != "RS256")
            throw new Refused(401, "only RS256 tokens are accepted");
        string? kid = head.TryGetValue("kid", out JsonElement k) && k.ValueKind == JsonValueKind.String ? k.GetString() : null;
        byte[] signed = Encoding.ASCII.GetBytes(parts[0] + "." + parts[1]);
        foreach (Jwk key in keys)
        {
            if (key.kty != "RSA" || (key.use is { Length: > 0 } use && use != "sig") || (kid is not null && key.kid != kid) || key.n is null || key.e is null) continue;
            try
            {
                using RSA rsa = RSA.Create(new RSAParameters { Modulus = B64(key.n), Exponent = B64(key.e) });
                if (rsa.KeySize < MinKeyBits) continue;
                if (rsa.VerifyData(signed, sig, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1)) return claims;
            }
            catch (Exception e) when (e is CryptographicException or FormatException)
            {
                // a malformed key verifies nothing
            }
        }

        throw new Refused(401, "the token's signature does not match the identity provider's keys");
    }

    /// <summary>Refuses a token from another issuer, for another audience, expired, or not valid yet.</summary>
    public static void CheckClaims(Dictionary<string, JsonElement> claims, string issuer, string audience, DateTimeOffset now)
    {
        string? Str(string name) => claims.TryGetValue(name, out JsonElement v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
        if (issuer.Length == 0 || Str("iss") != issuer) throw new Refused(401, "the token is from another issuer");
        bool forUs = claims.TryGetValue("aud", out JsonElement aud) && audience.Length > 0 && (aud.ValueKind == JsonValueKind.String
            ? aud.GetString() == audience
            : aud.ValueKind == JsonValueKind.Array && aud.EnumerateArray().Any(a => a.ValueKind == JsonValueKind.String && a.GetString() == audience));
        if (!forUs) throw new Refused(401, "the token is for another audience");
        long t = now.ToUnixTimeSeconds();
        if (!claims.TryGetValue("exp", out JsonElement exp) || exp.ValueKind != JsonValueKind.Number || exp.GetDouble() + LeewaySeconds < t)
            throw new Refused(401, "the token has expired");
        if (claims.TryGetValue("nbf", out JsonElement nbf) && nbf.ValueKind == JsonValueKind.Number && nbf.GetDouble() - LeewaySeconds > t)
            throw new Refused(401, "the token is not valid yet");
    }

    private static List<string> GroupsOf(JsonElement? raw) => raw switch
    {
        { ValueKind: JsonValueKind.Array } a => [.. a.EnumerateArray().Select(g => g.ToString().Trim()).Where(g => g.Length > 0)],
        { ValueKind: JsonValueKind.String } s => [.. s.GetString()!.Split(',').Select(g => g.Trim()).Where(g => g.Length > 0)],
        _ => [],
    };

    /// <summary>Azure App Service authentication's X-MS-CLIENT-PRINCIPAL: base64 JSON with the token's claims.</summary>
    private static (string User, List<string> Groups) Principal(string header)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(Convert.FromBase64String(header));
            JsonElement p = doc.RootElement;
            string Typ(string name, string fallback) => p.TryGetProperty(name, out JsonElement v) && v.GetString() is { Length: > 0 } s ? s : fallback;
            string nameTyp = Typ("name_typ", "name"), roleTyp = Typ("role_typ", "roles");
            List<(string Typ, string Val)> claims = p.TryGetProperty("claims", out JsonElement c) && c.ValueKind == JsonValueKind.Array
                ? [.. c.EnumerateArray().Select(x => (x.TryGetProperty("typ", out JsonElement t) ? t.GetString() ?? "" : "", x.TryGetProperty("val", out JsonElement v) ? v.GetString() ?? "" : ""))]
                : [];
            string user = claims.FirstOrDefault(x => x.Typ == nameTyp || x.Typ is "preferred_username" or "email").Val ?? "";
            return (user, [.. claims.Where(x => x.Val.Length > 0 && (x.Typ == roleTyp || x.Typ is "groups" or "roles")).Select(x => x.Val)]);
        }
        catch (Exception e) when (e is FormatException or JsonException or InvalidOperationException)
        {
            throw new Refused(401, "the proxy's X-MS-CLIENT-PRINCIPAL is not readable");
        }
    }

    /// <summary>Whether the caller's address is inside one of nets.</summary>
    public static bool Trusted(IPAddress? remote, IEnumerable<string> nets)
    {
        if (remote is null) return false;
        IPAddress ip = remote.IsIPv4MappedToIPv6 ? remote.MapToIPv4() : remote;
        foreach (string n in nets)
        {
            if (IPNetwork.TryParse(n, out IPNetwork net) && net.Contains(ip)) return true;
            if (IPAddress.TryParse(n, out IPAddress? one) && one.Equals(ip)) return true;
        }

        return false;
    }

    /// <summary>Who is asking. header reads a request header; keys, when given, stand in for the provider's published keys (tests).</summary>
    public static async Task<Caller> WhoAsync(IdentityConf c, Func<string, string> header, IPAddress? remote, string demoUser, List<string> demoGroups,
        IReadOnlyList<Jwk>? keys = null)
    {
        switch (c.Mode)
        {
            case "demo":
                string env = Environment.GetEnvironmentVariable("APP_ENV") is { Length: > 0 } a ? a : Environment.GetEnvironmentVariable("ENVIRONMENT") ?? "";
                if (Production.Contains(env.ToLowerInvariant())) throw new Refused(503, "demo identities are off in production: set AGENT_IDENTITY to oidc or proxy");
                return new Caller(demoUser, demoGroups, "demo");
            case "oidc":
                string auth = header("Authorization");
                if (!auth.StartsWith("Bearer ", StringComparison.Ordinal)) throw new Refused(401, "sign in first: send the identity provider's token (Authorization: Bearer ...)");
                if (keys is null)
                {
                    try
                    {
                        keys = await JwksAsync(c.JwksUrl);
                    }
                    catch (Exception e) when (e is not Refused)
                    {
                        throw new Refused(503, "the identity provider's keys could not be read");
                    }
                }

                Dictionary<string, JsonElement> claims = VerifyRs256(auth["Bearer ".Length..].Trim(), keys);
                CheckClaims(claims, c.Issuer, c.Audience, DateTimeOffset.UtcNow);
                string user = new[] { "preferred_username", "email", "upn", "sub" }
                    .Select(n => claims.TryGetValue(n, out JsonElement v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null)
                    .FirstOrDefault(v => !string.IsNullOrEmpty(v)) ?? throw new Refused(401, "the token does not say who is asking");
                return new Caller(user, GroupsOf(claims.TryGetValue(c.GroupsClaim, out JsonElement g) ? g : null), "oidc");
            case "proxy":
                if (!Trusted(remote, c.TrustedProxies)) throw new Refused(403, "identity headers are accepted only from the identity-aware proxy");
                string First(params string[] names) => names.Select(header).Select(v => v.Trim()).FirstOrDefault(v => v.Length > 0) ?? "";
                (string who, List<string> groups) = First("X-MS-CLIENT-PRINCIPAL") is { Length: > 0 } principal
                    ? Principal(principal)
                    : (First("X-Forwarded-Email", "X-Auth-Request-Email", "X-Forwarded-User", "X-Auth-Request-User"),
                       [.. First("X-Forwarded-Groups", "X-Auth-Request-Groups").Split(',').Select(x => x.Trim()).Where(x => x.Length > 0)]);
                if (who.Length == 0) throw new Refused(401, "the proxy did not say who is asking");
                return new Caller(who, groups, "proxy");
            default:
                throw new Refused(500, $"unknown AGENT_IDENTITY {c.Mode}: demo, oidc or proxy");
        }
    }
}
