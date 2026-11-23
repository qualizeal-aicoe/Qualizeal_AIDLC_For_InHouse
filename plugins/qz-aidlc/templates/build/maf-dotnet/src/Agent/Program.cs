using System.Text.Json;
using OpenTelemetry.Trace;
using OrderAgent;

// dotnet Agent.dll [message]                                     one question, the result as JSON
// dotnet Agent.dll --serve [--host 127.0.0.1] [--port 8080]      the HTTP interface (Server.cs)
// dotnet Agent.dll --health [--port 8080]                        the image's health check: 0 when healthy
// dotnet Agent.dll --waiting                                     the runs that wait for a person
// dotnet Agent.dll --answer <thread> --approve|--decline [--by NAME]   answer one, from this process or any other
string Opt(string name, string fallback) => Array.IndexOf(args, name) is int i and >= 0 && i + 1 < args.Length ? args[i + 1] : fallback;
int port = int.TryParse(Opt("--port", Environment.GetEnvironmentVariable("AGENT_PORT") ?? "8080"), out int p) ? p : 8080;

if (args.Contains("--health")) return await Server.HealthAsync(port);

using TracerProvider tracing = Telemetry.Start();
if (args.Contains("--serve"))
{
    string host = Opt("--host", Environment.GetEnvironmentVariable("AGENT_HOST") ?? "127.0.0.1");
    Console.Error.WriteLine($"Serving on http://{host}:{port} (identity: {IdentityConf.FromEnv().Mode}); Ctrl+C stops it.");
    await Server.Build(host, port).RunAsync();   // a deploy's SIGTERM finishes the requests in flight; waiting runs are in the state database
    return 0;
}

if (args.Contains("--waiting"))
{
    foreach (Durable.Saved r in Durable.Waiting())
        Console.WriteLine(JsonSerializer.Serialize(new { r.thread, asked_by = r.actor, r.role, since = r.created, waiting_for = r.pending.Select(c => new { c.name, c.args }) }));
    return 0;
}

if (args.Contains("--answer"))
{
    string thread = Opt("--answer", "");
    if (thread.Length == 0 || args.Contains("--approve") == args.Contains("--decline"))
    {
        Console.Error.WriteLine("usage: --answer <thread> --approve|--decline [--by NAME]");
        return 2;
    }

    try
    {
        Console.WriteLine(JsonSerializer.Serialize(await OrderSupport.AnswerAsync(thread, args.Contains("--approve"), Opt("--by", "") is { Length: > 0 } by ? by : null)));
        return 0;
    }
    catch (KeyNotFoundException e)
    {
        Console.Error.WriteLine(e.Message);
        return 1;
    }
}

string message = args.Length > 0 ? string.Join(' ', args) : "Where is my order ORD-1001?";
Console.WriteLine(JsonSerializer.Serialize(await OrderSupport.RunAsync(message), new JsonSerializerOptions { WriteIndented = true }));
return 0;
