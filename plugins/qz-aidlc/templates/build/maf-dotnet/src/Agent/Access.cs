using Microsoft.Extensions.AI;

namespace OrderAgent;

/// <summary>Go-live gates in code: which tools a role reaches (gate 2) and which hosts the agent may call (gates 3 and 6).</summary>
public static class Access
{
    /// <summary>Only the tools this role may use reach the model. A role not in Policy.Roles gets none. The knowledge
    /// tool is on only where a knowledge service is (KNOWLEDGE_URL, Knowledge.cs).</summary>
    public static IList<AITool> ToolsFor(string role, IList<AITool> tools)
    {
        HashSet<string> allowed = Policy.Roles.TryGetValue(role, out string[]? names) ? [.. names] : [];
        if (!Knowledge.On) allowed.Remove("search_knowledge");
        return [.. tools.Where(t => allowed.Contains(t.Name))];
    }

    private static readonly AsyncLocal<(string Role, string Actor)?> Current = new();

    /// <summary>Who the current run acts for, and in which role: set by RunAsync and AnswerAsync from whoever started the
    /// agent (an interface: the identity provider), never by the message. Tools read it (the knowledge service applies
    /// their access). Outside a run, Policy.Role and Policy.Actor.</summary>
    public static (string Role, string Actor) Caller => Current.Value ?? (Policy.Role, Policy.Actor);

    /// <summary>Runs what follows (in this async flow) as this role and person.</summary>
    public static IDisposable Enter(string role, string actor)
    {
        (string, string)? before = Current.Value;
        Current.Value = (role, actor);
        return new Scope(() => Current.Value = before);
    }

    private sealed class Scope(Action done) : IDisposable
    {
        public void Dispose() => done();
    }

    /// <summary>The agent calls only the hosts on Policy.AllowedHosts. Anything else fails closed.</summary>
    public static string CheckEndpoint(string url)
    {
        string host = Uri.TryCreate(url.Contains("://") ? url : "https://" + url, UriKind.Absolute, out Uri? uri) ? uri.Host.ToLowerInvariant() : "";
        if (host.Length == 0 || !Policy.AllowedHosts.Contains(host, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"'{host}' is not on Policy.AllowedHosts. Add it there, and to .qz/golive.json with its region, only once the data may go there.");
        }

        return url;
    }
}
