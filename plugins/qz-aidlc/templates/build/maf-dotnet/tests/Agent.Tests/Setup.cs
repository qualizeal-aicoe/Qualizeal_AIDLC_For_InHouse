using System.Runtime.CompilerServices;

// The tests share process-wide settings (the state database, the audit log), so they run one at a time.
[assembly: CollectionBehavior(DisableTestParallelization = true)]

namespace Agent.Tests;

internal static class Setup
{
    /// <summary>Before any test: the run's own state database and audit log, away from the project's .agent folder.</summary>
    [ModuleInitializer]
    internal static void Isolate()
    {
        string dir = Directory.CreateTempSubdirectory("agent-test-").FullName;
        Environment.SetEnvironmentVariable("AGENT_MODE", "stub");
        Environment.SetEnvironmentVariable("AGENT_STATE_DB", Path.Combine(dir, "state.db"));
        if (Environment.GetEnvironmentVariable("AGENT_AUDIT_LOG") is not { Length: > 0 })
            Environment.SetEnvironmentVariable("AGENT_AUDIT_LOG", Path.Combine(dir, "audit.jsonl"));
    }

    /// <summary>One test's own empty state database and audit log; returns the folder.</summary>
    internal static string Fresh()
    {
        string dir = Directory.CreateTempSubdirectory("agent-test-").FullName;
        Environment.SetEnvironmentVariable("AGENT_STATE_DB", Path.Combine(dir, "state.db"));
        Environment.SetEnvironmentVariable("AGENT_AUDIT_LOG", Path.Combine(dir, "audit.jsonl"));
        return dir;
    }
}
