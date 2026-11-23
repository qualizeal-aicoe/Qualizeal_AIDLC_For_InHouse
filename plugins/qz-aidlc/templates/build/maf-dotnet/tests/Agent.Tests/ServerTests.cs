using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using OrderAgent;

namespace Agent.Tests;

/// <summary>The HTTP interface, offline: ask, receive the pending approval, approve it over the API and get the result;
/// nobody approves their own request; the waiting run survives a restart of the server; who asks comes from the identity
/// provider, and a token is checked before it is believed.</summary>
public sealed class ServerTests : IAsyncDisposable
{
    private const string Refund = "ORD-1002 arrived damaged. Please refund it.";
    private readonly List<WebApplication> _apps = [];
    private static readonly HttpClient Http = new();

    public ServerTests()
    {
        Setup.Fresh();
        Environment.SetEnvironmentVariable("AGENT_IDENTITY", "demo");
        Environment.SetEnvironmentVariable("APP_ENV", null);
    }

    public async ValueTask DisposeAsync()
    {
        foreach (WebApplication app in _apps) await app.DisposeAsync();
        foreach (string k in new[] { "AGENT_IDENTITY", "APP_ENV", "AGENT_OIDC_ISSUER", "AGENT_OIDC_AUDIENCE", "AGENT_TRUSTED_PROXIES" }) Environment.SetEnvironmentVariable(k, null);
    }

    private async Task<string> Start(IReadOnlyList<Jwk>? keys = null)
    {
        WebApplication app = Server.Build("127.0.0.1", 0, keys);
        await app.StartAsync();
        _apps.Add(app);
        return app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First();
    }

    private static async Task<(int Status, JsonElement Body)> Call(string base_, HttpMethod method, string path, object? body = null, string? user = null,
        string? bearer = null)
    {
        using HttpRequestMessage req = new(method, base_ + path);
        if (body is not null) req.Content = JsonContent.Create(body);
        if (user is not null) req.Headers.Add("X-Demo-User", user);
        if (bearer is not null) req.Headers.Add("Authorization", "Bearer " + bearer);
        using HttpResponseMessage resp = await Http.SendAsync(req);
        string text = await resp.Content.ReadAsStringAsync();
        return ((int)resp.StatusCode, text.Length > 0 ? JsonDocument.Parse(text).RootElement.Clone() : default);
    }

