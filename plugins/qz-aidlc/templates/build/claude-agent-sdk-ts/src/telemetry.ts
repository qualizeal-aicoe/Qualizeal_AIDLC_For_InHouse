/** OpenTelemetry tracing: one span per run, with the tool calls as events. Spans go to OTEL_EXPORTER_OTLP_ENDPOINT
 *  when it is set, to stderr as JSON lines when AGENT_TRACE=console, and nowhere otherwise, so tests stay quiet.
 *  No message text goes into a span: counts, names and statuses only. */
import { context, ROOT_CONTEXT, trace, type Context, type ContextManager, type Tracer } from "@opentelemetry/api";
import { AsyncLocalStorage } from "node:async_hooks";
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

/** Keeps the active span across awaits, so a tool call's span and the gateway's trace context belong to the run. */
class AsyncContext implements ContextManager {
  private store = new AsyncLocalStorage<Context>();
  active(): Context {
    return this.store.getStore() ?? ROOT_CONTEXT;
  }
  with<A extends unknown[], F extends (...args: A) => ReturnType<F>>(ctx: Context, fn: F, thisArg?: ThisParameterType<F>, ...args: A): ReturnType<F> {
    return this.store.run(ctx, () => fn.apply(thisArg, args));
  }
  bind<T>(ctx: Context, target: T): T {
    if (typeof target !== "function") return target;
    const self = this;
    return function (this: unknown, ...args: unknown[]) {
      return self.with(ctx, () => (target as (...a: unknown[]) => unknown).apply(this, args));
    } as T;
  }
  enable(): this {
    return this;
  }
  disable(): this {
    this.store.disable();
    return this;
  }
}

let provider: TracerProvider | undefined;

export function tracer(): Tracer {
  if (!provider) {
    const processors: SpanProcessor[] = [];
    if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) processors.push(new BatchSpanProcessor({ exporter: new OTLPTraceExporter() }));
    else if (process.env.AGENT_TRACE === "console") processors.push(new SimpleSpanProcessor({ exporter: new StderrExporter() }));
    provider = new TracerProvider({ resource: resourceFromAttributes({ "service.name": "__SLUG__" }), spanProcessors: processors });
    context.setGlobalContextManager(new AsyncContext());
    trace.setGlobalTracerProvider(provider);
  }
  return trace.getTracer("__SLUG__");
}

/** One span per tool call, named for the tool. Its arguments and result stay out of the trace: they can hold people's data. */
export function traced<A, R>(name: string, fn: (args: A) => Promise<R>): (args: A) => Promise<R> {
  return (args) => tracer().startActiveSpan(`tool ${name}`, { attributes: { "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name } },
    async (span) => {
      try {
        return await fn(args);
      } finally {
        span.end();
      }
    });
}

/** Send what is still buffered before the process exits. */
export async function flush(): Promise<void> {
  await provider?.forceFlush();
}
