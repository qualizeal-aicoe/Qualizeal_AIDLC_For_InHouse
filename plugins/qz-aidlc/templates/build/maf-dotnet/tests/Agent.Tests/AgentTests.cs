using OrderAgent;

namespace Agent.Tests;

/// <summary>Wiring tests against the offline stub: tools, approval and limits. No key, no network.</summary>
public class AgentTests
{
    public AgentTests() => Environment.SetEnvironmentVariable("AGENT_MODE", "stub");

    [Fact]
    public async Task Lookup_calls_the_read_tool_only()
    {
        RunResult r = await OrderSupport.RunAsync("Where is my order ORD-1001?");
        Assert.Equal(["get_order"], r.tool_calls.Select(c => c.name));
        Assert.Contains("shipped", r.output);
    }

    [Fact]
    public async Task Refund_waits_for_a_person()
    {
        RunResult r = await OrderSupport.RunAsync("ORD-1002 arrived damaged. Please refund it.");
        Assert.True(r.awaiting_approval);
        Assert.Equal("pending", r.tool_calls[^1].status);
    }

    [Fact]
    public async Task Approved_refund_runs_and_declined_refund_does_not()
    {
        RunResult ok = await OrderSupport.RunAsync("ORD-1002 arrived damaged. Please refund it.", approve: true);
        Assert.Matches(@"RF-\d+", ok.output);
        RunResult denied = await OrderSupport.RunAsync("ORD-1002 arrived damaged. Please refund it.", approve: false);
        Assert.Equal("denied", denied.tool_calls[^1].status);
        Assert.DoesNotMatch(@"RF-\d+", denied.output);
    }

    [Fact]
    public void Every_side_effecting_tool_is_wrapped_for_approval()
    {
        var gated = Tools.All().OfType<Microsoft.Extensions.AI.ApprovalRequiredAIFunction>().Select(t => t.Name).ToHashSet();
        Assert.True(Policy.NeedsApproval.SetEquals(gated));
    }
}
