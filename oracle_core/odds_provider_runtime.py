"""Odds provider runtime boundary — fail-closed by default.

Odds are market comparison ONLY.  Odds output goes ONLY into
``market_comparison``.  Odds NEVER blend with model probabilities.
Odds NEVER alter ``result_probabilities`` or ``advancement_probabilities``.

Rules:
  - No default network
  - No default env/API key reads
  - Missing odds -> market gap/caveat
  - No committed live odds payloads
  - Report must state: odds are external market reference, not model input,
    no probability blending occurred
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Key types (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsProviderRequest:
    """Request for odds data.

    ``market_types`` specifies which markets to fetch (e.g. "1X2",
    "over_under_2.5").  ``allow_live`` is a per-request opt-in flag.
    """

    match_id: str
    market_types: tuple[str, ...] = ("1X2", "over_under_2.5")
    allow_live: bool = False


@dataclass(frozen=True)
class OddsProviderResponse:
    """Response from an odds provider fetch.

    ``odds_data`` is an optional provider-shaped dict.  When ``success`` is
    False, ``odds_data`` is None and gaps/caveats describe the failure.
    """

    provider_name: str
    success: bool
    odds_data: dict[str, Any] | None = None
    gaps: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    network_called: bool = False
    env_read: bool = False
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


@dataclass(frozen=True)
class OddsMarketSnapshot:
    """One odds market snapshot for a single match.

    ``report_only`` is ALWAYS True.
    ``affects_model`` is ALWAYS False.
    Odds are external market reference only — they never blend into model
    probabilities.

    ``selections`` is a tuple of dicts each containing ``label`` (str) and
    ``decimal_odds`` (float).
    """

    match_id: str
    market_type: str
    selections: tuple[dict[str, Any], ...]
    bookmaker: str
    captured_at: str
    report_only: bool = True
    affects_model: bool = False

    def __post_init__(self) -> None:
        if not self.report_only:
            raise ValueError(
                "OddsMarketSnapshot.report_only must always be True. "
                "Odds are report-only — they must not affect model output."
            )
        if self.affects_model:
            raise ValueError(
                "OddsMarketSnapshot.affects_model must always be False. "
                "Odds must not blend into model probabilities."
            )


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class OddsProviderAdapter(Protocol):
    """Protocol that all odds provider adapters implement."""

    PROVIDER_NAME: str

    def fetch(self, request: OddsProviderRequest) -> OddsProviderResponse:
        """Fetch odds for *request*.

        Returns an ``OddsProviderResponse``.  Never raises.
        """
        ...


# ---------------------------------------------------------------------------
# DisabledOddsProviderAdapter — default fail-closed adapter
# ---------------------------------------------------------------------------


class DisabledOddsProviderAdapter:
    """Default adapter — always returns fail-closed response.

    No network. No env reads. Never fabricates data.
    """

    PROVIDER_NAME = "disabled"

    def fetch(self, request: OddsProviderRequest) -> OddsProviderResponse:
        return OddsProviderResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            gaps=("odds_provider_disabled",),
            caveats=("Odds provider is disabled by default",),
            network_called=False,
            env_read=False,
        )


# ---------------------------------------------------------------------------
# StubOddsProviderAdapter — stub for future paid providers
# ---------------------------------------------------------------------------


class StubOddsProviderAdapter:
    """Stub adapter for future paid odds providers.

    Always returns a fail-closed response indicating no odds provider is
    configured.  Never fakes data.
    """

    PROVIDER_NAME = "stub"

    def fetch(self, request: OddsProviderRequest) -> OddsProviderResponse:
        return OddsProviderResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            gaps=("odds_provider_not_configured",),
            caveats=(
                "No live odds provider configured. "
                "Market comparison unavailable.",
            ),
            network_called=False,
            env_read=False,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_odds_provider(
    provider_name: str,
    *,
    allow_live: bool = False,
) -> OddsProviderAdapter:
    """Factory that returns an odds provider adapter.

    Always disabled unless explicit opt-in via ``allow_live=True``.
    Even with opt-in, only a stub adapter is returned — no real odds
    provider is configured by default.

    Args:
        provider_name: Name of the odds provider (ignored in v1).
        allow_live: If False (default), returns ``DisabledOddsProviderAdapter``.

    Returns:
        - ``DisabledOddsProviderAdapter`` if ``allow_live`` is False.
        - ``StubOddsProviderAdapter`` if ``allow_live`` is True (no real
          provider configured yet).
    """
    if not allow_live:
        return DisabledOddsProviderAdapter()

    return StubOddsProviderAdapter()


# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------


def fetch_odds(
    adapter: OddsProviderAdapter,
    request: OddsProviderRequest,
) -> OddsProviderResponse:
    """Run *adapter*.fetch(*request*), catching errors.

    Args:
        adapter: An ``OddsProviderAdapter`` implementation.
        request: The ``OddsProviderRequest`` to send.

    Returns:
        ``OddsProviderResponse`` — the adapter's response on success, or a
        fail-closed response with gaps/caveats on error.

    Never raises.  Never fabricates data on failure.
    """
    try:
        return adapter.fetch(request)
    except Exception as exc:
        return OddsProviderResponse(
            provider_name=getattr(adapter, "PROVIDER_NAME", "unknown"),
            success=False,
            gaps=("odds_fetch_error",),
            caveats=(
                f"Odds provider fetch raised {type(exc).__name__}: {exc}",
            ),
            network_called=False,
            env_read=False,
        )


# ---------------------------------------------------------------------------
# Market comparison builder
# ---------------------------------------------------------------------------


def build_market_comparison_section(
    odds_response: OddsProviderResponse,
) -> dict[str, Any]:
    """Build the ``market_comparison`` dict for the report.

    Odds output goes ONLY into ``market_comparison``.  Odds NEVER blend
    into model probabilities.  The returned dict includes a disclaimer
    stating that odds are external market reference only.

    Args:
        odds_response: The ``OddsProviderResponse`` from a fetch.

    Returns:
        A dict with keys:
        - ``available`` (bool): whether odds data is present.
        - ``disclaimer`` (str): always includes the no-blending disclaimer.
        - ``data`` (optional): the odds data if available.
        - ``gaps`` (list[str]): gaps from the response.
        - ``caveats`` (list[str]): caveats from the response.
    """
    disclaimer = (
        "Odds are external market reference, not model input. "
        "No probability blending occurred."
    )

    base: dict[str, Any] = {
        "disclaimer": disclaimer,
        "gaps": list(odds_response.gaps),
        "caveats": list(odds_response.caveats),
    }

    if not odds_response.success or odds_response.odds_data is None:
        base["available"] = False
        base["data"] = None
        return base

    base["available"] = True
    base["data"] = odds_response.odds_data
    if "not blended into model" not in disclaimer.lower():
        base["caveats"].append(
            "Odds are market comparison only. "
            "They do not alter result_probabilities or "
            "advancement_probabilities."
        )

    return base
