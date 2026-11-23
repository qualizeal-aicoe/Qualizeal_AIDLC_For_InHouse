using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Extensions.AI;
using OpenTelemetry.Trace;
using OrderAgent;
using Xunit;

namespace Agent.Tests;

/// <summary>The model gateway (AGENT_GATEWAY=litellm): every model call goes to the gateway, by the gateway's model name,
/// with the gateway's key and the run's trace context; the agent refuses to start while it holds a provider key; the
/// tools, the approval gate and the limits are the same. A stand-in plays the gateway here (Anthropic's Messages API,
/// answering through the stub's rules); CI runs the real LiteLLM proxy.</summary>
public sealed class GatewayTests
{
    private sealed record Seen(string Model, string Auth, string ApiKey, string TraceParent);

    private sealed class Standin : IDisposable
    {
        private readonly HttpListener _listener = new();
        private readonly List<Seen> _calls = [];
        public string Url { get; }

        public Standin()
        {
            TcpListener probe = new(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            Url = $"http://127.0.0.1:{port}";
            _listener.Prefixes.Add(Url + "/");
            _listener.Start();
            _ = Task.Run(Loop);
        }

        public List<Seen> Calls { get { lock (_calls) return [.. _calls]; } }

        private async Task Loop()
        {
            while (_listener.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await _listener.GetContextAsync(); } catch { return; }
                using StreamReader reader = new(ctx.Request.InputStream);
                JsonNode req = JsonNode.Parse(await reader.ReadToEndAsync())!;
                lock (_calls) _calls.Add(new Seen((string?)req["model"] ?? "", ctx.Request.Headers["Authorization"] ?? "",
                    ctx.Request.Headers["x-api-key"] ?? "", ctx.Request.Headers["traceparent"] ?? ""));
                List<ChatMessage> messages = [];
                foreach (JsonNode? m in req["messages"]!.AsArray())
                {
                    ChatRole role = (string?)m!["role"] == "assistant" ? ChatRole.Assistant : ChatRole.User;
                    List<AIContent> contents = [];
                    JsonNode content = m["content"]!;
                    if (content is JsonValue) contents.Add(new TextContent((string?)content));
                    else foreach (JsonNode? b in content.AsArray())
                        {
                            switch ((string?)b!["type"])
                            {
                                case "text": contents.Add(new TextContent((string?)b["text"])); break;
                                case "tool_use":
                                    contents.Add(new FunctionCallContent((string)b["id"]!, (string)b["name"]!,
                                        b["input"].Deserialize<Dictionary<string, object?>>())); break;
                                case "tool_result":
                                    JsonNode? c = b["content"];
                                    string text = c is JsonArray a ? string.Concat(a.Select(x => (string?)x?["text"])) : (string?)c ?? "";
                                    contents.Add(new FunctionResultContent((string)b["tool_use_id"]!, JsonDocument.Parse(text).RootElement.Clone())); break;
                            }
                        }
                    messages.Add(new ChatMessage(role, contents));
                }
                string[] given = [.. (req["tools"]?.AsArray() ?? []).Select(t => (string)t!["name"]!)];
                ChatResponse r = await new StubChatClient(given).GetResponseAsync(messages);
                FunctionCallContent? call = r.Messages.SelectMany(x => x.Contents).OfType<FunctionCallContent>().FirstOrDefault();
                object block = call is not null
                    ? new { type = "tool_use", id = call.CallId, name = call.Name, input = call.Arguments }
                    : new { type = "text", text = r.Text };
                byte[] body = JsonSerializer.SerializeToUtf8Bytes(new
                {
                    id = "msg_test", type = "message", role = "assistant", model = (string?)req["model"], content = new[] { block },
                    stop_reason = call is not null ? "tool_use" : "end_turn", stop_sequence = (string?)null,
                    usage = new { input_tokens = r.Usage?.InputTokenCount ?? 40, output_tokens = r.Usage?.OutputTokenCount ?? 12 },
                });
                ctx.Response.ContentType = "application/json";
                ctx.Response.ContentLength64 = body.Length;
                await ctx.Response.OutputStream.WriteAsync(body);
                ctx.Response.Close();
            }
        }

