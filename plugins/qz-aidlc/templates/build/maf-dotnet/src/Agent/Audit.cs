using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace OrderAgent;

/// <summary>
/// Go-live gate 5: who did what, and when. One JSON line per event, each carrying the SHA-256 of the line before it, so
/// a line that was edited, taken out or moved shows when the chain is checked (Audit.Verify).
/// A line holds the time, the actor, the role, the event (a run or a tool call), the tool, its arguments with card and
/// ID numbers masked, and how it ended. Never the reply, never the message itself (only its hash), never a key.
/// The file is AGENT_AUDIT_LOG (default .agent/audit.jsonl, which git ignores); "-" writes each line to standard error
/// instead, for a container whose platform ships its logs (each process then starts its own chain). A chain shows
/// tampering; it does not stop it, so production ships each line to the organisation's log store (a SIEM) as it is written.
/// </summary>
public static class Audit
{
    private const string Genesis = "0000000000000000000000000000000000000000000000000000000000000000";
    private static readonly object Lock = new();
    private static long _streamSeq;
    private static string _streamHash = Genesis;

    public sealed record Check(bool ok, int records, int? broken_at);

    public static string FilePath => Environment.GetEnvironmentVariable("AGENT_AUDIT_LOG") is { Length: > 0 } p ? p : Path.Combine(".agent", "audit.jsonl");

    /// <summary>Canonical JSON: object keys in ordinal order, no spaces, so the same record always hashes the same.</summary>
    public static string Canon(JsonNode? node) => node switch
    {
        null => "null",
        JsonObject o => "{" + string.Join(",", o.OrderBy(kv => kv.Key, StringComparer.Ordinal).Select(kv => JsonSerializer.Serialize(kv.Key) + ":" + Canon(kv.Value))) + "}",
        JsonArray a => "[" + string.Join(",", a.Select(Canon)) + "]",
        _ => node.ToJsonString(),
    };

    private static string Digest(string prev, JsonObject body) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(prev + Canon(body))));

    public static void Append(string evt, string actor, string role, IDictionary<string, object?> fields)
    {
        lock (Lock)
        {
            string file = FilePath;
            long seq = 0;
            string prev = Genesis;
            if (file == "-")
            {
                seq = _streamSeq;
                prev = _streamHash;
            }
            else
            {
                string? dir = Path.GetDirectoryName(file);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                string? last = File.Exists(file) ? File.ReadLines(file).LastOrDefault(l => l.Trim().Length > 0) : null;
                if (last is not null && JsonNode.Parse(last) is JsonObject lastRecord)
                {
                    seq = lastRecord["seq"]?.GetValue<long>() ?? 0;
                    prev = lastRecord["hash"]?.GetValue<string>() ?? Genesis;
                }
            }

            JsonObject body = new()
            {
                ["seq"] = seq + 1,
                ["ts"] = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
                ["event"] = evt,
                ["actor"] = actor,
                ["role"] = role,
            };
            foreach (KeyValuePair<string, object?> field in fields) body[field.Key] = field.Value is null ? null : JsonSerializer.SerializeToNode(field.Value);
            string hash = Digest(prev, body);
            JsonObject record = JsonNode.Parse(body.ToJsonString())!.AsObject();
            record["prev"] = prev;
            record["hash"] = hash;
            string line = Canon(record);
            if (file == "-")
            {
                _streamSeq = seq + 1;
                _streamHash = hash;
                Console.Error.WriteLine(line);
            }
            else
            {
                File.AppendAllText(file, line + "\n");
            }
        }
    }

    public static Check Verify(string? file = null)
    {
        file ??= FilePath;
        if (!File.Exists(file)) return new Check(true, 0, null);
        string prev = Genesis;
        int n = 0;
        int i = 0;
        foreach (string line in File.ReadLines(file))
        {
            i++;
            if (line.Trim().Length == 0) continue;
            bool fits;
            string hash = "";
            try
            {
                JsonObject record = JsonNode.Parse(line)!.AsObject();
                string p = record["prev"]?.GetValue<string>() ?? "";
                hash = record["hash"]?.GetValue<string>() ?? "";
                long seq = record["seq"]?.GetValue<long>() ?? -1;
                record.Remove("prev");
                record.Remove("hash");
                fits = p == prev && seq == n + 1 && Digest(prev, record) == hash;
            }
            catch (Exception)
            {
                fits = false;
            }

            if (!fits) return new Check(false, n, i);
            prev = hash;
            n++;
        }

        return new Check(true, n, null);
    }
}
