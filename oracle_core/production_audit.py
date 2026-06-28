"""Production audit logging — immutable, no secrets, fail-closed.

Every audit record documents what happened during a production operation:
which modes were active, what data was requested/used, and what data gaps
were encountered.

**Safety invariants:**
  * ``probability_mutated`` is ALWAYS ``False`` (hard-clamped by the factory).
  * ``affects_model`` is ALWAYS ``False`` (hard-clamped by the factory).
  * ``raw_payload_saved`` defaults to ``False``.
  * ``source_references`` are redacted on output — no API keys or tokens
    leak into audit logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any


#: Regex that matches common credential patterns in source-reference strings.
#: Matches labels like ``api_key``, ``apikey``, ``token``, ``secret``,
#: ``password``, ``auth`` followed by a separator and a value.
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(api[_-]?key|apikey|key|token|secret|password|auth)"
    r"[=:]\s*"
    r"['\"]?"
    r"([a-zA-Z0-9_\-.]{8,})"
)


@dataclass(frozen=True)
class AuditRecord:
    """Immutable record of a single production operation.

    Every field documents the runtime state and data flows for one
    command/prediction/report cycle.
    """

    command_timestamp: datetime
    """UTC-aware timestamp of the command."""

    runtime_mode: str
    network_allowed: bool
    env_access_allowed: bool

    # ── Provider activity ──
    live_provider_requested: bool = False
    live_provider_used: bool = False

    # ── Web scout activity ──
    web_scout_requested: bool = False
    web_scout_used: bool = False

    # ── Odds activity ──
    odds_requested: bool = False
    odds_used: bool = False

    # ── Data flow ──
    model_output_supplied: bool = False
    context_snapshot_supplied: bool = False
    provider_gaps: tuple[str, ...] = ()
    scout_gaps: tuple[str, ...] = ()
    odds_gaps: tuple[str, ...] = ()

    # ── Output paths ──
    report_path: str = ""
    snapshot_reference: str = ""

    # ── Safety fields (hard-clamped by factory) ──
    probability_mutated: bool = False
    """MUST ALWAYS BE FALSE — model probability mutation is prohibited."""

    affects_model: bool = False
    """MUST ALWAYS BE FALSE — audit must not affect model output."""

    raw_payload_saved: bool = False
    """MUST ALWAYS BE FALSE by default — live payloads are never committed."""

    source_references: tuple[str, ...] = ()
    """MUST BE REDACTED before output — no API keys or tokens."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        if self.command_timestamp.tzinfo is None or self.command_timestamp.utcoffset() is None:
            raise ValueError("command_timestamp must be timezone-aware")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict with source references redacted."""
        return {
            "command_timestamp": self.command_timestamp.isoformat(),
            "runtime_mode": self.runtime_mode,
            "network_allowed": self.network_allowed,
            "env_access_allowed": self.env_access_allowed,
            "live_provider_requested": self.live_provider_requested,
            "live_provider_used": self.live_provider_used,
            "web_scout_requested": self.web_scout_requested,
            "web_scout_used": self.web_scout_used,
            "odds_requested": self.odds_requested,
            "odds_used": self.odds_used,
            "model_output_supplied": self.model_output_supplied,
            "context_snapshot_supplied": self.context_snapshot_supplied,
            "provider_gaps": list(self.provider_gaps),
            "scout_gaps": list(self.scout_gaps),
            "odds_gaps": list(self.odds_gaps),
            "report_path": self.report_path,
            "snapshot_reference": self.snapshot_reference,
            "probability_mutated": self.probability_mutated,
            "affects_model": self.affects_model,
            "raw_payload_saved": self.raw_payload_saved,
            "source_references": [redact_source_reference(r) for r in self.source_references],
        }


# ------------------------------------------------------------------
# Source-reference redaction
# ------------------------------------------------------------------


def redact_source_reference(ref: str) -> str:
    """Replace credential values in a source-reference string with ``<redacted>``.

    Matches common credential labels (``api_key``, ``token``, ``secret``,
    ``password``, ``auth``, etc.) followed by a value and replaces the
    value with ``<redacted>``.

    Examples
    --------
    >>> redact_source_reference("https://api.example.com?api_key=abc123def456")
    'https://api.example.com?api_key=<redacted>'

    >>> redact_source_reference("token=ghijk789")
    'token=<redacted>'

    >>> redact_source_reference("clean-reference-path")
    'clean-reference-path'
    """
    return _CREDENTIAL_PATTERN.sub(r"\1=<redacted>", ref)


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def create_audit_record(**kwargs: Any) -> AuditRecord:
    """Create an ``AuditRecord`` with hard safety defaults.

    **Hard-clamped fields (always overridden):**
      * ``probability_mutated`` → ``False``  (cannot be overridden)
      * ``affects_model``       → ``False``  (cannot be overridden)

    If ``command_timestamp`` is not provided, ``datetime.now(timezone.utc)``
    is used.
    """
    if "command_timestamp" not in kwargs:
        kwargs["command_timestamp"] = datetime.now(timezone.utc)

    kwargs["probability_mutated"] = False
    kwargs["affects_model"] = False
    return AuditRecord(**kwargs)


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------


def audit_to_dict(record: AuditRecord) -> dict[str, Any]:
    """Convert an ``AuditRecord`` to a plain dict (source refs redacted)."""
    return record.to_dict()


def audit_to_json(record: AuditRecord, **json_kwargs: Any) -> str:
    """Convert an ``AuditRecord`` to a JSON string (source refs redacted).

    Accepts additional ``json.dumps`` keyword arguments such as ``indent``.
    """
    return json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, **json_kwargs)
