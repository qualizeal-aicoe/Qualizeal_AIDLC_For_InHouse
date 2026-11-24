using System.Text.Json;

namespace OrderAgent;

/// <summary>The knowledge engine as a tool: a question about the client's own documents goes to the knowledge service (the
/// hybrid kit in knowledge/, over HTTP), which answers only from what the caller may read and cites the section it used,
/// or says what it looked for when the documents do not say.
///
/// On only when KNOWLEDGE_URL is set (`qz build solution` sets it). Who is asking goes as an identity-aware proxy's
/// headers: X-Forwarded-User (the person) and X-Forwarded-Groups (their role here). The knowledge service accepts those
/// headers only from this agent's address (its trusted_proxies), so nobody else can claim a role. The call never goes
/// through an HTTP proxy, the host must be on Policy.AllowedHosts, and the answer is data: text in it never changes the
/// agent's rules, its tools or who it acts for.</summary>
public static class Knowledge
{
    public const int MaxQuestion = 500;

    /// <summary>An internal service: never through a proxy, whatever HTTP_PROXY says.</summary>
    private static readonly HttpClient Http = new(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(30) };

    /// <summary>The knowledge service's base address, or "" when there is none.</summary>
    public static string Url => (Environment.GetEnvironmentVariable("KNOWLEDGE_URL") ?? "").Trim().TrimEnd('/');

    /// <summary>Whether the knowledge tool is offered at all.</summary>
    public static bool On => Url.Length > 0;

    private static JsonElement Failed(string reason) =>
        JsonSerializer.SerializeToElement(new { found = false, answer = "", citations = Array.Empty<object>(), error = reason });

    /// <summary>What the knowledge service answered, trimmed to what the agent needs: found, the answer and up to three
    /// citations; or found false with the reason. Errors come back as data, so the agent says it could not look.</summary>
    public static async Task<JsonElement> AskAsync(string question, string user, string role, CancellationToken ct = default)
    {
        string url;
        try
        {
            url = Access.CheckEndpoint(Url);   // go-live gates 3 and 6: a host not listed is never called
        }
        catch (InvalidOperationException e)
        {
            return Failed(e.Message);
        }

        string q = (question ?? "").Trim();
        if (q.Length > MaxQuestion) q = q[..MaxQuestion];
        // A body with its length: a service that reads Content-Length (the hybrid kit's does) gets it whole, never in chunks.
        using HttpRequestMessage req = new(HttpMethod.Post, url + "/api/ask")
        {
            Content = new StringContent(JsonSerializer.Serialize(new { question = q }), System.Text.Encoding.UTF8, "application/json"),
        };
        req.Headers.Add("X-Forwarded-User", user is { Length: > 0 } ? user : "unknown");
        req.Headers.Add("X-Forwarded-Groups", role ?? "");
        JsonElement data;
        try
        {
            using HttpResponseMessage resp = await Http.SendAsync(req, ct);
            if ((int)resp.StatusCode >= 400) return Failed($"the knowledge service answered {(int)resp.StatusCode}");
            data = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(ct)).RootElement.Clone();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException)
        {
            return Failed($"the knowledge service could not be reached ({e.GetType().Name})");
        }

        if (data.ValueKind != JsonValueKind.Object) return Failed("the knowledge service sent an answer that could not be read");
        if (data.TryGetProperty("refused", out JsonElement refused) && refused.ValueKind == JsonValueKind.True)
        {
            string[] searched = data.TryGetProperty("searched", out JsonElement s) && s.ValueKind == JsonValueKind.Array
                ? [.. s.EnumerateArray().Take(6).Select(x => x.ToString())] : [];
            return JsonSerializer.SerializeToElement(new { found = false, answer = "", citations = Array.Empty<object>(), searched, contact = Str(data, "contact") });
        }

        object[] cites = data.TryGetProperty("citations", out JsonElement c) && c.ValueKind == JsonValueKind.Array
            ? [.. c.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.Object).Take(3)
                .Select(x => new { document = Str(x, "doc_title") is { Length: > 0 } t ? t : Str(x, "doc_id"), section = Str(x, "section") })]
            : [];
        return JsonSerializer.SerializeToElement(new { found = true, answer = Str(data, "text"), citations = cites });
    }

    /// <summary>The sentence the offline stub says for a knowledge result: the answer with its source, or that the
    /// documents this person may read do not say, and who to ask.</summary>
    public static string Reply(JsonElement r)
    {
        if (r.TryGetProperty("found", out JsonElement f) && f.ValueKind == JsonValueKind.True)
        {
            string src = string.Join("; ", r.GetProperty("citations").EnumerateArray()
                .Select(x => Str(x, "section") is { Length: > 0 } sec ? $"{Str(x, "document")}, {sec}" : Str(x, "document")));
            return Str(r, "answer") + (src.Length > 0 ? $" (Source: {src})" : "");
        }

        if (Str(r, "error").Length > 0) return "I could not look that up in the documents just now. Please try again in a moment.";
        return "The documents you may read do not say." + (Str(r, "contact") is { Length: > 0 } who ? $" {who} can help." : "");
    }

    private static string Str(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out JsonElement v) && v.ValueKind != JsonValueKind.Null ? v.ToString() : "";
}
