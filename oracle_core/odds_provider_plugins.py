"""Odds provider plugging kit — extends ``oracle_core.odds_provider_runtime``.

Plugin specs, request/response types, and default disabled adapters for
odds data providers.  All providers are disabled by default.  No network.
No env reads.  No fake data.

Odds are market comparison ONLY.  Odds NEVER blend with model probabilities.
Market-implied probabilities are LABELED as ``"market_implied_only"``,
NOT as model probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Plugin spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsPluginSpec:
    """Specification for an odds provider plugin.

    All providers start disabled (``approval_status="disabled"``).
    Activation requires explicit approval.
    """

    provider_name: str
    provider_type: str = "http_api"
    base_url: str = ""
    configured: bool = False
    requires_api_key: bool = True
    approval_status: str = "disabled"
    market_types_supported: tuple[str, ...] = ("1X2",)


# ---------------------------------------------------------------------------
# Plugin-level request / response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsPluginRequest:
    """A plugin-level request for odds data.

    ``market_types`` specifies which markets to fetch (e.g. ``"1X2"``,
    ``"over_under_2.5"``).  ``allow_live`` is a per-request opt-in flag.
    """

    match_id: str
    market_types: tuple[str, ...] = ("1X2",)
    allow_live: bool = False

    def __post_init__(self) -> None:
        if not self.match_id.strip():
            raise ValueError("match_id must not be empty")


@dataclass(frozen=True)
class OddsPluginResponse:
    """Response from an odds plugin fetch.

    ``odds_data`` is an optional provider-shaped dict.  When ``success`` is
    ``False``, ``odds_data`` is ``None`` and gaps/caveats describe the failure.

    ``market_implied_probabilities`` is always **separate** and LABELED as
    ``"market_implied_only"`` — NOT model probabilities.
    """

    provider_name: str
    success: bool
    odds_data: dict[str, Any] | None = None
    """Provider-shaped odds data dict.  ``None`` when fetch fails."""

    gaps: tuple[str, ...] = ()
    """Gaps that could not be filled (e.g. no provider configured)."""

    caveats: tuple[str, ...] = ()
    """Caveats / warnings about the odds fetch."""

    network_called: bool = False
    """Whether a network call was made during this fetch."""

    market_implied_probabilities: dict[str, Any] | None = None
    """Market-implied probabilities, LABELED as ``"market_implied_only"``.

    These are NOT model probabilities.  They must not be blended with or
    substituted for model output.
    """

    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the fetch completed."""

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


@dataclass(frozen=True)
class OddsMarketEntry:
    """A single odds market entry for one match.

    ``report_only`` is ALWAYS ``True``.
    ``affects_model`` is ALWAYS ``False``.
    Odds are external market reference only — they never blend into model
    probabilities.

    ``stale`` indicates whether the odds data may be outdated.
    """

    market_type: str
    """Market type, e.g. ``"1X2"``, ``"over_under_2.5"``."""

    home_price: float = 0.0
    """Decimal odds for home win."""

    draw_price: float = 0.0
    """Decimal odds for draw."""

    away_price: float = 0.0
    """Decimal odds for away win."""

    bookmaker: str = ""
    """Bookmaker name, if known."""

    timestamp: str = ""
    """ISO-format timestamp of when odds were captured."""

    stale: bool = False
    """Whether the odds data may be outdated."""

    report_only: bool = True
    """ALWAYS ``True`` — odds are report-only."""

    affects_model: bool = False
    """ALWAYS ``False`` — odds must not affect model output."""

    def __post_init__(self) -> None:
        if not self.report_only:
            raise ValueError(
                "OddsMarketEntry.report_only must always be True. "
                "Odds are report-only — they must not affect model output."
            )
        if self.affects_model:
            raise ValueError(
                "OddsMarketEntry.affects_model must always be False. "
                "Odds must not blend into model probabilities."
            )


# ---------------------------------------------------------------------------
# Built-in specs
# ---------------------------------------------------------------------------

