using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Anthropic;
using Anthropic.Models.Messages;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace OrderAgent;

/// <summary>One tool call. result is what the tool returned, when it ran: the grounded check and the effects read it.</summary>
public sealed record ToolCall(string name, IDictionary<string, object?>? args, string status, JsonElement? result = null, [property: JsonIgnore] string? call_id = null);

/// <summary>ai_notice: shown before the first reply (EU AI Act Article 50(1)); ai_generated: a machine-readable mark, false for fixed texts (50(2)).
/// effects, outcome and checks are the outcome and response levels the evals and the live monitor score.</summary>
public sealed record RunResult(string output, List<ToolCall> tool_calls, Dictionary<string, long> usage, bool awaiting_approval, Dictionary<string, List<string>>? guard = null,
    string? ai_notice = null, bool ai_generated = false, string? role = null, List<JsonElement>? effects = null, string? outcome = null,
    Dictionary<string, object>? checks = null);

/// <summary>The agent: Microsoft Agent Framework with approval-required tools, a session, limits and OpenTelemetry.</summary>
public static class OrderSupport
{
    /// <summary>The model sees only the role's tools (go-live gate 2); a live model is called only on a listed host (gates 3 and 6).</summary>
    public static AIAgent Build(string? model = null, string? role = null)
    {
        bool live = Environment.GetEnvironmentVariable("AGENT_MODE") == "live";
        IList<AITool> tools = Access.ToolsFor(role ?? Policy.Role, Tools.All());
        ChatClientAgentOptions options = new()
        {
            Name = "__SLUG__",
            ChatOptions = new ChatOptions { Instructions = Policy.System, Tools = tools, MaxOutputTokens = Policy.MaxOutputTokens },
        };
        if (live) Access.CheckEndpoint(Policy.ModelUrl);
        AIAgent agent = live
            ? new AnthropicClient { ApiKey = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY") ?? throw new InvalidOperationException("Set ANTHROPIC_API_KEY for live runs.") }
                .AsAIAgent(model: model ?? Policy.Model, name: options.Name, instructions: null, tools: tools,
                    // The system prompt goes in as a cached block: the breakpoint covers the tools before it, so every turn reuses both.
                    clientFactory: inner => inner.AsBuilder().ConfigureOptions(o => o.MaxOutputTokens ??= Policy.MaxOutputTokens)
                        .Use((messages, chatOptions, next, ct) => next(messages.Prepend(CachedSystem()), chatOptions, ct)).Build())
            : new StubChatClient([.. tools.Select(t => t.Name)]).AsAIAgent(options);
        // Spans for every agent run, model call and tool call. Prompts and results stay out of traces.
        return agent.AsBuilder().UseOpenTelemetry(Policy.TelemetrySource, o => o.EnableSensitiveData = false).Build();
    }

    /// <summary>approve: true or false answers the approval request; null leaves it waiting (keep the session to resume).
    /// role and actor say who is asking (defaults: Policy.Role and Policy.Actor); the run goes to the audit log.</summary>
    public static async Task<RunResult> RunAsync(string message, bool? approve = null, AIAgent? agent = null, string? role = null, string? actor = null)
    {
        string who = role ?? Policy.Role, by = actor ?? Policy.Actor, masked = Guardrails.Mask(message ?? "").Text;
        RunResult result;
        try
        {
            result = await GuardedAsync(message ?? "", approve, agent, who) with { role = who };
        }
        catch (Exception e)   // a run that fails is recorded as failed, then thrown as before
        {
            Record(by, who, masked, new RunResult("", [], new() { ["input_tokens"] = 0, ["output_tokens"] = 0 }, false, outcome: "failed"), e.GetType().Name);
            throw;
        }

        bool refused = result.guard is not null && result.guard.TryGetValue("input", out List<string>? found) && found.Contains("instruction-like input");
        List<JsonElement> effects = Guardrails.Effects(result.tool_calls);
        result = result with { effects = effects, outcome = Guardrails.Outcome(result with { effects = effects }, refused) };
        if (result.outcome is "acted" or "answered" or "declined")
        {
            List<string> sources = [Guardrails.ScreenInput(message ?? "").Text, Policy.System, .. result.tool_calls.Where(c => c.result is not null).Select(c => c.result!.Value.GetRawText())];
            List<string> bad = Guardrails.Ungrounded(result.output, sources);
            result = result with { checks = new() { ["grounded"] = bad.Count == 0, ["ungrounded"] = bad.Count } };
        }

        Record(by, who, masked, result);   // go-live gate 5
        return result;
    }

    /// <summary>One audit line per tool call and one for the run: masked arguments, never the reply or the message itself.
    /// The run line carries what the live monitor scores: how it ended, what it changed, whether the reply was grounded.</summary>
    private static void Record(string actor, string role, string message, RunResult r, string? error = null)
    {
        string runId = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16));
        foreach (ToolCall c in r.tool_calls)
        {
            string args = Guardrails.Mask(JsonSerializer.Serialize(c.args)).Text;
            Audit.Append("tool", actor, role, new Dictionary<string, object?> { ["run_id"] = runId, ["tool"] = c.name, ["status"] = c.status, ["args"] = args.Length > 500 ? args[..500] : args });
        }

