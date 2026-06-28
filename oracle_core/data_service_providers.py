"""Provider adapter interface and deterministic fake provider — Data Service v1.

Patch 15 — provider interface + fake provider only.
No live API. No network. No local store. No snapshot writer/reader.
No prediction engine integration. No real data.

IMPORTANT — Model Input Boundary (v1):
  Provider adapters fetch *source-shaped* raw data with provenance.
  Normalization into canonical entities and snapshot creation are later
  patches (16/17).  Provider data — especially odds, lineups, injuries,
  suspensions, and prematch signals — MUST NOT be used to modify model
  probabilities at any stage of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from oracle_core.data_service_types import (
    DataQualitySeverity,
    ProviderProvenance,
    _fixed_datetime,
    _synthetic_hash,
)


# ---------------------------------------------------------------------------
# Provider capability
# ---------------------------------------------------------------------------


class ProviderCapability(str, Enum):
    """What kind of data a provider can supply.

    A provider may support zero or more capabilities.
    """

    TEAMS = "teams"
    MATCHES = "matches"
    GROUP_STANDINGS = "group_standings"
    KNOCKOUT_BRACKET = "knockout_bracket"
    ODDS = "odds"
    LINEUPS = "lineups"
    INJURIES = "injuries"
    SUSPENSIONS = "suspensions"
    PREMATCH_SIGNALS = "prematch_signals"


# ---------------------------------------------------------------------------
# Provider descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderDescriptor:
    """Metadata about a provider adapter.

    Mirrors the pattern established in ``football_data/providers/base.py``
    but extended for the full Data Service v1 capability set.
    """

    name: str
    """Unique provider identifier, e.g. ``"fake_provider_v1"``."""

    adapter_version: str
    """Version of this adapter, e.g. ``"1.0.0"``."""

    capabilities: frozenset[ProviderCapability] = frozenset()
    """Capabilities this provider supports."""

    requires_credentials: bool = False
    """Whether this provider needs API keys or tokens."""

    attribution_url: str = ""
    """URL or reference for attribution / licensing."""

    enabled: bool = True
    """Whether this provider is currently active."""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "adapter_version": self.adapter_version,
            "capabilities": sorted(c.value for c in self.capabilities),
            "requires_credentials": self.requires_credentials,
            "attribution_url": self.attribution_url,
            "enabled": self.enabled,
        }


# ---------------------------------------------------------------------------
# Provider fetch result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderFetchResult:
    """Generic envelope returned by every provider fetch method.

    Wraps the raw provider response together with mandatory provenance
    metadata so that every downstream consumer can trace data back to
    its source.

    The ``payload`` contains provider-shaped data — it is NOT a canonical
    entity or a ``MatchContextSnapshot``.  Normalization and snapshot
    creation are handled in later patches (16/17).
    """

    provider_name: str
    """Which provider produced this result."""

    adapter_version: str
    """Version of the adapter that produced this result."""

    capability: ProviderCapability
    """What kind of data this result contains."""

    fetched_at: datetime
    """UTC-aware timestamp of when the provider was queried."""

    source_reference: str
    """Where the data came from, e.g. ``"fixture://fake_provider_v1/teams"``."""

    raw_payload_hash: str
    """SHA-256 hex digest of the serialized payload for audit."""

    payload: Mapping[str, Any] = field(default_factory=dict)
    """Provider-shaped raw data.  Structure varies by capability."""

    license_notes: str | None = None
    """Attribution or license requirements, if relevant."""

    completeness: Mapping[str, Any] = field(default_factory=dict)
    """Metadata about data completeness: which sub-fields are present, missing, etc."""

    warnings: tuple[str, ...] = ()
    """Non-blocking warnings encountered during fetch."""

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        if not self.source_reference.strip():
            raise ValueError("source_reference must not be empty")

    @property
    def is_empty(self) -> bool:
        """``True`` if the payload contains no data."""
        return len(self.payload) == 0

    def to_dict(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "adapter_version": self.adapter_version,
            "capability": self.capability.value,
            "fetched_at": self.fetched_at.isoformat(),
            "source_reference": self.source_reference,
            "raw_payload_hash": self.raw_payload_hash,
            "payload": dict(self.payload),
            "license_notes": self.license_notes,
            "completeness": dict(self.completeness),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Provider adapter interface (Protocol)
# ---------------------------------------------------------------------------


class ProviderAdapter(Protocol):
    """Protocol that every Data Service v1 provider adapter must satisfy.

    Each method corresponds to one ``ProviderCapability``.  A provider that
    does not support a capability should raise ``NotImplementedError``.

    All methods return ``ProviderFetchResult`` — a raw payload envelope
    with full provenance.  Normalization into canonical entities and
    ``MatchContextSnapshot`` creation are separate pipeline stages
    (later patches).

    **v1 boundary:** Provider data — especially odds, lineups, injuries,
    suspensions, and prematch signals — MUST NOT be fed into the prediction
    engine to modify probabilities.
    """

    descriptor: ProviderDescriptor

    def fetch_teams(self) -> ProviderFetchResult: ...

    def fetch_matches(self) -> ProviderFetchResult: ...

    def fetch_group_standings(self) -> ProviderFetchResult: ...

    def fetch_knockout_bracket(self) -> ProviderFetchResult: ...

    def fetch_odds(self) -> ProviderFetchResult: ...

    def fetch_lineups(self) -> ProviderFetchResult: ...

    def fetch_injuries(self) -> ProviderFetchResult: ...

    def fetch_suspensions(self) -> ProviderFetchResult: ...

    def fetch_prematch_signals(self) -> ProviderFetchResult: ...


# ---------------------------------------------------------------------------
# Provider errors (structured failures — no silent fallback)
# ---------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """Base error for provider failures."""

    category: str = "provider"


class ProviderUnavailableError(ProviderError):
    """Provider is unreachable (network, timeout, rate-limit)."""

    category = "unavailable"


class ProviderConfigurationError(ProviderError):
    """Provider is misconfigured (missing credentials, invalid endpoint)."""

    category = "configuration"


class ProviderSchemaError(ProviderError):
    """Provider returned data that does not match expected schema."""

    category = "schema"


# ---------------------------------------------------------------------------
# Deterministic fake provider
# ---------------------------------------------------------------------------


# ── Fixed timestamps (all UTC) ──

_FAKE_NOW = _fixed_datetime(2026, 6, 15, 12, 0, 0)


def _fake_source(capability: str) -> str:
    """Build a deterministic ``source_reference`` for the fake provider."""
    return f"fixture://fake_provider_v1/{capability}"


def _compute_payload_hash(payload: Mapping[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of a payload dict.

    Canonicalization rules (Patch 15.1):
      - Dict keys are sorted at ALL nesting levels via ``json.dumps(..., sort_keys=True)``.
      - Tuples and lists are both serialized as JSON arrays ``[...]`` — a tuple
        and a list with the same elements produce the same hash.
      - Non-JSON-serializable types fall through to ``default=str`` (for
        human-readable audit only; provider payloads should stick to JSON-safe
        types in normal operation).
      - The hash is SHA-256 over UTF-8 bytes of the canonical JSON.

    These rules mean that two payloads that are semantically identical but
    differ only in dict key insertion order or tuple-vs-list wrapping will
    produce the same hash.
    """
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _make_result(
    capability: ProviderCapability,
    payload: Mapping[str, Any],
    *,
    completeness: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> ProviderFetchResult:
    """Build a ``ProviderFetchResult`` with deterministic provenance."""
    return ProviderFetchResult(
        provider_name="fake_provider_v1",
        adapter_version="1.0.0",
        capability=capability,
        fetched_at=_FAKE_NOW,
        source_reference=_fake_source(capability.value),
        raw_payload_hash=_compute_payload_hash(payload),
        payload=payload,
        license_notes="fictional fixture — no license required",
        completeness=completeness or {},
        warnings=warnings,
    )


# ── Fictional payload data (all FIC- prefixed, Fake / Fictional names) ──


_FAKE_TEAMS_PAYLOAD: Mapping[str, Any] = {
    "teams": (
        {
            "team_id": "FIC-ALPHA",
            "display_name": "Fictional Alpha FC",
            "country_code": "FIC",
            "external_id": "FAKE-001",
        },
        {
            "team_id": "FIC-BETA",
            "display_name": "Fictional Beta FC",
            "country_code": "FIC",
            "external_id": "FAKE-002",
        },
        {
            "team_id": "FIC-GAMMA",
            "display_name": "Fictional Gamma FC",
            "country_code": "FIC",
            "external_id": "FAKE-003",
        },
        {
            "team_id": "FIC-DELTA",
            "display_name": "Fictional Delta FC",
            "country_code": "FIC",
            "external_id": "FAKE-004",
        },
    ),
}

_FAKE_MATCHES_PAYLOAD: Mapping[str, Any] = {
    "matches": (
        {
            "match_id": "FIC-001",
            "team_a_id": "FIC-ALPHA",
            "team_b_id": "FIC-BETA",
            "kickoff_at": "2026-06-16T20:00:00Z",
            "stage": "group",
            "group": "Fictional Group A",
            "matchday": 1,
            "venue": "Fictional Stadium One",
            "neutral_site": True,
        },
        {
            "match_id": "FIC-002",
            "team_a_id": "FIC-GAMMA",
            "team_b_id": "FIC-DELTA",
            "kickoff_at": "2026-06-16T23:00:00Z",
            "stage": "group",
            "group": "Fictional Group A",
            "matchday": 1,
            "venue": "Fictional Stadium Two",
            "neutral_site": True,
        },
        {
            "match_id": "FIC-KO-001",
            "team_a_id": "FIC-ALPHA",
            "team_b_id": "FIC-GAMMA",
            "kickoff_at": "2026-07-01T20:00:00Z",
            "stage": "QF",
            "round_name": "Quarter-final",
            "venue": "Fictional Grand Stadium",
            "neutral_site": True,
        },
    ),
}

_FAKE_STANDINGS_PAYLOAD: Mapping[str, Any] = {
    "standings": (
        {
            "group_id": "Fictional Group A",
            "rows": (
                {"position": 1, "team_id": "FIC-ALPHA", "played": 2, "won": 2, "drawn": 0,
                 "lost": 0, "goals_for": 5, "goals_against": 1, "goal_difference": 4, "points": 6},
                {"position": 2, "team_id": "FIC-BETA", "played": 2, "won": 1, "drawn": 0,
                 "lost": 1, "goals_for": 2, "goals_against": 3, "goal_difference": -1, "points": 3},
                {"position": 3, "team_id": "FIC-GAMMA", "played": 2, "won": 1, "drawn": 0,
                 "lost": 1, "goals_for": 2, "goals_against": 2, "goal_difference": 0, "points": 3},
                {"position": 4, "team_id": "FIC-DELTA", "played": 2, "won": 0, "drawn": 0,
                 "lost": 2, "goals_for": 1, "goals_against": 4, "goal_difference": -3, "points": 0},
            ),
        },
    ),
}

_FAKE_BRACKET_PAYLOAD: Mapping[str, Any] = {
    "bracket": {
        "bracket_id": "FIC-KO-2026",
        "round_name": "Quarter-final",
        "match_slots": ("FIC-KO-001", "FIC-KO-002", "FIC-KO-003", "FIC-KO-004"),
    },
}

_FAKE_ODDS_PAYLOAD: Mapping[str, Any] = {
    "odds": (
        {
            "match_id": "FIC-001",
            "market_type": "1X2",
            "bookmaker": "Fictional Bookmaker Ltd",
            "captured_at": "2026-06-15T10:00:00Z",
            "selections": (
                {"label": "team_a_win", "decimal_odds": 2.10},
                {"label": "draw", "decimal_odds": 3.50},
                {"label": "team_b_win", "decimal_odds": 3.80},
            ),
        },
        {
            "match_id": "FIC-001",
            "market_type": "over_under_2.5",
            "bookmaker": "Fictional Bookmaker Ltd",
            "captured_at": "2026-06-15T10:00:00Z",
            "selections": (
                {"label": "over", "decimal_odds": 1.85},
                {"label": "under", "decimal_odds": 1.95},
            ),
        },
    ),
}

_FAKE_LINEUPS_PAYLOAD: Mapping[str, Any] = {
    "lineups": (
        {
            "match_id": "FIC-001",
            "team_id": "FIC-ALPHA",
            "status": "confirmed",
            "formation": "4-3-3",
            "starting_xi": (
                {"name": "Fake Player One", "number": 1, "position": "GK", "is_captain": False},
                {"name": "Fake Player Two", "number": 4, "position": "CB", "is_captain": True},
                {"name": "Fake Player Three", "number": 7, "position": "FW", "is_captain": False},
            ),
            "substitutes": (
                {"name": "Fake Player Four", "number": 12, "position": "MF", "is_captain": False},
            ),
            "coach": "Fake Coach Alpha",
            "last_updated": "2026-06-15T10:00:00Z",
        },
        {
            "match_id": "FIC-001",
            "team_id": "FIC-BETA",
            "status": "predicted",
            "formation": "4-4-2",
            "starting_xi": (
                {"name": "Fake Player Five", "number": 1, "position": "GK", "is_captain": False},
                {"name": "Fake Player Six", "number": 10, "position": "FW", "is_captain": True},
            ),
            "substitutes": (),
            "coach": "Fake Coach Beta",
            "last_updated": "2026-06-15T10:00:00Z",
        },
    ),
}

_FAKE_INJURIES_PAYLOAD: Mapping[str, Any] = {
    "injuries": (
        {
            "team_id": "FIC-ALPHA",
            "player_name": "Fake Player Three",
            "status": "doubtful",
            "injury_type": "fictional hamstring strain",
            "expected_return": "2026-06-20",
            "source_updated_at": "2026-06-15T10:00:00Z",
        },
        {
            "team_id": "FIC-BETA",
            "player_name": "Fake Player Seven",
            "status": "out",
            "injury_type": "fictional knee sprain",
            "expected_return": "unknown",
            "source_updated_at": "2026-06-15T10:00:00Z",
        },
    ),
}

_FAKE_SUSPENSIONS_PAYLOAD: Mapping[str, Any] = {
    "suspensions": (
        {
            "team_id": "FIC-BETA",
            "player_name": "Fake Player Six",
            "reason": "yellow_accumulation",
            "matches_suspended": 1,
            "remaining_matches": 1,
        },
    ),
}

_FAKE_SIGNALS_PAYLOAD: Mapping[str, Any] = {
    "signals": (
        {
            "signal_id": "FIC-SIG-001",
            "match_id": "FIC-001",
            "category": "weather",
            "summary": "Fictional mild rain expected at kickoff; no wind impact.",
            "confidence": "confirmed",
            "source_name": "Fictional Weather Service",
            "published_at": "2026-06-15T10:00:00Z",
            "tags": ("weather", "fictional"),
        },
        {
            "signal_id": "FIC-SIG-002",
            "match_id": "FIC-001",
            "category": "tactical",
            "summary": (
                "Fictional Alpha FC expected to use high-press approach "
                "against Fictional Beta FC's counter-attacking style."
            ),
            "confidence": "reported",
            "source_name": "Fictional Tactical Analyst",
            "published_at": "2026-06-15T10:00:00Z",
            "tags": ("tactical", "fictional"),
        },
    ),
}


# ── Fake provider ──


class DeterministicFakeProvider:
    """A fully deterministic fake provider for Data Service v1.

    Returns hardcoded fictional data for every capability.  All timestamps
    are fixed, all hashes are deterministic.  No network calls.  No real data.

    This provider is intended for:
      - schema validation
      - provider interface testing
      - local store and snapshot writer/reader development (future patches)
      - import-boundary verification

    It is NOT intended for:
      - prediction (data is fictional)
      - calibration (data is fictional)
      - any production use
    """

    descriptor = ProviderDescriptor(
        name="fake_provider_v1",
        adapter_version="1.0.0",
        capabilities=frozenset(ProviderCapability),
        requires_credentials=False,
        attribution_url="fixture://fake_provider_v1",
        enabled=True,
    )

    # ── Core data ──

    def fetch_teams(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)

    def fetch_matches(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.MATCHES, _FAKE_MATCHES_PAYLOAD)

    # ── Tournament structure ──

    def fetch_group_standings(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.GROUP_STANDINGS, _FAKE_STANDINGS_PAYLOAD)

    def fetch_knockout_bracket(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.KNOCKOUT_BRACKET, _FAKE_BRACKET_PAYLOAD)

    # ── Market data (market comparison only — NOT model input) ──

    def fetch_odds(self) -> ProviderFetchResult:
        return _make_result(
            ProviderCapability.ODDS,
            _FAKE_ODDS_PAYLOAD,
            completeness={"markets_present": ["1X2", "over_under_2.5"], "markets_missing": []},
        )

    # ── Squad context (structured context only — NOT model input) ──

    def fetch_lineups(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.LINEUPS, _FAKE_LINEUPS_PAYLOAD)

    def fetch_injuries(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.INJURIES, _FAKE_INJURIES_PAYLOAD)

    def fetch_suspensions(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.SUSPENSIONS, _FAKE_SUSPENSIONS_PAYLOAD)

    # ── Context / signals (report-only — NOT model input) ──

    def fetch_prematch_signals(self) -> ProviderFetchResult:
        return _make_result(ProviderCapability.PREMATCH_SIGNALS, _FAKE_SIGNALS_PAYLOAD)
