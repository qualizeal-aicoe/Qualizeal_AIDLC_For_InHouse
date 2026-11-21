"""OpenTelemetry tracing: one span per memory call, carrying what happened (decisions, counts, tokens, and the number
of its audit record, which links a trace to the audit log) and never what was said. The person's id is a pseudonym.

Spans are dropped unless OTEL_EXPORTER_OTLP_ENDPOINT is set (they go to that collector) or MEM_TRACE=console (they
print to stderr). An app that embeds the memory and has set up its own tracer provider gets the spans in its traces."""
from __future__ import annotations

import hashlib
import os
import sys

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_tracer = None


def tracer():
    global _tracer
    if _tracer is None:
        if not isinstance(trace.get_tracer_provider(), TracerProvider):     # nobody set one up: use ours
            provider = TracerProvider(resource=Resource.create({"service.name": "__NAME__ memory"}))
            if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            elif os.environ.get("MEM_TRACE") == "console":
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
            trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("mem")
    return _tracer


def pseudonym(user: str) -> str:
    """Stable per person, so one person's calls can be followed; not their id. Still personal data under most laws."""
    return hashlib.sha256(("mem:" + str(user)).encode("utf-8")).hexdigest()[:16]


def record(action: str, seq: int, detail: dict) -> None:
    """Add what the audit record says to the current span: numbers and decisions only, never text."""
    span = trace.get_current_span()
    span.set_attribute("memory.action", action)
    span.set_attribute("memory.audit_seq", seq)
    for k, v in detail.items():
        if isinstance(v, (bool, int, float)):
            span.set_attribute(f"memory.{k}", v)
        elif k == "decisions":
            span.set_attribute("memory.decisions", [str(d.get("decision", "")) for d in v])
        elif k == "ids":
            span.set_attribute("memory.hits", len(v))
        elif k == "removed":
            span.set_attribute("memory.removed", [str(x) for x in v])
        elif k == "category":
            span.set_attribute("memory.category", str(v))
        elif k == "usage" and v:
            span.set_attribute("gen_ai.usage.input_tokens", int(v.get("input_tokens", 0)))
            span.set_attribute("gen_ai.usage.output_tokens", int(v.get("output_tokens", 0)))
