package agent

import (
	"context"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// Tracing registers a tracer provider. The Anthropic SDK emits a span for each request on it; Run adds agent.run.
// Spans go to stderr when AGENT_TRACE=console. For a collector, swap the exporter for otlptracehttp.
func Tracing() func() {
	if os.Getenv("AGENT_TRACE") != "console" {
		return func() {}
	}
	exp, err := stdouttrace.New(stdouttrace.WithWriter(os.Stderr))
	if err != nil {
		return func() {}
	}
	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exp))
	otel.SetTracerProvider(tp)
	return func() { _ = tp.Shutdown(context.Background()) }
}
