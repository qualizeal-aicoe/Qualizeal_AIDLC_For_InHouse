using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.AI;

namespace OrderAgent;

/// <summary>A scripted stand-in for the model, for offline runs and CI. It follows fixed rules, so it proves the
/// wiring (tools, approval, limits, tracing), not the quality of a model's answers.</summary>
public sealed partial class StubChatClient(IEnumerable<string>? given = null) : IChatClient
{
    /// <summary>What the stub says when the call it wants is not among the role's tools: a model only calls the tools it was given.</summary>
    public const string NotAllowed = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help.";

    private readonly HashSet<string>? _given = given is null ? null : [.. given];

    [GeneratedRegex(@"\bORD-\d+\b", RegexOptions.IgnoreCase)]
    private static partial Regex OrderRx();

    /// <summary>A question about how things are done here, for the knowledge service when there is one (KNOWLEDGE_URL).</summary>
    [GeneratedRegex(@"\b(polic(?:y|ies)|handbook|procedures?|warranty|return window|refund window|limits?|how long|how many days|eligible|allowed to)\b", RegexOptions.IgnoreCase)]
    private static partial Regex KnowledgeRx();

    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
    {
        List<ChatMessage> all = [.. messages];
        string user = all.FirstOrDefault(m => m.Role == ChatRole.User && !string.IsNullOrEmpty(m.Text))?.Text ?? "";
        Dictionary<string, string> names = [];
        Dictionary<string, JsonElement> results = [];
        int size = 0;
        foreach (AIContent c in all.SelectMany(m => m.Contents))
        {
            switch (c)
            {
                case TextContent t: size += t.Text.Length; break;
                case FunctionCallContent call: names[call.CallId] = call.Name; break;
                case FunctionResultContent result when names.TryGetValue(result.CallId, out string? name):
                    results[name] = ToJson(result.Result);
                    size += results[name].GetRawText().Length;
                    break;
            }
        }

        (string, Dictionary<string, object?>)? decision = Decide(user, results);
        if (decision is (string wanted, _) && _given is not null && !_given.Contains(wanted))
        {
            decision = null;
            _say = NotAllowed;
        }

        ChatMessage reply = decision is (string callName, Dictionary<string, object?> args)
            ? new ChatMessage(ChatRole.Assistant, [new FunctionCallContent($"call_{results.Count + 1}", callName, args)])
            : new ChatMessage(ChatRole.Assistant, _say);
        return Task.FromResult(new ChatResponse(reply)
        {
            ModelId = "qz-stub",
            Usage = new UsageDetails { InputTokenCount = size / 4 + 60, OutputTokenCount = 24, TotalTokenCount = size / 4 + 84 },
        });
    }

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        ChatResponse response = await GetResponseAsync(messages, options, cancellationToken);
        foreach (ChatResponseUpdate update in response.ToChatResponseUpdates())
        {
            yield return update;
        }
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => serviceType.IsInstanceOfType(this) ? this : null;

    public void Dispose() { }

    private string _say = "";

    private (string, Dictionary<string, object?>)? Decide(string user, Dictionary<string, JsonElement> results)
    {
        if (results.TryGetValue("search_knowledge", out JsonElement known)) { _say = Knowledge.Reply(known); return null; }   // said with its source
        if (_given?.Contains("search_knowledge") == true && !OrderRx().IsMatch(user) && KnowledgeRx().IsMatch(user))
        {
            return ("search_knowledge", new() { ["question"] = user });
        }

        Match m = OrderRx().Match(user);
        if (!m.Success) { _say = "I can help once I have an order number, for example ORD-1001."; return null; }
        string oid = m.Value.ToUpperInvariant();
        if (!results.TryGetValue("get_order", out JsonElement order)) return ("get_order", new() { ["order_id"] = oid });
        if (!Flag(order, "found")) { _say = $"I could not find order {oid}. Please check the number."; return null; }
        bool tried = results.TryGetValue("issue_refund", out JsonElement refund);
        if (user.Contains("refund", StringComparison.OrdinalIgnoreCase) && !tried)
        {
            return ("issue_refund", new() { ["order_id"] = oid, ["amount"] = order.GetProperty("total").GetDecimal(), ["reason"] = "customer request" });
        }

        if (tried)
        {
            _say = Flag(refund, "ok")
                ? $"Refund {Text(refund, "refund_id")} of {Text(refund, "amount")} has been issued for order {oid}."
                : $"The refund for order {oid} was not issued: {(Text(refund, "error") is { Length: > 0 } e ? e : "a person declined it")}.";
            return null;
        }

        string carrier = Text(order, "carrier");
        _say = $"Order {oid} is {Text(order, "status")}" + (carrier.Length > 0 ? $" with {carrier}." : ".");
        return null;
    }

    private static bool Flag(JsonElement e, string name) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out JsonElement v) && v.ValueKind == JsonValueKind.True;

    private static string Text(JsonElement e, string name) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out JsonElement v) ? v.ToString() : "";

    private static JsonElement ToJson(object? value)
    {
        string raw = value switch { null => "null", JsonElement j => j.GetRawText(), string s => s, _ => JsonSerializer.Serialize(value) };
        try { return JsonDocument.Parse(raw).RootElement.Clone(); }
        catch (JsonException) { return JsonSerializer.SerializeToElement(new { ok = false, error = raw }); }
    }
}