DISABLED_ODDS_SPEC = OddsPluginSpec(
    provider_name="disabled_odds",
    provider_type="http_api",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

GENERIC_HTTP_ODDS_SPEC = OddsPluginSpec(
    provider_name="generic_http_odds",
    provider_type="http_api",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class OddsPluginAdapter(Protocol):
    """Protocol that all odds plugin adapters implement."""

    PROVIDER_NAME: str

    def fetch(self, request: OddsPluginRequest) -> OddsPluginResponse:
        """Fetch odds for *request*.

        Returns an ``OddsPluginResponse``.  Never raises.
        """
        ...


# ---------------------------------------------------------------------------
# DisabledOddsPluginAdapter — default fail-closed adapter
# ---------------------------------------------------------------------------


class DisabledOddsPluginAdapter:
    """Default adapter — always returns fail-closed response.

    No network.  No env reads.  Never fabricates data.
    """

    PROVIDER_NAME = "disabled"

    def fetch(self, request: OddsPluginRequest) -> OddsPluginResponse:
        now = datetime.now(timezone.utc)
        return OddsPluginResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            odds_data=None,
            gaps=("odds_provider_disabled",),
            caveats=(
                "Odds plugin is disabled by default. "
                "No odds fetch performed. Market comparison unavailable.",
            ),
            network_called=False,
            market_implied_probabilities=None,
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# List plugins
# ---------------------------------------------------------------------------


def list_odds_plugins() -> tuple[OddsPluginSpec, ...]:
    """Return all built-in odds plugin specs.

    Returns:
        Tuple of ``OddsPluginSpec``, all disabled by default.
    """
    return (DISABLED_ODDS_SPEC, GENERIC_HTTP_ODDS_SPEC)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_odds_adapter(
    provider_name: str,
    *,
    allow_live: bool = False,
) -> OddsPluginAdapter:
    """Factory: create an odds plugin adapter.

    Always disabled unless explicit opt-in via ``allow_live=True``.
    Even with opt-in, only a stub adapter is returned — no real odds
    provider is configured by default.

    Args:
        provider_name: Name of the odds provider (ignored in current version).
        allow_live: If ``False`` (default), returns
            ``DisabledOddsPluginAdapter``.

    Returns:
        - ``DisabledOddsPluginAdapter`` if ``allow_live`` is ``False``.
        - ``_StubRealOddsAdapter`` if ``allow_live`` is ``True`` (no real
          provider configured yet).
    """
    if not allow_live:
        return DisabledOddsPluginAdapter()

    return _StubRealOddsAdapter()


class _StubRealOddsAdapter:
    """Stub adapter for future real odds providers.

    Always returns a fail-closed response indicating no odds provider is
    configured.  Never fakes data.
    """

    PROVIDER_NAME = "stub_real"

    def fetch(self, request: OddsPluginRequest) -> OddsPluginResponse:
        now = datetime.now(timezone.utc)
        return OddsPluginResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            odds_data=None,
            gaps=("odds_provider_not_configured",),
            caveats=(
                "No real odds provider configured. "
                "Market comparison unavailable.",
            ),
            network_called=False,
            market_implied_probabilities=None,
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def execute_odds_fetch(
    adapter: OddsPluginAdapter,
    request: OddsPluginRequest,
) -> OddsPluginResponse:
    """Run *adapter*.fetch(*request*), catching errors.

    Args:
        adapter: An ``OddsPluginAdapter`` implementation.
        request: The ``OddsPluginRequest`` to send.

    Returns:
        ``OddsPluginResponse`` — the adapter's response on success, or a
        fail-closed response with gaps/caveats on error.

    Never raises.  Never fabricates data on failure.
    """
    try:
        return adapter.fetch(request)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        return OddsPluginResponse(
            provider_name=getattr(adapter, "PROVIDER_NAME", "unknown"),
            success=False,
            odds_data=None,
            gaps=("odds_fetch_error",),
            caveats=(
                f"Odds fetch raised {type(exc).__name__}: {exc}",
            ),
            network_called=False,
            market_implied_probabilities=None,
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# Market-implied probability computation
# ---------------------------------------------------------------------------


def compute_implied_probabilities(
    odds_entry: OddsMarketEntry,
) -> dict[str, Any]:
    """Compute market-implied probabilities from an odds entry.

    ONLY callable on real odds data, never on synthetic data.
    Converts decimal odds to implied probabilities: ``1 / decimal_odds``,
    then normalizes to sum to 1.0.

    The returned dict is LABELED with ``"market_implied_only"`` to clearly
    distinguish it from model probabilities.

    Args:
        odds_entry: An ``OddsMarketEntry`` with real (non-zero) odds data.

    Returns:
        A dict containing:
        - ``"_label"`` (str): always ``"market_implied_only"``.
        - ``"home_implied"`` (float): normalized home win probability.
        - ``"draw_implied"`` (float): normalized draw probability.
        - ``"away_implied"`` (float): normalized away win probability.
        - ``"raw_home_price"`` (float): original decimal odds for home.
        - ``"raw_draw_price"`` (float): original decimal odds for draw.
        - ``"raw_away_price"`` (float): original decimal odds for away.
        - ``"overround"`` (float): sum of raw implied probabilities before
          normalization (market overround).
    """
    raw_home = 1.0 / odds_entry.home_price if odds_entry.home_price > 0 else 0.0
    raw_draw = 1.0 / odds_entry.draw_price if odds_entry.draw_price > 0 else 0.0
    raw_away = 1.0 / odds_entry.away_price if odds_entry.away_price > 0 else 0.0

    overround = raw_home + raw_draw + raw_away

    if overround > 0:
        home_implied = raw_home / overround
        draw_implied = raw_draw / overround
        away_implied = raw_away / overround
    else:
        home_implied = 0.0
        draw_implied = 0.0
        away_implied = 0.0

    return {
        "_label": "market_implied_only",
        "home_implied": home_implied,
        "draw_implied": draw_implied,
        "away_implied": away_implied,
        "raw_home_price": odds_entry.home_price,
        "raw_draw_price": odds_entry.draw_price,
        "raw_away_price": odds_entry.away_price,
        "overround": overround,
    }


# ---------------------------------------------------------------------------
# Market comparison builder
# ---------------------------------------------------------------------------


def odds_to_market_comparison(
    response: OddsPluginResponse,
) -> dict[str, Any]:
    """Build a ``market_comparison`` dict from an odds plugin response.

    Odds output goes ONLY into ``market_comparison``.  Odds NEVER blend
    into model probabilities.  The returned dict includes a disclaimer
    stating that odds are external market reference only.

    Args:
        response: The ``OddsPluginResponse`` from a fetch.

    Returns:
        A dict with keys:
        - ``available`` (bool): whether odds data is present.
        - ``disclaimer`` (str): always includes the no-blending disclaimer.
        - ``data`` (optional): the odds data if available.
        - ``market_implied_probabilities`` (optional): probabilities labeled
          as ``"market_implied_only"``.
        - ``gaps`` (list[str]): gaps from the response.
        - ``caveats`` (list[str]): caveats from the response.
    """
    disclaimer = (
        "Odds are external market reference, not model input. "
        "No probability blending occurred. "
        "Market-implied probabilities are labeled 'market_implied_only' "
        "and are NOT model probabilities."
    )

    base: dict[str, Any] = {
        "disclaimer": disclaimer,
        "gaps": list(response.gaps),
        "caveats": list(response.caveats),
    }

    if not response.success or response.odds_data is None:
        base["available"] = False
        base["data"] = None
        base["market_implied_probabilities"] = None
        return base

    base["available"] = True
    base["data"] = response.odds_data
    base["market_implied_probabilities"] = response.market_implied_probabilities
    base["caveats"].append(
        "Odds are market comparison only. "
        "They do not alter result_probabilities or "
        "advancement_probabilities. "
        "Market-implied probabilities are NOT model probabilities."
    )

    return base
