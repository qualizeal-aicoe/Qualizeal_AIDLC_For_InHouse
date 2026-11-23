using Microsoft.Extensions.AI;

namespace OrderAgent;

/// <summary>Go-live gates in code: which tools a role reaches (gate 2) and which hosts the agent may call (gates 3 and 6).</summary>
public static class Access
{
    /// <summary>Only the tools this role may use reach the model. A role not in Policy.Roles gets none.</summary>
    public static IList<AITool> ToolsFor(string role, IList<AITool> tools)
    {
        HashSet<string> allowed = Policy.Roles.TryGetValue(role, out string[]? names) ? [.. names] : [];
        return [.. tools.Where(t => allowed.Contains(t.Name))];
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
