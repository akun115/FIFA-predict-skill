"""Monitoring and alerting hooks — Patch 38.

All alerts are created with ``sent=False`` and default to stdout sink.
External sinks (file, webhook, slack, email) are stubs only and return
``"sink_not_configured"`` — no network is ever called by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------


AlertSeverity = Literal["info", "warning", "error", "critical"]
"""Allowed severity levels for alert events."""


@dataclass(frozen=True)
class AlertEvent:
    """A single alert event.

    Every alert is created with ``sent=False`` and defaults to a
    ``"stdout"`` sink.  External sinks are stubs only.
    """

    alert_id: str
    severity: AlertSeverity
    component: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sent: bool = False
    sink: str = "stdout"

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        valid_severities = ("info", "warning", "error", "critical")
        if self.severity not in valid_severities:
            raise ValueError(
                f"severity must be one of {valid_severities}, got {self.severity!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity,
            "component": self.component,
            "message": self.message,
            "details": dict(self.details),
            "generated_at": self.generated_at.isoformat(),
            "sent": self.sent,
            "sink": self.sink,
        }


@dataclass(frozen=True)
class AlertSink:
    """Protocol or specification for an alert delivery sink.

    External sinks are stubs only — they record the intended destination
    but never actually deliver.
    """

    sink_type: str
    """One of ``stdout``, ``file``, ``webhook_stub``, ``slack_stub``,
    ``email_stub``."""

    target: str = ""
    """Path, URL, or address the sink would deliver to (stub value)."""

    configured: bool = False
    """``True`` only after the operator has completed setup."""


# ------------------------------------------------------------------
# Alert lifecycle
# ------------------------------------------------------------------

_alert_counter: int = 0


def _next_alert_id() -> str:
    global _alert_counter
    _alert_counter += 1
    return f"alert-{_alert_counter:04d}"


def create_alert(
    severity: AlertSeverity,
    component: str,
    message: str,
    **details: Any,
) -> AlertEvent:
    """Create an ``AlertEvent`` with ``sent=False``.

    Parameters
    ----------
    severity:
        One of ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
    component:
        Name of the component that generated the alert.
    message:
        Human-readable alert message.
    **details:
        Additional structured context (no secrets).
    """
    return AlertEvent(
        alert_id=_next_alert_id(),
        severity=severity,
        component=component,
        message=message,
        details=details,
        sent=False,
        sink="stdout",
    )


def send_alert(event: AlertEvent, sink: str = "stdout") -> str:
    """Send an alert event to the specified sink.

    Parameters
    ----------
    event:
        The alert to send.
    sink:
        Destination.  ``"stdout"`` prints the alert.  All other sinks
        return ``"sink_not_configured"`` without calling network.

    Returns
    -------
    str
        Status message.
    """
    if sink == "stdout":
        severity_tag = event.severity.upper()
        print(
            f"[ALERT][{severity_tag}][{event.component}] "
            f"{event.message}"
        )
        # Return a new instance with sent=True (frozen dataclass)
        return "sent_to_stdout"

    return "sink_not_configured"


# ------------------------------------------------------------------
# Convenience alert factories
# ------------------------------------------------------------------


def alert_provider_unavailable(provider_name: str) -> AlertEvent:
    """Create and send a WARNING alert for an unavailable provider."""
    event = create_alert(
        severity="warning",
        component="data_provider",
        message=f"Provider '{provider_name}' is unavailable.",
        provider_name=provider_name,
    )
    send_alert(event)
    return event


def alert_scout_unavailable() -> AlertEvent:
    """Create and send a WARNING alert for web scout unavailability."""
    event = create_alert(
        severity="warning",
        component="web_scout",
        message="Web scout is unavailable — no search results.",
    )
    send_alert(event)
    return event


def alert_odds_unavailable() -> AlertEvent:
    """Create and send a WARNING alert for odds unavailability."""
    event = create_alert(
        severity="warning",
        component="odds_provider",
        message="Odds provider is unavailable — market comparison disabled.",
    )
    send_alert(event)
    return event


def alert_healthcheck_degraded(issues: list[str]) -> AlertEvent:
    """Create a WARNING alert for healthcheck degradation.

    The alert is created but **not** sent automatically — the caller
    decides when/how to deliver it.
    """
    return create_alert(
        severity="warning",
        component="healthcheck",
        message=f"Healthcheck degraded: {'; '.join(issues)}",
        issues=list(issues),
    )


def alert_probability_mutation_attempted() -> AlertEvent:
    """Create a CRITICAL alert for a prohibited probability mutation.

    This is a **critical** safety violation and should be investigated
    immediately.
    """
    return create_alert(
        severity="critical",
        component="model_boundary",
        message="Prohibited probability mutation attempted — model "
        "integrity may be compromised.",
        mutation_blocked=True,
    )


# ------------------------------------------------------------------
# Sink listing & dry-run
# ------------------------------------------------------------------


def list_alert_sinks() -> tuple[str, ...]:
    """Return the available sink types.

    Only ``"stdout"`` is functional.  The remaining entries are stubs.
    """
    return ("stdout", "file", "webhook_stub", "slack_stub", "email_stub")


def dry_run_alert_system() -> list[AlertEvent]:
    """Test all alert types without sending to external sinks.

    Creates one instance of each alert factory and sends them all
    to stdout.  Returns the list of created events for inspection.
    """
    events: list[AlertEvent] = []

    events.append(
        create_alert("info", "dry_run", "Dry-run info alert — no action needed.")
    )
    send_alert(events[-1])

    events.append(
        create_alert(
            "warning",
            "dry_run",
            "Dry-run warning alert — no action needed.",
        )
    )
    send_alert(events[-1])

    events.append(
        create_alert(
            "error",
            "dry_run",
            "Dry-run error alert — no action needed.",
        )
    )
    send_alert(events[-1])

    events.append(
        create_alert(
            "critical",
            "dry_run",
            "Dry-run critical alert — no action needed.",
        )
    )
    send_alert(events[-1])

    events.append(alert_provider_unavailable("test_provider"))
    events.append(alert_scout_unavailable())
    events.append(alert_odds_unavailable())
    events.append(alert_healthcheck_degraded(["test issue"]))
    send_alert(events[-1])
    events.append(alert_probability_mutation_attempted())

    return events
