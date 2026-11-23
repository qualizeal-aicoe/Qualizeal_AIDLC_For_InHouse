using System.Diagnostics;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using OrderAgent;

namespace Agent.Tests;

/// <summary>Durable runs, offline: a run that waits for a person is answered from another process after a restart; a
/// crash right after the refund leads to exactly one refund on retry; temporary errors are retried and permanent ones stop.</summary>
public class DurableTests
{
    private const string Refund = "ORD-1002 arrived damaged. Please refund it.";

    public DurableTests() => Setup.Fresh();

    private static List<(string Order, double Amount)> Refunds()
    {
        using SqliteConnection db = Durable.Connect();
        using SqliteCommand exists = Durable.Command(db, "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sample_refunds'");
        if ((long)exists.ExecuteScalar()! == 0) return [];
        using SqliteCommand cmd = Durable.Command(db, "SELECT order_id, amount FROM sample_refunds");
        using SqliteDataReader r = cmd.ExecuteReader();
        List<(string, double)> rows = [];
        while (r.Read()) rows.Add((r.GetString(0), r.GetDouble(1)));
        return rows;
    }

    /// <summary>Answers the run as ana from a new process: the agent's own build, the way `--answer` runs it on a host.</summary>
    internal static (int Code, RunResult? Result) AnswerInANewProcess(string thread, string? crashAfter = null)
    {
        ProcessStartInfo start = new("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (string a in new[] { typeof(OrderSupport).Assembly.Location, "--answer", thread, "--approve", "--by", "ana" }) start.ArgumentList.Add(a);
        start.Environment.Remove("AGENT_CRASH_AFTER_EFFECT");
        if (crashAfter is not null) start.Environment["AGENT_CRASH_AFTER_EFFECT"] = crashAfter;
        using Process p = Process.Start(start)!;
        string output = p.StandardOutput.ReadToEnd();
        p.WaitForExit();
        return (p.ExitCode, p.ExitCode == 0 ? JsonSerializer.Deserialize<RunResult>(output.Trim().Split('\n')[^1]) : null);
    }

    [Fact]
    public async Task A_waiting_run_is_answered_from_another_process_after_a_restart()
    {
        RunResult r = await OrderSupport.RunAsync(Refund);
        Assert.True(r.awaiting_approval);
        Assert.Equal("awaiting_approval", Durable.Load(r.thread_id!)!.status);
        (int code, RunResult? done) = AnswerInANewProcess(r.thread_id!);
        Assert.Equal(0, code);
        Assert.Equal("acted", done!.outcome);
        Assert.Matches(@"RF-\d+", done.output);
        Assert.Equal("ana", done.answered_by);
        Assert.Equal("done", Durable.Load(r.thread_id!)!.status);
        Assert.Equal([("ORD-1002", 42.5)], Refunds());
    }

    [Fact]
    public async Task A_crash_right_after_the_refund_leads_to_exactly_one_refund()
    {
        RunResult r = await OrderSupport.RunAsync(Refund);
        Assert.Equal(75, AnswerInANewProcess(r.thread_id!, crashAfter: "issue_refund").Code);
        Assert.Single(Refunds());
        RunResult again = await OrderSupport.AnswerAsync(r.thread_id!, true, "ana");
        Assert.Equal("acted", again.outcome);
        Assert.Equal(42.5m, again.effects![0].GetProperty("order_refunded").GetDecimal());
        Assert.Single(Refunds());
        Assert.True((await OrderSupport.AnswerAsync(r.thread_id!, true, "ana")).already_answered);
        Assert.Single(Refunds());
    }

    [Fact]
    public async Task A_declined_run_moves_no_money_and_an_unknown_thread_is_refused()
    {
        RunResult r = await OrderSupport.RunAsync(Refund);
        RunResult no = await OrderSupport.AnswerAsync(r.thread_id!, false, "ana");
        Assert.Equal("declined", no.outcome);
        Assert.DoesNotMatch(@"RF-\d+", no.output);
        Assert.Empty(Refunds());
        await Assert.ThrowsAsync<KeyNotFoundException>(() => OrderSupport.AnswerAsync(new string('0', 32), true));
    }

    [Fact]
    public async Task The_same_change_in_one_thread_is_made_once()
    {
        List<string> seen = [];
        Task<JsonElement> Do(string key)
        {
            seen.Add(key);
            return Task.FromResult(JsonSerializer.SerializeToElement(new { ok = true, n = seen.Count }));
        }

        using (Durable.Enter(new string('t', 32)))
        {
            JsonElement a = await Durable.OnceAsync("issue_refund", new Dictionary<string, object?> { ["order_id"] = "ORD-1" }, Do);
            JsonElement b = await Durable.OnceAsync("issue_refund", new Dictionary<string, object?> { ["order_id"] = "ORD-1" }, Do);
            JsonElement c = await Durable.OnceAsync("issue_refund", new Dictionary<string, object?> { ["order_id"] = "ORD-2" }, Do);
            Assert.Equal(a.GetRawText(), b.GetRawText());
            Assert.Equal(2, c.GetProperty("n").GetInt32());
        }

        Assert.Equal(2, seen.Count);
    }

    [Fact]
    public async Task Temporary_errors_are_retried_and_permanent_ones_stop()
    {
        TimeSpan before = Durable.RetryWait;
        Durable.RetryWait = TimeSpan.FromMilliseconds(1);
        try
        {
            int tries = 0;
            Assert.Equal("ok", await Durable.RetryAsync(() => ++tries < 3 ? throw new Durable.Temporary("503 from the payment system") : Task.FromResult("ok"), "issue_refund"));
            Assert.Equal(3, tries);
            int hard = 0;
            await Assert.ThrowsAsync<InvalidOperationException>(() => Durable.RetryAsync<string>(() => { hard++; throw new InvalidOperationException("the account is closed"); }, "issue_refund"));
            Assert.Equal(1, hard);
        }
        finally
        {
            Durable.RetryWait = before;
        }

        List<string> steps = [.. File.ReadLines(Audit.FilePath).Select(l => JsonDocument.Parse(l).RootElement)
            .Where(e => e.TryGetProperty("step", out _)).Select(e => e.GetProperty("step").GetString()!)];
        Assert.Equal(2, steps.Count(s => s == "retry"));
        Assert.Equal(1, steps.Count(s => s == "error.permanent"));
        Assert.True(Audit.Verify().ok);
    }
}
