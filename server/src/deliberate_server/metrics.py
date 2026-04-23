"""Prometheus metrics for Deliberate server."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

INTERRUPTS_TOTAL = Counter(
    "deliberate_interrupts_total",
    "Total interrupts submitted",
    ["layout", "action"],  # action: request_human, auto_approve
)

DECISIONS_TOTAL = Counter(
    "deliberate_decisions_total",
    "Total decisions made",
    ["decision_type"],  # approve, modify, reject, escalate
)

APPROVAL_DURATION = Histogram(
    "deliberate_approval_duration_seconds",
    "Time from approval creation to decision",
    buckets=[10, 30, 60, 300, 600, 1800, 3600, 7200, 14400, 43200, 86400],
)

TIMEOUTS_TOTAL = Counter(
    "deliberate_timeouts_total",
    "Total approval timeouts",
)

ESCALATIONS_TOTAL = Counter(
    "deliberate_escalations_total",
    "Total approval escalations",
)
