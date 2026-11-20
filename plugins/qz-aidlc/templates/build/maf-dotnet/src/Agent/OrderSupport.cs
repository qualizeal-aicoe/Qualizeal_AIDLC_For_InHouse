using Anthropic;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace OrderAgent;

public sealed record ToolCall(string name, IDictionary<string, object?>? args, string status);

public sealed record RunResult(string output, List<ToolCall> tool_calls, Dictionary<string, long> usage, bool awaiting_approval);

/// <summary>The agent: Microsoft Agent Framework with approval-required tools, a session, limits and OpenTelemetry.</summary>
public static class OrderSupport
{
    public static AIAgent Build()
    {
        bool live = Environment.GetEnvironmentVariable("AGENT_MODE") == "live";
        ChatClientAgentOptions options = new()
        {
            Name = "__SLUG__",
            ChatOptions = new ChatOptions { Instructions = Policy.System, Tools = Tools.All(), MaxOutputTokens = Policy.MaxOutputTokens },
        };
        AIAgent agent = live
            ? new AnthropicClient { ApiKey = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY") ?? throw new InvalidOperationException("Set ANTHROPIC_API_KEY for live runs.") }
                .AsAIAgent(model: Policy.Model, name: options.Name, instructions: Policy.System, tools: Tools.All(),
                    clientFactory: inner => inner.AsBuilder().ConfigureOptions(o => o.MaxOutputTokens ??= Policy.MaxOutputTokens).Build())
            : new StubChatClient().AsAIAgent(options);
        // Spans for every agent run, model call and tool call. Prompts and results stay out of traces.
        return agent.AsBuilder().UseOpenTelemetry(Policy.TelemetrySource, o => o.EnableSensitiveData = false).Build();
    }

    /// <summary>approve: true or false answers the approval request; null leaves it waiting (keep the session to resume).</summary>
    public static async Task<RunResult> RunAsync(string message, bool? approve = null, AIAgent? agent = null)
    {
        agent ??= Build();
        AgentSession session = await agent.CreateSessionAsync();
        List<ToolCall> calls = [];
        Dictionary<string, long> usage = new() { ["input_tokens"] = 0, ["output_tokens"] = 0 };
        AgentResponse response = await agent.RunAsync(message, session);
        bool waiting = false;
        for (int round = 0; round < Policy.MaxIterations; round++)
        {
            Collect(response, calls, usage);
            List<ToolApprovalRequestContent> requests = [.. response.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>()];
            if (requests.Count == 0) break;
            foreach (ToolApprovalRequestContent request in requests)
            {
                FunctionCallContent call = (FunctionCallContent)request.ToolCall;
                calls.Add(new ToolCall(call.Name, call.Arguments, approve switch { null => "pending", true => "ok", false => "denied" }));
            }

            if (approve is null) { waiting = true; break; }
            List<ChatMessage> answers = requests.ConvertAll(r => new ChatMessage(ChatRole.User, [r.CreateResponse(approve.Value)]));
            response = await agent.RunAsync(answers, session);
        }

        string text = waiting
            ? $"This needs approval from a person before it can go ahead: {string.Join(", ", calls.Where(c => c.status == "pending").Select(c => c.name))}. It is waiting; nothing has been changed."
            : response.Text;
        return new RunResult(text, calls, usage, waiting);
    }

    private static void Collect(AgentResponse response, List<ToolCall> calls, Dictionary<string, long> usage)
    {
        usage["input_tokens"] += response.Usage?.InputTokenCount ?? 0;
        usage["output_tokens"] += response.Usage?.OutputTokenCount ?? 0;
        foreach (FunctionCallContent call in response.Messages.SelectMany(m => m.Contents).OfType<FunctionCallContent>())
        {
            if (!Policy.NeedsApproval.Contains(call.Name)) calls.Add(new ToolCall(call.Name, call.Arguments, "ok"));
        }
    }
}
