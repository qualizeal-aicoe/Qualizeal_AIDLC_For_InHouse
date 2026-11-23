using System.Text.Json;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using OrderAgent;

// Tracing: console when AGENT_TRACE=console, a collector when OTEL_EXPORTER_OTLP_ENDPOINT is set.
TracerProviderBuilder tracing = Sdk.CreateTracerProviderBuilder()
    .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService(Policy.TelemetrySource))
    .AddSource(Policy.TelemetrySource);
if (Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT") is { Length: > 0 }) tracing.AddOtlpExporter();
else if (Environment.GetEnvironmentVariable("AGENT_TRACE") == "console") tracing.AddConsoleExporter(o => o.Targets = OpenTelemetry.Exporter.ConsoleExporterOutputTargets.Debug);
using TracerProvider provider = tracing.Build();

if (args.Contains("--eval"))
{
    // Evaluation adapter: one case in on stdin, one JSON result out on stdout.
    using JsonDocument doc = JsonDocument.Parse(await Console.In.ReadToEndAsync());
    JsonElement input = doc.RootElement.GetProperty("input");
    string message = input.ValueKind == JsonValueKind.String ? input.GetString()! : input.GetProperty("message").GetString()!;
    bool? approve = input.ValueKind == JsonValueKind.Object && input.TryGetProperty("approve", out JsonElement a) && a.ValueKind is JsonValueKind.True or JsonValueKind.False ? a.GetBoolean() : null;
    string? role = input.ValueKind == JsonValueKind.Object && input.TryGetProperty("role", out JsonElement r) && r.ValueKind == JsonValueKind.String ? r.GetString() : null;
    Console.WriteLine(JsonSerializer.Serialize(await OrderSupport.RunAsync(message, approve, role: role)));
}
else
{
    string message = args.Length > 0 ? string.Join(' ', args) : "Where is my order ORD-1001?";
    Console.WriteLine(JsonSerializer.Serialize(await OrderSupport.RunAsync(message), new JsonSerializerOptions { WriteIndented = true }));
}
