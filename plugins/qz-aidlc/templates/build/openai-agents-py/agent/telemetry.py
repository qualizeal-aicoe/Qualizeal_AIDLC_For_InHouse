"""OpenTelemetry tracing. Spans go to the console unless OTEL_EXPORTER_OTLP_ENDPOINT is set."""
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_ready = False


def tracer():
    global _ready
    if not _ready:
        provider = TracerProvider(resource=Resource.create({"service.name": "__NAME__"}))
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        elif os.environ.get("AGENT_TRACE") == "console":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=__import__("sys").stderr)))
        trace.set_tracer_provider(provider)
        _ready = True
    return trace.get_tracer("__NAME__")


def tool_span(name: str):
    """One span per tool call, named for the tool. Its arguments and result stay out of the trace: they can hold people's data."""
    return tracer().start_as_current_span(f"tool {name}", attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name})
