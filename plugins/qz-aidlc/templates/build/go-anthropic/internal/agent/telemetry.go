package agent

import (
	"context"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// Tracing registers a tracer provider: Run adds agent.run, each tool call a span of its own. Spans go to
// OTEL_EXPORTER_OTLP_ENDPOINT (a collector, or Langfuse's OTLP endpoint) when it is set, to stderr when
// AGENT_TRACE=console, and nowhere otherwise; the provider is there either way, so the run's trace context reaches the
// model gateway. No message text goes into a span unless AGENT_TRACE_CONTENT=1.
func Tracing() func() {
	opts := []sdktrace.TracerProviderOption{sdktrace.WithResource(resource.NewSchemaless(attribute.String("service.name", "__SLUG__")))}
	if os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") != "" {
		if exp, err := otlptracehttp.New(context.Background()); err == nil { // endpoint and headers from the OTEL_* variables
			opts = append(opts, sdktrace.WithBatcher(exp))
		}
	} else if os.Getenv("AGENT_TRACE") == "console" {
		if exp, err := stdouttrace.New(stdouttrace.WithWriter(os.Stderr)); err == nil {
			opts = append(opts, sdktrace.WithBatcher(exp))
		}
	}
	tp := sdktrace.NewTracerProvider(opts...)
	otel.SetTracerProvider(tp)
	return func() { _ = tp.Shutdown(context.Background()) }
}

// runTool runs one tool in a span named for it. Its arguments and result stay out of the trace: they can hold people's data.
func runTool(ctx context.Context, t Tool, args map[string]any) map[string]any {
	ctx, span := otel.Tracer("__SLUG__").Start(ctx, "tool "+t.Name, trace.WithAttributes(
		attribute.String("gen_ai.operation.name", "execute_tool"), attribute.String("gen_ai.tool.name", t.Name)))
	defer span.End()
	return t.Run(ctx, args)
}
