using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;

namespace OrderAgent;

/// <summary>
/// The agent over HTTP (ASP.NET Core): ask, answer what waits for a person, and health. A waiting run lives in the
/// state database (Durable.cs), so a restart, a deploy or a rollback does not lose it, and any instance can answer it.
///
///   GET  /health                          {"status": "ok", "waiting": n}: no sign-in, for the container check and the platform
///   POST /ask                {"message"}  the result; a run that waits says so (202), with its thread
///   GET  /runs/{thread}                   how the run stands and what waits (its asker or an approver)
///   POST /runs/{thread}/approve           the result after a person's yes
///   POST /runs/{thread}/decline           the result after a person's no
///
/// Who is asking comes from the identity provider, never from the body (go-live gate 1, Identity.cs). The role is the
/// first of Policy.GroupRoles the person's groups name (gate 2); approving needs one of Policy.ApproverGroups, and
/// nobody approves a request they made.
///
///   dotnet run --project src/Agent -- --serve [--host 127.0.0.1] [--port 8080]
/// </summary>
public static partial class Server
{
    private const int MaxBody = 64 * 1024;
    private const int MaxMessage = 4000;

    [GeneratedRegex("^[0-9a-f]{32}$")]
    private static partial Regex ThreadId();

    private static string? RoleOf(List<string> groups) => Policy.GroupRoles.FirstOrDefault(gr => groups.Contains(gr.Group)).Role;

    private static bool Approver(List<string> groups) => Policy.ApproverGroups.Any(groups.Contains);

    private static IResult Send(int status, object body) =>
        Results.Text(JsonSerializer.Serialize(body), "application/json", statusCode: status);

    private static IResult Fail(Exception e) => e is Refused r
        ? Send(r.Status, new { error = r.Message })
        : Send(500, new { error = $"the run failed ({e.GetType().Name})" });

    private static async Task<Caller> CallerAsync(HttpContext ctx, IReadOnlyList<Jwk>? keys)
    {
        IdentityConf c = IdentityConf.FromEnv();
        string demo = ctx.Request.Headers["X-Demo-User"].ToString();
        if (c.Mode == "demo" && !Policy.DemoUsers.ContainsKey(demo))
            throw new Refused(401, "name a demo user in X-Demo-User: " + string.Join(", ", Policy.DemoUsers.Keys.Order(StringComparer.Ordinal)));
        return await Identity.WhoAsync(c, name => ctx.Request.Headers[name].ToString(), ctx.Connection.RemoteIpAddress, demo,
            Policy.DemoUsers.TryGetValue(demo, out List<string>? g) ? g : [], keys);
    }

    private static Durable.Saved? LoadRun(string thread) => ThreadId().IsMatch(thread) ? Durable.Load(thread) : null;

