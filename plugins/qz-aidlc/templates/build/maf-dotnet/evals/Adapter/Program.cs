using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using OpenTelemetry.Trace;
using OrderAgent;

// Evaluation adapter: one case in on stdin, one JSON result out on stdout.
//
// Each case starts from its own empty state database unless AGENT_STATE_DB is set. Two inputs exercise durable runs:
//   approve_after_restart  the run waits for a person in this process; the answer comes from a new process (this
//                          adapter again, with --answer), which carries the run on from the state database
//   crash_after_refund     that new process dies right after the refund is made, before it is recorded as done; a third
//                          process answers again, and the refund must still have been made exactly once
using TracerProvider tracing = Telemetry.Start();

if (args.Length == 3 && args[0] == "--answer")   // the new process that answers a waiting run
{
    Console.WriteLine(JsonSerializer.Serialize(await OrderSupport.AnswerAsync(args[1], args[2] == "--approve")));
    return 0;
}

string? temp = null;
if (Environment.GetEnvironmentVariable("AGENT_STATE_DB") is not { Length: > 0 })
{
    temp = Directory.CreateTempSubdirectory("agent-case-").FullName;
    Environment.SetEnvironmentVariable("AGENT_STATE_DB", Path.Combine(temp, "state.db"));
}

try
{
    using JsonDocument doc = JsonDocument.Parse(await Console.In.ReadToEndAsync());
    JsonElement input = doc.RootElement.GetProperty("input");
    bool isObject = input.ValueKind == JsonValueKind.Object;
    string message = isObject ? input.GetProperty("message").GetString()! : input.GetString()!;
    bool? Flag(string name) => isObject && input.TryGetProperty(name, out JsonElement v) && v.ValueKind is JsonValueKind.True or JsonValueKind.False ? v.GetBoolean() : null;
    string? role = isObject && input.TryGetProperty("role", out JsonElement r) && r.ValueKind == JsonValueKind.String ? r.GetString() : null;
    bool? later = Flag("approve_after_restart");
    RunResult result = await OrderSupport.RunAsync(message, later is null ? Flag("approve") : null, role: role);
    if (later is { } yes && result.awaiting_approval)
    {
        if (Flag("crash_after_refund") == true)
        {
            (int died, _) = Again(result.thread_id!, yes, "issue_refund");
            if (died != 75) throw new InvalidOperationException($"the crash did not happen where it should (exit {died})");
        }

        (int code, string output) = Again(result.thread_id!, yes, null);
        if (code != 0) throw new InvalidOperationException($"answering in a new process failed (exit {code})");
        result = JsonSerializer.Deserialize<RunResult>(output.Trim().Split('\n')[^1])!;
    }

    Console.WriteLine(JsonSerializer.Serialize(result));
    return 0;
}
finally
{
    if (temp is not null) Directory.Delete(temp, recursive: true);
}

// Answers the run in a new process of this adapter; crashAfter makes that process die right after that tool's change.
static (int Code, string Output) Again(string thread, bool approve, string? crashAfter)
{
    string self = Environment.ProcessPath!;
    ProcessStartInfo start = new(self) { RedirectStandardOutput = true, UseShellExecute = false };
    if (Path.GetFileNameWithoutExtension(self) == "dotnet") start.ArgumentList.Add(Assembly.GetEntryAssembly()!.Location);   // run as `dotnet Adapter.dll`
    foreach (string a in new[] { "--answer", thread, approve ? "--approve" : "--decline" }) start.ArgumentList.Add(a);
    start.Environment.Remove("AGENT_CRASH_AFTER_EFFECT");
    if (crashAfter is not null) start.Environment["AGENT_CRASH_AFTER_EFFECT"] = crashAfter;
    using Process p = Process.Start(start)!;
    string output = p.StandardOutput.ReadToEnd();
    p.WaitForExit();
    return (p.ExitCode, output);
}
