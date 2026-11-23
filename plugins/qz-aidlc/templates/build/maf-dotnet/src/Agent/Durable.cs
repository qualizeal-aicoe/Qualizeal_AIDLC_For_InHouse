using System.Diagnostics;
using System.Globalization;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace OrderAgent;

/// <summary>
/// Durable runs: a run that waits for a person survives a restart, and a change is never made twice.
///
/// The state database is SQLite (AGENT_STATE_DB, default .agent/state.db) through Microsoft.Data.Sqlite: nothing to
/// install, no server to run. Postgres is the step up when several machines share the runs (the same two tables).
///
///   runs     one row per thread: the message, who asked and in which role, how it stands, the calls so far and what
///            waits for a person, so another process (after a restart, a deploy, or the HTTP interface) finishes it
///   effects  one row per change a tool makes, keyed by the thread, the tool and its arguments. A step retried after a
///            crash finds the row and returns what the first call returned. The key also goes to the system that makes
///            the change, as its idempotency key, so a crash between the change and the row cannot make it twice either
///
/// Temporary errors (a timeout, a dropped connection, a 408, 425, 429 or 5xx) are retried after a short wait that
/// grows; anything else stops at once with the reason. Both are events on the trace and lines in the audit log.
/// </summary>
public static class Durable
{
    public const int Retries = 3;                                         // attempts for a temporary error, the first included
    public static TimeSpan RetryWait { get; set; } = TimeSpan.FromMilliseconds(500);   // then double, with a little jitter
    private static readonly HashSet<int> TemporaryStatus = [408, 425, 429, 500, 502, 503, 504];
    private static readonly AsyncLocal<string?> CurrentThread = new();

    private const string Schema = """
        CREATE TABLE IF NOT EXISTS runs (thread TEXT PRIMARY KEY, created TEXT, updated TEXT, status TEXT, message TEXT, role TEXT,
          actor TEXT, calls TEXT, pending TEXT, state TEXT, answer TEXT, answered_by TEXT);
        CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, thread TEXT, tool TEXT, args TEXT, status TEXT, result TEXT,
          error TEXT, created TEXT, updated TEXT);
        """;

    /// <summary>One run in the state database. message is as the agent read it: card and ID numbers masked.</summary>
    public sealed record Saved(string thread, string status, string message, string role, string actor, List<ToolCall> calls,
        List<ToolCall> pending, string? answer, string? answered_by, string created);

    /// <summary>An error worth another try: the system said so (a 429 or a 5xx), or the network failed on the way.</summary>
    public sealed class Temporary(string message, Exception? inner = null) : Exception(message, inner);

    /// <summary>The run's thread, or null outside a run.</summary>
    public static string? Thread => CurrentThread.Value;

    /// <summary>Runs what follows (in this async flow) as the run `thread`: a change made under it is made once.</summary>
    public static IDisposable Enter(string thread)
    {
        string? before = CurrentThread.Value;
        CurrentThread.Value = thread;
        return new Scope(() => CurrentThread.Value = before);
    }

    private sealed class Scope(Action done) : IDisposable
    {
        public void Dispose() => done();
    }