    [Fact]
    public async Task Ask_wait_approve_over_the_API()
    {
        string api = await Start();
        (int st, JsonElement h) = await Call(api, HttpMethod.Get, "/health");
        Assert.Equal(200, st);
        Assert.Equal(0, h.GetProperty("waiting").GetInt32());
        (st, JsonElement r) = await Call(api, HttpMethod.Post, "/ask", new { message = Refund }, "sam");
        Assert.Equal(202, st);
        string t = r.GetProperty("thread_id").GetString()!;
        (_, JsonElement run) = await Call(api, HttpMethod.Get, $"/runs/{t}", user: "ana");
        Assert.Equal("awaiting_approval", run.GetProperty("status").GetString());
        Assert.Equal("issue_refund", run.GetProperty("waiting_for")[0].GetProperty("name").GetString());
        Assert.Equal(1, (await Call(api, HttpMethod.Get, "/health")).Body.GetProperty("waiting").GetInt32());
        Assert.Equal(403, (await Call(api, HttpMethod.Post, $"/runs/{t}/approve", user: "sam")).Status);
        Assert.Equal(403, (await Call(api, HttpMethod.Post, $"/runs/{t}/approve", user: "vic")).Status);
        (st, JsonElement done) = await Call(api, HttpMethod.Post, $"/runs/{t}/approve", user: "ana");
        Assert.Equal(200, st);
        Assert.Equal("acted", done.GetProperty("outcome").GetString());
        Assert.Matches(@"RF-\d+", done.GetProperty("output").GetString());
        Assert.Equal("ana", done.GetProperty("answered_by").GetString());
        Assert.Equal(409, (await Call(api, HttpMethod.Post, $"/runs/{t}/approve", user: "ana")).Status);
        Assert.Equal("done", (await Call(api, HttpMethod.Get, $"/runs/{t}", user: "ana")).Body.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Nobody_approves_their_own_request()
    {
        string api = await Start();
        (int st, JsonElement r) = await Call(api, HttpMethod.Post, "/ask", new { message = Refund }, "ana");
        Assert.Equal(202, st);
        (st, JsonElement e) = await Call(api, HttpMethod.Post, $"/runs/{r.GetProperty("thread_id").GetString()}/approve", user: "ana");
        Assert.Equal(403, st);
        Assert.Contains("a request they made", e.GetProperty("error").GetString());
    }

    [Fact]
    public async Task A_waiting_run_survives_a_restart_of_the_server()
    {
        (_, JsonElement r) = await Call(await Start(), HttpMethod.Post, "/ask", new { message = Refund }, "sam");
        await _apps[0].StopAsync();
        (int st, JsonElement done) = await Call(await Start(), HttpMethod.Post, $"/runs/{r.GetProperty("thread_id").GetString()}/decline", user: "ana");
        Assert.Equal(200, st);
        Assert.Equal("declined", done.GetProperty("outcome").GetString());
        Assert.DoesNotMatch(@"RF-\d+", done.GetProperty("output").GetString());
    }

    [Fact]
    public async Task Who_asks_comes_from_the_identity_not_the_body()
    {
        string api = await Start();
        Assert.Equal(401, (await Call(api, HttpMethod.Post, "/ask", new { message = Refund })).Status);
        Assert.Equal(401, (await Call(api, HttpMethod.Post, "/ask", new { message = Refund, user = "ana", role = "support" })).Status);
        (int st, JsonElement r) = await Call(api, HttpMethod.Post, "/ask", new { message = Refund }, "vic");
        Assert.Equal(200, st);
        Assert.Contains("role does not have", r.GetProperty("output").GetString());
        Assert.Equal(404, (await Call(api, HttpMethod.Get, $"/runs/{r.GetProperty("thread_id").GetString()}", user: "sam")).Status);
        Environment.SetEnvironmentVariable("APP_ENV", "production");
        Assert.Equal(503, (await Call(api, HttpMethod.Post, "/ask", new { message = Refund }, "sam")).Status);
        Assert.Equal(200, (await Call(api, HttpMethod.Get, "/health")).Status);
    }

    private static string B64(byte[] b) => Convert.ToBase64String(b).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static string Sign(RSA key, string kid, Dictionary<string, object> claims)
    {
        string signing = B64(JsonSerializer.SerializeToUtf8Bytes(new { alg = "RS256", typ = "JWT", kid })) + "." + B64(JsonSerializer.SerializeToUtf8Bytes(claims));
        return signing + "." + B64(key.SignData(Encoding.ASCII.GetBytes(signing), HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1));
    }

    [Fact]
    public async Task An_OIDC_token_is_checked_before_it_is_believed()
    {
        using RSA key = RSA.Create(2048), other = RSA.Create(2048);
        RSAParameters pub = key.ExportParameters(false);
        string api = await Start([new Jwk("RSA", "sig", "k1", "RS256", B64(pub.Modulus!), B64(pub.Exponent!))]);
        Environment.SetEnvironmentVariable("AGENT_IDENTITY", "oidc");
        Environment.SetEnvironmentVariable("AGENT_OIDC_ISSUER", "https://login.example.org");
        Environment.SetEnvironmentVariable("AGENT_OIDC_AUDIENCE", "orders-agent");
        Dictionary<string, object> With(string k, object v) => new(Good()) { [k] = v };
        Dictionary<string, object> Good() => new()
        {
            ["iss"] = "https://login.example.org", ["aud"] = "orders-agent", ["exp"] = DateTimeOffset.UtcNow.AddHours(1).ToUnixTimeSeconds(),
            ["preferred_username"] = "asha@example.org", ["groups"] = new[] { "order-viewers" },
        };
        object ask = new { message = "Where is my order ORD-1001?" };
        Assert.Equal(200, (await Call(api, HttpMethod.Post, "/ask", ask, bearer: Sign(key, "k1", Good()))).Status);
        foreach (string token in new[]
        {
            Sign(other, "k1", Good()), Sign(key, "k1", With("aud", "someone-else")), Sign(key, "k1", With("iss", "https://evil.example.net")),
            Sign(key, "k1", With("exp", DateTimeOffset.UtcNow.AddHours(-1).ToUnixTimeSeconds())), Sign(key, "k1", With("preferred_username", "")), "not-a-token",
            B64("{\"alg\":\"HS256\"}"u8.ToArray()) + "." + B64("{}"u8.ToArray()) + ".x",
        })
        {
            Assert.Equal(401, (await Call(api, HttpMethod.Post, "/ask", ask, bearer: token)).Status);
        }

        Environment.SetEnvironmentVariable("AGENT_IDENTITY", "proxy");
        string easyAuth = Convert.ToBase64String("{\"name_typ\":\"name\",\"claims\":[{\"typ\":\"name\",\"val\":\"ana\"},{\"typ\":\"groups\",\"val\":\"order-support\"}]}"u8.ToArray());
        using (HttpRequestMessage viaProxy = new(HttpMethod.Post, api + "/ask") { Content = JsonContent.Create(ask) })
        {
            viaProxy.Headers.Add("X-MS-CLIENT-PRINCIPAL", easyAuth);
            Assert.Equal(HttpStatusCode.OK, (await Http.SendAsync(viaProxy)).StatusCode);
        }

        Environment.SetEnvironmentVariable("AGENT_TRUSTED_PROXIES", "10.9.9.9/32");
        using HttpRequestMessage req = new(HttpMethod.Post, api + "/ask") { Content = JsonContent.Create(ask) };
        req.Headers.Add("X-Forwarded-Email", "ana");
        req.Headers.Add("X-Forwarded-Groups", "order-support,refund-approvers");
        Assert.Equal(HttpStatusCode.Forbidden, (await Http.SendAsync(req)).StatusCode);
    }
}
