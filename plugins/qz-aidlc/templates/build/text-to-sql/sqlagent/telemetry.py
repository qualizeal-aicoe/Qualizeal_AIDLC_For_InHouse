"""OpenTelemetry tracing: a span per question (sql.ask) with a child span per step (sql.understand, sql.generate,
sql.guard, ...). Spans carry the outcome, the attempt, row counts, tables, tokens and the SQL with its text values
masked; never a result row.

Spans are dropped unless OTEL_EXPORTER_OTLP_ENDPOINT is set (they go to that collector) or SQLAGENT_TRACE=console
(they print to stderr). An app that embeds the agent and has its own tracer provider gets them in its traces."""
from __future__ import annotations

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
        if not isinstance(trace.get_tracer_provider(), TracerProvider):
            provider = TracerProvider(resource=Resource.create({"service.name": "__NAME__"}))
            if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            elif os.environ.get("SQLAGENT_TRACE") == "console":
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
            trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("sqlagent")
    return _tracer
