using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using OrderAgent;

namespace Agent.Tests;

/// <summary>The knowledge tool against a stand-in knowledge service: off until KNOWLEDGE_URL is set; on, it asks with the
/// person's identity and role in the proxy headers, says the answer with its source or that the documents do not say,
/// never calls a host that is not on Policy.AllowedHosts, and its answer goes through the same output filter as any
/// reply. No key, no network beyond this machine.</summary>
public sealed class KnowledgeTests : IAsyncDisposable
{
    private const string Question = "What is the refund window policy for damaged items?";

    private static readonly object Found = new
    {
        text = "Damaged items can be returned within 30 days of delivery.", refused = false,
        citations = new[] { new { doc_id = "returns", doc_title = "Returns policy", section = "Refund window", node_id = "n1" } },
    };

    private sealed record Seen(string Path, string? User, string? Groups, JsonElement Body);

    private readonly List<Seen> _calls = [];
    private object _answer = Found;
    private WebApplication? _service;
    private readonly string _dir = Setup.Fresh();

    public async ValueTask DisposeAsync()
    {
        if (_service is not null) await _service.DisposeAsync();
        Environment.SetEnvironmentVariable("KNOWLEDGE_URL", null);
    }

    private async Task Start()
    {
        WebApplicationBuilder b = WebApplication.CreateSlimBuilder();
        b.WebHost.UseUrls("http://127.0.0.1:0");
        _service = b.Build();
        _service.MapPost("/api/ask", async (HttpContext ctx) =>
        {
            JsonElement body = (await JsonDocument.ParseAsync(ctx.Request.Body)).RootElement.Clone();
            lock (_calls) _calls.Add(new(ctx.Request.Path, ctx.Request.Headers["X-Forwarded-User"], ctx.Request.Headers["X-Forwarded-Groups"], body));
            return Results.Json(_answer);
        });
        await _service.StartAsync();
        Environment.SetEnvironmentVariable("KNOWLEDGE_URL", _service.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First());
    }

    [Fact]
    public async Task Off_until_a_knowledge_service_is_set()
    {
        Environment.SetEnvironmentVariable("KNOWLEDGE_URL", null);
        Assert.False(Knowledge.On);
        Assert.DoesNotContain("search_knowledge", Access.ToolsFor("support", Tools.All()).Select(t => t.Name));
        RunResult r = await OrderSupport.RunAsync(Question);
        Assert.Empty(r.tool_calls);
        Assert.Contains("order number", r.output);
    }

    [Fact]
    public async Task A_policy_question_is_answered_from_the_documents_with_its_source()
    {
        await Start();
        RunResult r = await OrderSupport.RunAsync(Question, actor: "asha@example.com");
        Assert.Equal(["search_knowledge"], r.tool_calls.Select(c => c.name));
        Assert.Contains("30 days", r.output);
        Assert.Contains("Returns policy, Refund window", r.output);
        Assert.Equal("answered", r.outcome);
        Assert.True((bool)r.checks!["grounded"]);
        Seen call = Assert.Single(_calls);
        Assert.Equal("/api/ask", call.Path);
        Assert.Equal(Question, call.Body.GetProperty("question").GetString());
        Assert.Equal("asha@example.com", call.User);
        Assert.Equal("support", call.Groups);
    }

    [Fact]
    public async Task The_knowledge_service_applies_the_callers_role()
    {
        await Start();
        await OrderSupport.RunAsync(Question, role: "viewer", actor: "vic@example.com");
        Assert.Equal("viewer", _calls[^1].Groups);
        Assert.Equal("vic@example.com", _calls[^1].User);
    }

    [Fact]
    public async Task When_the_documents_do_not_say_the_agent_says_so_and_who_can_help()
    {
        await Start();
        _answer = new { refused = true, searched = new[] { "refund window" }, contact = "The support lead" };
        RunResult r = await OrderSupport.RunAsync(Question);
        Assert.Contains("do not say", r.output);
        Assert.Contains("The support lead can help", r.output);
    }

    [Fact]
    public async Task An_order_question_still_goes_to_the_order_tools()
    {
        await Start();
        RunResult r = await OrderSupport.RunAsync("Where is my order ORD-1001?");
        Assert.Equal(["get_order"], r.tool_calls.Select(c => c.name));
        Assert.Empty(_calls);
    }

    [Fact]
    public async Task A_host_not_on_the_allowed_list_is_never_called()
    {
        await Start();
        Environment.SetEnvironmentVariable("KNOWLEDGE_URL", "https://docs.example.com");
        JsonElement r = await Knowledge.AskAsync(Question, "asha@example.com", "support");
        Assert.False(r.GetProperty("found").GetBoolean());
        Assert.Contains("AllowedHosts", r.GetProperty("error").GetString());
        Assert.Empty(_calls);
        Assert.Contains("could not look that up", Knowledge.Reply(r));
    }

    [Fact]
    public async Task An_answer_goes_through_the_output_filter_like_any_reply()
    {
        await Start();
        _answer = new { text = "The card on file, 4111 1111 1111 1111, is refunded within 30 days.", refused = false,
            citations = new[] { new { doc_id = "returns", doc_title = "Returns policy", section = "Refund window" } } };
        RunResult r = await OrderSupport.RunAsync(Question);
        Assert.DoesNotContain("4111", r.output);
        Assert.Contains("[card number removed]", r.output);
    }

    [Fact]
    public async Task The_audit_log_records_the_lookup()
    {
        await Start();
        await OrderSupport.RunAsync(Question, actor: "asha@example.com");
        JsonElement[] lines = [.. File.ReadAllLines(Path.Combine(_dir, "audit.jsonl")).Select(l => JsonDocument.Parse(l).RootElement.Clone())];
        Assert.Equal(["tool", "run"], lines.Select(x => x.GetProperty("event").GetString()));
        Assert.Equal("search_knowledge", lines[0].GetProperty("tool").GetString());
    }
}
