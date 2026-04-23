"""OpenTelemetry integration for ledger event export.

Exports ledger events as OTLP spans so they can feed into Langfuse, Phoenix,
or any OTLP-compatible collector. Disabled by default — only active when
OTEL_EXPORTER_OTLP_ENDPOINT is set.
"""

from __future__ import annotations

import os
from typing import Any

_tracer = None


def _init_tracer() -> Any:
    """Lazy-initialize the OpenTelemetry tracer."""
    global _tracer
    if _tracer is not None:
        return _tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        # No-op: return None, callers check for this
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": "deliberate-server"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("deliberate")
    return _tracer


def emit_ledger_span(ledger_content: dict[str, Any]) -> None:
    """Emit an OTLP span for a ledger entry."""
    tracer = _init_tracer()
    if tracer is None:
        return  # OTLP not configured

    approval = ledger_content.get("approval", {})
    with tracer.start_as_current_span("deliberate.ledger_entry") as span:
        span.set_attribute("deliberate.thread_id", ledger_content.get("thread_id", ""))
        span.set_attribute("deliberate.decision_type", approval.get("decision_type", ""))
        span.set_attribute("deliberate.approver", approval.get("approver_email", ""))
        span.set_attribute("deliberate.review_duration_ms", approval.get("review_duration_ms", 0))
        span.set_attribute(
            "deliberate.policy_name",
            ledger_content.get("policy_evaluation", {}).get("policy_name", ""),
        )
        span.set_attribute("deliberate.content_hash", ledger_content.get("content_hash", ""))
