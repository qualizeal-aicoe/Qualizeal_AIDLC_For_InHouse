using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace OrderAgent;

/// <summary>Tracing: console when AGENT_TRACE=console, a collector when OTEL_EXPORTER_OTLP_ENDPOINT is set.</summary>
public static class Telemetry
{
    public static TracerProvider Start()
    {
        TracerProviderBuilder tracing = Sdk.CreateTracerProviderBuilder()
            .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService(Policy.TelemetrySource))
            .AddSource(Policy.TelemetrySource);
        if (Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT") is { Length: > 0 }) tracing.AddOtlpExporter();
        else if (Environment.GetEnvironmentVariable("AGENT_TRACE") == "console") tracing.AddConsoleExporter(o => o.Targets = OpenTelemetry.Exporter.ConsoleExporterOutputTargets.Debug);
        return tracing.Build();
    }
}
