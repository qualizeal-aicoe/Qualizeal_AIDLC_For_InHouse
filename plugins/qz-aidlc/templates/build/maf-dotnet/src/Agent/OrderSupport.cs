using System.Diagnostics;
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
/// effects, outcome and checks are the outcome and response levels the evals and the live monitor score.
/// thread_id is the run's thread: AnswerAsync(thread_id, ...) finishes one that waits, from this process or any other.</summary>
public sealed record RunResult(string output, List<ToolCall> tool_calls, Dictionary<string, long> usage, bool awaiting_approval, Dictionary<string, List<string>>? guard = null,
    string? ai_notice = null, bool ai_generated = false, string? role = null, List<JsonElement>? effects = null, string? outcome = null,
    Dictionary<string, object>? checks = null, string? thread_id = null, string? answered_by = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] bool already_answered = false);

/// <summary>The agent: Microsoft Agent Framework with approval-required tools, a session, limits and OpenTelemetry.
/// A run is kept in the state database (Durable.cs) under its thread; one that waits for a person is kept with the call
/// it waits on, so AnswerAsync finishes it from any process: after a restart, a deploy, or from the HTTP interface.</summary>
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
            ? Client().AsAIAgent(model: model ?? Policy.Model, name: options.Name, instructions: null, tools: tools,
                    // The system prompt goes in as a cached block: the breakpoint covers the tools before it, so every turn reuses both.
                    clientFactory: inner => inner.AsBuilder().ConfigureOptions(o => o.MaxOutputTokens ??= Policy.MaxOutputTokens)
                        .Use((messages, chatOptions, next, ct) => next(messages.Prepend(CachedSystem()), chatOptions, ct)).Build())
            : new StubChatClient([.. tools.Select(t => t.Name)]).AsAIAgent(options);
        // Spans for every agent run, model call and tool call. Prompts and results stay out of traces.
        return agent.AsBuilder().UseOpenTelemetry(Policy.TelemetrySource, o => o.EnableSensitiveData = false).Build();
    }

    /// <summary>The live model's client: the model gateway with the gateway's key when it is on (gateway/litellm.yaml),
    /// else the Anthropic API with ANTHROPIC_API_KEY.</summary>
    private static AnthropicClient Client() => Gateway.On
        ? new AnthropicClient { BaseUrl = Gateway.Url, AuthToken = Gateway.Key() }
        : new AnthropicClient { ApiKey = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY") ?? throw new InvalidOperationException("Set ANTHROPIC_API_KEY for live runs.") };

    private static readonly ActivitySource Source = new(Policy.TelemetrySource);

    /// <summary>approve: true or false answers the approval request; null leaves it waiting (keep the session to resume).
    /// role and actor say who is asking (defaults: Policy.Role and Policy.Actor); the run goes to the audit log.</summary>
    public static async Task<RunResult> RunAsync(string message, bool? approve = null, AIAgent? agent = null, string? role = null, string? actor = null, string? thread = null)
    {
        string who = role ?? Policy.Role, by = actor ?? Policy.Actor, masked = Guardrails.Mask(message ?? "").Text, t = thread ?? Durable.NewThread();
        using IDisposable scope = Durable.Enter(t);
        using IDisposable caller = Access.Enter(who, by);
        RunResult result;
        try
        {
            result = await GuardedAsync(message ?? "", approve, agent, who) with { role = who, thread_id = t };
        }
        catch (Exception e)   // a run that fails is recorded as failed, then thrown as before
        {
            RunResult failed = new("", [], new() { ["input_tokens"] = 0, ["output_tokens"] = 0 }, false, outcome: "failed", thread_id: t);
            Record(by, who, masked, failed, t, e.GetType().Name);
            Durable.Save(t, "failed", masked, who, by, [], null, null);
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

        Record(by, who, masked, result, t);   // go-live gate 5
        Keep(t, result, masked, who, by);
        return result;
    }

    /// <summary>The run in the state database: what waits is kept with its calls, a finished run with its result.</summary>
    private static void Keep(string thread, RunResult r, string message, string role, string actor, string? answeredBy = null) =>
        Durable.Save(thread, r.awaiting_approval ? "awaiting_approval" : "done", message, role, actor, r.tool_calls,
            r.awaiting_approval ? null : JsonSerializer.Serialize(r), answeredBy);

    /// <summary>A person's answer to a run that waits, from this process or any other: approve runs the call exactly as it
    /// was asked for, once, through the same tool; no runs nothing. Who asked, and in which role, come from the saved run,
    /// never from whoever answers. A run already answered returns what it returned then.</summary>
    public static async Task<RunResult> AnswerAsync(string thread, bool approve, string? approver = null)
    {
        Durable.Saved saved = Durable.Load(thread) ?? throw new KeyNotFoundException($"no run {thread} in the state database");
        if (saved.status != "awaiting_approval")
        {
            RunResult before = saved.answer is { } a ? JsonSerializer.Deserialize<RunResult>(a)!
                : new RunResult("", saved.calls, new() { ["input_tokens"] = 0, ["output_tokens"] = 0 }, false, outcome: saved.status, ai_notice: Guardrails.AiNotice);
            return before with { thread_id = thread, already_answered = true };
        }

        string by = approver ?? saved.actor;
        using IDisposable scope = Durable.Enter(thread);
        using IDisposable caller = Access.Enter(saved.role, saved.actor);
        Dictionary<string, AIFunction> tools = Tools.All().OfType<AIFunction>().ToDictionary(f => f.Name);
        List<ToolCall> calls = [];
        foreach (ToolCall c in saved.calls)
        {
            if (c.status != "pending")
            {
                calls.Add(c);
                continue;
            }

            if (!approve)
            {
                calls.Add(c with { status = "denied" });
                continue;
            }

            AIFunction tool = tools.TryGetValue(c.name, out AIFunction? f) ? f : throw new InvalidOperationException($"run {thread} waits on {c.name}, which is not on this agent's tool list");
            object? done = await tool.InvokeAsync(new AIFunctionArguments(c.args ?? new Dictionary<string, object?>()));
            calls.Add(c with { status = "ok", result = done is JsonElement je ? je.Clone() : JsonSerializer.SerializeToElement(done) });
        }

        Guardrails.Screened output = Guardrails.ScreenOutput(Policy.AfterApproval(calls, approve));
        RunResult result = new(output.Text, calls, new() { ["input_tokens"] = 0, ["output_tokens"] = 0 }, false, new() { ["input"] = [], ["output"] = output.Findings },
            Guardrails.AiNotice, false, saved.role, thread_id: thread, answered_by: by);
        List<JsonElement> effects = Guardrails.Effects(calls);
        result = result with { effects = effects, outcome = Guardrails.Outcome(result with { effects = effects }, false) };
        if (result.outcome is "acted" or "answered" or "declined")
        {
            List<string> sources = [saved.message, Policy.System, .. calls.Where(c => c.result is not null).Select(c => c.result!.Value.GetRawText())];
            List<string> bad = Guardrails.Ungrounded(result.output, sources);
            result = result with { checks = new() { ["grounded"] = bad.Count == 0, ["ungrounded"] = bad.Count } };
        }

        Record(by, saved.role, saved.message, result, thread);
        Keep(thread, result, saved.message, saved.role, saved.actor, by);
        return result;
    }

    /// <summary>One audit line per tool call and one for the run: masked arguments, never the reply or the message itself.
    /// The run line carries what the live monitor scores: how it ended, what it changed, whether the reply was grounded.</summary>
    private static void Record(string actor, string role, string message, RunResult r, string runId, string? error = null)
    {
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
        using Activity? run = Source.StartActivity("agent.run");     // the framework's spans and the gateway's record nest under it
        if (Durable.Thread is { } thread) run?.SetTag("langfuse.session.id", thread);
        if (Gateway.ContentInTraces) run?.SetTag("langfuse.observation.input", message);
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
        run?.SetTag("agent.tool_calls", string.Join(",", calls.Select(c => $"{c.name}:{c.status}")));
        run?.SetTag("gen_ai.usage.input_tokens", usage["input_tokens"]);
        run?.SetTag("gen_ai.usage.output_tokens", usage["output_tokens"]);
        if (Gateway.ContentInTraces) run?.SetTag("langfuse.observation.output", output.Text);
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