        public void Dispose() => _listener.Close();
    }

    private sealed class Env : IDisposable
    {
        private readonly Dictionary<string, string?> _before = [];

        public Env(Dictionary<string, string?> set)
        {
            foreach ((string k, string? v) in set)
            {
                _before[k] = Environment.GetEnvironmentVariable(k);
                Environment.SetEnvironmentVariable(k, v);
            }
        }

        public void Dispose()
        {
            foreach ((string k, string? v) in _before) Environment.SetEnvironmentVariable(k, v);
        }
    }

    private static Env WithGateway(string url, Dictionary<string, string?>? extra = null)
    {
        Dictionary<string, string?> set = Gateway.ProviderKeys.ToDictionary(k => k, _ => (string?)null);
        set["AGENT_MODE"] = "live";
        set["AGENT_GATEWAY"] = "litellm";
        set["AGENT_GATEWAY_URL"] = url;
        set["AGENT_GATEWAY_KEY"] = "sk-gateway-test";
        set["AGENT_GATEWAY_MODEL_SMALL"] = null;
        foreach ((string k, string? v) in extra ?? []) set[k] = v;
        return new Env(set);
    }

    public GatewayTests() => Setup.Fresh();

    [Fact]
    public async Task AQuestionGoesThroughTheGatewayWithItsKeyAndTheTrace()
    {
        using Standin s = new();
        using Env env = WithGateway(s.Url);
        using TracerProvider tracing = Telemetry.Start();     // the run's activity, whose context HttpClient sends
        RunResult r = await OrderSupport.RunAsync("Where is my order ORD-1001?");
        Assert.Contains("shipped", r.output);
        Assert.Equal(["get_order"], r.tool_calls.Select(c => c.name));
        Assert.NotEmpty(s.Calls);
        Assert.All(s.Calls, c =>
        {
            Assert.Equal("agent-model", c.Model);                   // the gateway's name: the gateway picks the provider
            Assert.Equal("Bearer sk-gateway-test", c.Auth);
            Assert.Equal("", c.ApiKey);
            Assert.StartsWith("00-", c.TraceParent);                // the gateway files the call inside the run's trace
        });
    }

    [Fact]
    public async Task ARefundThroughTheGatewayStillWaitsForAPerson()
    {
        using Standin s = new();
        using Env env = WithGateway(s.Url);
        RunResult r = await OrderSupport.RunAsync("ORD-1002 arrived damaged. Please refund it.");
        Assert.True(r.awaiting_approval);
        Assert.Equal("pending", r.tool_calls[^1].status);
        Assert.DoesNotContain("RF-", r.output);
    }

    [Fact]
    public async Task AnEasyQuestionCanGoToTheGatewaysSmallModel()
    {
        using Standin s = new();
        using Env env = WithGateway(s.Url, new() { ["AGENT_GATEWAY_MODEL_SMALL"] = "agent-model-small" });
        await OrderSupport.RunAsync("Where is my order ORD-1001?");
        await OrderSupport.RunAsync("ORD-1002 arrived damaged. Please refund it.");
        Assert.Equal("agent-model-small", s.Calls[0].Model);
        Assert.Equal("agent-model", s.Calls[^1].Model);
    }

    [Theory]
    [InlineData("ANTHROPIC_API_KEY")]
    [InlineData("OPENAI_API_KEY")]
    [InlineData("AWS_SECRET_ACCESS_KEY")]
    public async Task TheAgentWillNotHoldAProviderKeyBehindTheGateway(string held)
    {
        using Standin s = new();
        using Env env = WithGateway(s.Url, new() { [held] = "sk-not-for-the-agent" });
        InvalidOperationException e = await Assert.ThrowsAsync<InvalidOperationException>(() => OrderSupport.RunAsync("Where is my order ORD-1001?"));
        Assert.Contains("gateway holds the provider keys", e.Message);
        Assert.Empty(s.Calls);
    }
}