    /// <summary>The HTTP interface on host:port (port 0 picks a free one). keys, when given, stand in for the identity
    /// provider's published keys (tests).</summary>
    public static WebApplication Build(string host = "127.0.0.1", int port = 8080, IReadOnlyList<Jwk>? keys = null)
    {
        WebApplicationBuilder b = WebApplication.CreateSlimBuilder();
        b.Logging.ClearProviders();   // the audit log records each run; keep the console quiet
        string bind = IPAddress.TryParse(host, out IPAddress? ip) && ip.AddressFamily == AddressFamily.InterNetworkV6 ? $"[{host}]" : host;
        b.WebHost.UseUrls($"http://{bind}:{port}");
        b.WebHost.ConfigureKestrel(o =>
        {
            o.AddServerHeader = false;
            o.Limits.MaxRequestBodySize = MaxBody;
        });
        WebApplication app = b.Build();
        app.Use(async (ctx, next) =>
        {
            ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";
            ctx.Response.Headers["Cache-Control"] = "no-store";
            await next(ctx);
        });

        app.MapGet("/health", () =>
        {
            try
            {
                return Send(200, new { status = "ok", waiting = Durable.Waiting().Count });
            }
            catch (Exception e)
            {
                return Send(503, new { status = "unavailable", error = e.GetType().Name });
            }
        });

        app.MapPost("/ask", async (HttpContext ctx) =>
        {
            try
            {
                Caller who = await CallerAsync(ctx, keys);
                if (RoleOf(who.Groups) is not { } role) return Send(403, new { error = "none of your groups may use this agent" });
                string message;
                try
                {
                    using JsonDocument doc = await JsonDocument.ParseAsync(ctx.Request.Body);
                    message = doc.RootElement.TryGetProperty("message", out JsonElement m) && m.ValueKind == JsonValueKind.String ? m.GetString()!.Trim() : "";
                }
                catch (Exception e) when (e is JsonException or BadHttpRequestException or InvalidOperationException)
                {
                    return Send(400, new { error = "send JSON: {\"message\": \"...\"}" });
                }

                if (message.Length is 0 or > MaxMessage) return Send(400, new { error = $"the message must be 1 to {MaxMessage} characters" });
                RunResult r = await OrderSupport.RunAsync(message, role: role, actor: who.User);
                return Send(r.awaiting_approval ? 202 : 200, r);
            }
            catch (Exception e)
            {
                return Fail(e);
            }
        });

        app.MapGet("/runs/{thread}", async (HttpContext ctx, string thread) =>
        {
            try
            {
                Caller who = await CallerAsync(ctx, keys);
                Durable.Saved? s = LoadRun(thread);
                if (s is null || (s.actor != who.User && !Approver(who.Groups))) return Send(404, new { error = "no such run" });
                return Send(200, new
                {
                    s.thread, s.status, asked_by = s.actor, s.role, waiting_for = s.pending.Select(c => new { c.name, c.args }), s.answered_by,
                    result = s.answer is { } a ? JsonDocument.Parse(a).RootElement.Clone() : (JsonElement?)null,
                });
            }
            catch (Exception e)
            {
                return Fail(e);
            }
        });

        app.MapPost("/runs/{thread}/{verb}", async (HttpContext ctx, string thread, string verb) =>
        {
            if (verb is not ("approve" or "decline")) return Send(404, new { error = "not found" });
            try
            {
                Caller who = await CallerAsync(ctx, keys);
                if (!Approver(who.Groups)) return Send(403, new { error = "only an approver may answer a waiting action" });
                Durable.Saved? s = LoadRun(thread);
                if (s is null) return Send(404, new { error = "no such run" });
                if (s.actor == who.User && !Policy.SelfApproval) return Send(403, new { error = "nobody approves a request they made: ask another approver" });
                if (s.status != "awaiting_approval") return Send(409, new { error = $"the run is {s.status}, not waiting", s.answered_by });
                return Send(200, await OrderSupport.AnswerAsync(thread, verb == "approve", who.User));
            }
            catch (Exception e)
            {
                return Fail(e);
            }
        });

        app.MapFallback(() => Send(404, new { error = "not found" }));
        return app;
    }

    /// <summary>The image's health check: a server here must answer /health; with none running (the image answers one
    /// question or runs its gold set instead), the state database must open. 0 is healthy.</summary>
    public static async Task<int> HealthAsync(int port)
    {
        using HttpClient http = new() { Timeout = TimeSpan.FromSeconds(5) };
        try
        {
            using HttpResponseMessage resp = await http.GetAsync($"http://127.0.0.1:{port}/health");
            return resp.StatusCode == HttpStatusCode.OK ? 0 : 1;
        }
        catch (HttpRequestException e) when (e.InnerException is SocketException { SocketErrorCode: SocketError.ConnectionRefused })
        {
            try
            {
                using var db = Durable.Connect();
                return 0;
            }
            catch (Exception)
            {
                return 1;
            }
        }
        catch (Exception)
        {
            return 1;
        }
    }
}
