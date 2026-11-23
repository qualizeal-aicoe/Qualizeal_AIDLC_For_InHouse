namespace OrderAgent;

/// <summary>The model gateway: one setting, AGENT_GATEWAY=litellm, sends every model call through the LiteLLM proxy
/// described in gateway/litellm.yaml, at AGENT_GATEWAY_URL, with the gateway's own key (AGENT_GATEWAY_KEY).
///
/// The provider keys live in the proxy's environment and nowhere else: in gateway mode the agent refuses to start while
/// a provider key is in its own environment. Each model call carries the run's trace context (HttpClient sends the
/// W3C traceparent of the current activity), so the gateway's record of the call (model, tokens, cost) lands inside
/// the run's trace in Langfuse. The tools, the approval gate and the limits are the same with or without the gateway.</summary>
public static class Gateway
{
    public static readonly string[] ProviderKeys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "AZURE_OPENAI_API_KEY", "AZURE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY"];

    public static bool On => string.Equals((Environment.GetEnvironmentVariable("AGENT_GATEWAY") ?? "").Trim(), "litellm", StringComparison.OrdinalIgnoreCase);

    public static string Url => (Environment.GetEnvironmentVariable("AGENT_GATEWAY_URL") is { Length: > 0 } u ? u : "http://127.0.0.1:4000").TrimEnd('/');

    /// <summary>The gateway's name for the model (model_name in gateway/litellm.yaml): the gateway picks the provider.</summary>
    public static string Model(bool small = false) =>
        small && Environment.GetEnvironmentVariable("AGENT_GATEWAY_MODEL_SMALL") is { Length: > 0 } s ? s
        : Environment.GetEnvironmentVariable("AGENT_GATEWAY_MODEL") is { Length: > 0 } m ? m : "agent-model";

    /// <summary>The only credential the agent holds in gateway mode; it fails while a provider key is in reach.</summary>
    public static string Key()
    {
        string[] held = [.. ProviderKeys.Where(k => Environment.GetEnvironmentVariable(k) is { Length: > 0 })];
        if (held.Length > 0)
            throw new InvalidOperationException($"With AGENT_GATEWAY=litellm the gateway holds the provider keys: unset {string.Join(", ", held)} where the agent runs.");
        return Environment.GetEnvironmentVariable("AGENT_GATEWAY_KEY") is { Length: > 0 } k ? k
            : throw new InvalidOperationException("Set AGENT_GATEWAY_KEY to the gateway's key: a LiteLLM virtual key (its master key only on a laptop).");
    }

    /// <summary>Prompt and answer text go into traces only when the team turns it on (AGENT_TRACE_CONTENT=1).</summary>
    public static bool ContentInTraces => Environment.GetEnvironmentVariable("AGENT_TRACE_CONTENT") == "1";
}
