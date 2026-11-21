/** OpenTelemetry tracing: one span per run, with the tool calls as events. Spans go to OTEL_EXPORTER_OTLP_ENDPOINT
 *  when it is set, to stderr as JSON lines when AGENT_TRACE=console, and nowhere otherwise, so tests stay quiet.
 *  No message text goes into a span: counts, names and statuses only. */
import { trace, type Tracer } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor, SimpleSpanProcessor, TracerProvider, type ReadableSpan, type SpanExporter, type SpanProcessor } from "@opentelemetry/sdk-trace";

/** Writes finished spans to stderr, never stdout: stdout carries the agent's JSON answer to the eval adapter. */
class StderrExporter implements SpanExporter {
  export(spans: ReadableSpan[], done: Parameters<SpanExporter["export"]>[1]): void {
    for (const s of spans) {
      const ms = s.duration[0] * 1e3 + s.duration[1] / 1e6;
      process.stderr.write(JSON.stringify({ span: s.name, trace_id: s.spanContext().traceId, ms: Math.round(ms), status: s.status.code, attributes: s.attributes, events: s.events.map((e) => ({ name: e.name, ...e.attributes })) }) + "\n");
    }
    done({ code: 0 });                     // ExportResultCode.SUCCESS
  }
  shutdown(): Promise<void> {
    return Promise.resolve();
  }
}

let provider: TracerProvider | undefined;

export function tracer(): Tracer {
  if (!provider) {
    const processors: SpanProcessor[] = [];
    if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) processors.push(new BatchSpanProcessor({ exporter: new OTLPTraceExporter() }));
    else if (process.env.AGENT_TRACE === "console") processors.push(new SimpleSpanProcessor({ exporter: new StderrExporter() }));
    provider = new TracerProvider({ resource: resourceFromAttributes({ "service.name": "__SLUG__" }), spanProcessors: processors });
    trace.setGlobalTracerProvider(provider);
  }
  return trace.getTracer("__SLUG__");
}

/** Send what is still buffered before the process exits. */
export async function flush(): Promise<void> {
  await provider?.forceFlush();
}