    public static string NewThread() => Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16));

    public static string StatePath => Environment.GetEnvironmentVariable("AGENT_STATE_DB") is { Length: > 0 } p ? p : Path.Combine(".agent", "state.db");

    private static string Now() => DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);

    /// <summary>The state database, with its folder and tables. Dispose it when done.</summary>
    public static SqliteConnection Connect()
    {
        string? dir = Path.GetDirectoryName(Path.GetFullPath(StatePath));
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        SqliteConnection db = new(new SqliteConnectionStringBuilder { DataSource = StatePath, Pooling = false, DefaultTimeout = 30 }.ToString());
        db.Open();
        Execute(db, "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000;" + Schema);
        return db;
    }

    public static int Execute(SqliteConnection db, string sql, params object?[] args)
    {
        using SqliteCommand cmd = Command(db, sql, args);
        return cmd.ExecuteNonQuery();
    }

    public static SqliteCommand Command(SqliteConnection db, string sql, params object?[] args)
    {
        SqliteCommand cmd = db.CreateCommand();
        cmd.CommandText = sql;
        for (int i = 0; i < args.Length; i++) cmd.Parameters.AddWithValue($"$p{i}", args[i] ?? DBNull.Value);
        return cmd;
    }

    /// <summary>Writes a run's row, creating it the first time.</summary>
    public static void Save(string thread, string status, string message, string role, string actor, List<ToolCall> calls, string? answer, string? answeredBy)
    {
        using SqliteConnection db = Connect();
        string at = Now();
        List<ToolCall> pending = [.. calls.Where(c => c.status == "pending")];
        Execute(db, """
            INSERT INTO runs (thread, created, updated, status, message, role, actor, calls, pending, answer, answered_by)
            VALUES ($p0, $p1, $p1, $p2, $p3, $p4, $p5, $p6, $p7, $p8, $p9)
            ON CONFLICT(thread) DO UPDATE SET updated = excluded.updated, status = excluded.status, message = excluded.message,
              role = excluded.role, actor = excluded.actor, calls = excluded.calls, pending = excluded.pending,
              answer = excluded.answer, answered_by = excluded.answered_by
            """, thread, at, status, message, role, actor, JsonSerializer.Serialize(calls), JsonSerializer.Serialize(pending), answer, answeredBy);
    }

    /// <summary>One run, or null when there is none.</summary>
    public static Saved? Load(string thread)
    {
        using SqliteConnection db = Connect();
        using SqliteCommand cmd = Command(db, "SELECT status, message, role, actor, calls, pending, answer, answered_by, created FROM runs WHERE thread = $p0", thread);
        using SqliteDataReader r = cmd.ExecuteReader();
        if (!r.Read()) return null;
        string? S(int i) => r.IsDBNull(i) ? null : r.GetString(i);
        List<ToolCall> Calls(int i) => S(i) is { Length: > 0 } j ? JsonSerializer.Deserialize<List<ToolCall>>(j) ?? [] : [];
        return new Saved(thread, S(0) ?? "", S(1) ?? "", S(2) ?? "", S(3) ?? "", Calls(4), Calls(5), S(6), S(7), S(8) ?? "");
    }

    /// <summary>The runs that wait for a person, oldest first.</summary>
    public static List<Saved> Waiting()
    {
        List<string> ids = [];
        using (SqliteConnection db = Connect())
        using (SqliteCommand cmd = Command(db, "SELECT thread FROM runs WHERE status = 'awaiting_approval' ORDER BY created"))
        using (SqliteDataReader r = cmd.ExecuteReader())
        {
            while (r.Read()) ids.Add(r.GetString(0));
        }

        return [.. ids.Select(Load).OfType<Saved>()];
    }

    /// <summary>The idempotency key of one change: the thread, the tool and its arguments.</summary>
    public static string Key(string thread, string tool, IReadOnlyDictionary<string, object?> args)
    {
        string body = JsonSerializer.Serialize(new SortedDictionary<string, object?>(StringComparer.Ordinal)
        {
            ["args"] = new SortedDictionary<string, object?>(args.ToDictionary(kv => kv.Key, kv => kv.Value), StringComparer.Ordinal),
            ["thread"] = thread,
            ["tool"] = tool,
        });
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(body)))[..32];
    }

    /// <summary>Makes the change doIt(key) at most once for this run's thread, tool and arguments: a second call (a retry
    /// after a crash, a replayed step) returns what the first one returned. Outside a run every call is its own.</summary>
    public static async Task<JsonElement> OnceAsync(string tool, IReadOnlyDictionary<string, object?> args, Func<string, Task<JsonElement>> doIt)
    {
        if (Thread is not { } thread) return await doIt(NewThread());
        string key = Key(thread, tool, args);
        using SqliteConnection db = Connect();
        string? status = null, stored = null;
        using (SqliteCommand cmd = Command(db, "SELECT status, result FROM effects WHERE key = $p0", key))
        using (SqliteDataReader r = cmd.ExecuteReader())
        {
            if (r.Read())
            {
                status = r.IsDBNull(0) ? "" : r.GetString(0);
                stored = r.IsDBNull(1) ? null : r.GetString(1);
            }
        }

        if (status == "done" && stored is not null)
        {
            Event("effect.replayed", new() { ["tool"] = tool, ["key"] = key });
            return JsonDocument.Parse(stored).RootElement.Clone();
        }

        string at = Now();
        Execute(db, "INSERT OR IGNORE INTO effects (key, thread, tool, args, status, created, updated) VALUES ($p0, $p1, $p2, $p3, 'started', $p4, $p4)",
            key, thread, tool, JsonSerializer.Serialize(new SortedDictionary<string, object?>(args.ToDictionary(kv => kv.Key, kv => kv.Value), StringComparer.Ordinal)), at);
        if (status is not null) Event("effect.resumed", new() { ["tool"] = tool, ["key"] = key });   // the system's own key keeps it single
        JsonElement result;
        try
        {
            result = await RetryAsync(() => doIt(key), tool);
        }
        catch (Exception e)
        {
            string why = $"{e.GetType().Name}: {e.Message}";
            Execute(db, "UPDATE effects SET status = 'failed', error = $p0, updated = $p1 WHERE key = $p2", why.Length > 300 ? why[..300] : why, Now(), key);
            throw;
        }

        if (Environment.GetEnvironmentVariable("AGENT_CRASH_AFTER_EFFECT") == tool) Environment.Exit(75);   // tests only: the change is made, the row is not
        try
        {
            Execute(db, "UPDATE effects SET status = 'done', result = $p0, updated = $p1 WHERE key = $p2", result.GetRawText(), Now(), key);
        }
        catch (SqliteException e)   // the change is made; a retry finds the row unfinished and the system's own key returns it
        {
            Event("effect.unrecorded", new() { ["tool"] = tool, ["key"] = key, ["error"] = e.GetType().Name });
        }

        return result;
    }

    /// <summary>Whether e is worth another try.</summary>
    public static bool IsTemporary(Exception e) => e switch
    {
        Temporary or TimeoutException or TaskCanceledException => true,
        HttpRequestException { StatusCode: { } code } => TemporaryStatus.Contains((int)code),
        HttpRequestException { InnerException: SocketException or IOException } => true,
        SocketException => true,
        _ => false,
    };

    /// <summary>Calls fn; a temporary error is tried again after a short wait that grows, anything else stops at once.</summary>
    public static async Task<T> RetryAsync<T>(Func<Task<T>> fn, string what = "")
    {
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                return await fn();
            }
            catch (Exception e) when (!IsTemporary(e))
            {
                Event("error.permanent", new() { ["tool"] = what, ["error"] = e.GetType().Name, ["reason"] = e.Message.Length > 200 ? e.Message[..200] : e.Message });
                throw;
            }
            catch (Exception e) when (attempt >= Retries)
            {
                Event("retry.gave_up", new() { ["tool"] = what, ["attempts"] = attempt, ["error"] = e.GetType().Name });
                throw;
            }
            catch (Exception e)
            {
                TimeSpan wait = RetryWait * Math.Pow(2, attempt - 1) * (0.8 + 0.4 * Random.Shared.NextDouble());
                Event("retry", new() { ["tool"] = what, ["attempt"] = attempt, ["wait_ms"] = (long)wait.TotalMilliseconds, ["error"] = e.GetType().Name });
                await Task.Delay(wait);
            }
        }
    }

    /// <summary>An event on the current trace activity, where there is one, and a line in the audit log.</summary>
    public static void Event(string name, Dictionary<string, object?> attrs)
    {
        Activity.Current?.AddEvent(new ActivityEvent(name, tags: new ActivityTagsCollection(attrs.Select(kv => new KeyValuePair<string, object?>(kv.Key, kv.Value?.ToString())))));
        try
        {
            Dictionary<string, object?> fields = new() { ["step"] = name, ["thread"] = Thread ?? "" };
            foreach (KeyValuePair<string, object?> kv in attrs) fields[kv.Key] = kv.Value;
            Audit.Append("durable", Policy.Actor, Policy.Role, fields);
        }
        catch (IOException)
        {
            // the run goes on if the line cannot be written
        }
    }
}