        string sha = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(message)))[..16];
        List<JsonElement> effects = [.. (r.effects ?? []).Select(e => JsonDocument.Parse(Guardrails.Mask(e.GetRawText()).Text).RootElement.Clone())];
        Dictionary<string, object?> fields = new()
        {
            ["run_id"] = runId, ["outcome"] = r.outcome, ["checks"] = r.checks, ["effects"] = effects, ["tool_calls"] = r.tool_calls.Count,
            ["message_sha"] = sha, ["message_chars"] = message.Length, ["guard"] = r.guard,
        };
        if (error is not null) fields["error"] = error;
        Audit.Append("run", actor, role, fields);
    }

    private static async Task<RunResult> GuardedAsync(string message, bool? approve, AIAgent? agent, string role)
    {
        Guardrails.Screened input = Guardrails.ScreenInput(message);   // gate 1: checked before the agent reads it
        if (input.Blocked)
            return new RunResult(input.Text, [], new() { ["input_tokens"] = 0, ["output_tokens"] = 0 }, false, new() { ["input"] = input.Findings, ["output"] = [] },
                Guardrails.AiNotice, false);
        message = input.Text;
        agent ??= Build(Policy.PickModel(message), role);
        AgentSession session = await agent.CreateSessionAsync();
        List<ToolCall> calls = [];
        Dictionary<string, JsonElement> results = [];   // call id -> what the tool returned
        Dictionary<string, long> usage = new() { ["input_tokens"] = 0, ["output_tokens"] = 0 };
        AgentResponse response = await agent.RunAsync(message, session);
        bool waiting = false;
        for (int round = 0; round < Policy.MaxIterations; round++)
        {
            Collect(response, calls, usage, results);
            List<ToolApprovalRequestContent> requests = [.. response.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>()];
            if (requests.Count == 0) break;
            foreach (ToolApprovalRequestContent request in requests)
            {
                FunctionCallContent call = (FunctionCallContent)request.ToolCall;
                calls.Add(new ToolCall(call.Name, call.Arguments, approve switch { null => "pending", true => "ok", false => "denied" }, call_id: call.CallId));
            }

            if (approve is null) { waiting = true; break; }
            List<ChatMessage> answers = requests.ConvertAll(r => new ChatMessage(ChatRole.User, [r.CreateResponse(approve.Value)]));
            response = await agent.RunAsync(answers, session);
        }

        Results(response, results);   // the last answer can carry the result of an approved call
        calls = calls.ConvertAll(c => c.status == "ok" && c.call_id is not null && results.TryGetValue(c.call_id, out JsonElement r) ? c with { result = r } : c);

        string text = waiting
            ? $"This needs approval from a person before it can go ahead: {string.Join(", ", calls.Where(c => c.status == "pending").Select(c => c.name))}. It is waiting; nothing has been changed."
            : response.Text;
        Guardrails.Screened output = Guardrails.ScreenOutput(text);   // gate 2: checked before anyone sees it
        return new RunResult(output.Text, calls, usage, waiting, new() { ["input"] = input.Findings, ["output"] = output.Findings },
            Guardrails.AiNotice, !output.Blocked && !waiting);
    }

    private static ChatMessage CachedSystem() =>
        new(ChatRole.System, [new TextContent(Policy.System).WithCacheControl(new CacheControlEphemeral())]);

    private static void Collect(AgentResponse response, List<ToolCall> calls, Dictionary<string, long> usage, Dictionary<string, JsonElement> results)
    {
        usage["input_tokens"] += response.Usage?.InputTokenCount ?? 0;
        usage["output_tokens"] += response.Usage?.OutputTokenCount ?? 0;
        foreach (FunctionCallContent call in response.Messages.SelectMany(m => m.Contents).OfType<FunctionCallContent>())
        {
            if (!Policy.NeedsApproval.Contains(call.Name)) calls.Add(new ToolCall(call.Name, call.Arguments, "ok", call_id: call.CallId));
        }

        Results(response, results);
    }

    /// <summary>What each tool returned, by call id: the grounded check and the effects read it.</summary>
    private static void Results(AgentResponse response, Dictionary<string, JsonElement> results)
    {
        foreach (FunctionResultContent done in response.Messages.SelectMany(m => m.Contents).OfType<FunctionResultContent>())
        {
            if (done.Exception is null) results[done.CallId] = done.Result is JsonElement je ? je.Clone() : JsonSerializer.SerializeToElement(done.Result);
        }
    }
}
