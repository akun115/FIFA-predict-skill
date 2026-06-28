"""Live provider runtime boundary — fail-closed by default.

No default network. No default env/API key reads. No committed live payloads.
Provider result must NOT alter model probabilities or xG.
TheSportsDB remains needs_more_info (NOT approved_for_live_adapter).

Rules:
  - Do not mark TheSportsDB approved
  - All failures produce gaps/caveats, not fabricated data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveProviderConfig:
    """Configuration for a live provider adapter.

    ``live_opt_in`` must be explicitly set to True for any live fetch to
    proceed.  Default is False (fail-closed).
    """

    live_opt_in: bool = False
    """Must be set to True for live fetch to proceed."""


# ---------------------------------------------------------------------------
# Key types (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveProviderRequest:
    """Request to a live provider for match context data.

    ``allow_live`` is a per-request opt-in flag.  Even if the adapter is
    configured with ``live_opt_in=True``, the request must also declare
    ``allow_live=True`` for a live fetch to proceed.
    """

    provider_name: str
    capability: str
    match_id: str
    team_ids: tuple[str, ...] = ()
    allow_live: bool = False


@dataclass(frozen=True)
class LiveProviderResponse:
    """Response from a live provider fetch.

    ``data`` is an optional provider-shaped dict.  When ``success`` is
    False, ``data`` is None and gaps/caveats describe the failure.
    """

    provider_name: str
    success: bool
    data: dict[str, Any] | None = None
    gaps: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    network_called: bool = False
    env_read: bool = False
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


@dataclass(frozen=True)
class ProviderStatus:
    """Status report for a live provider.

    ``approved`` is always False for TheSportsDB.
    ``last_checked`` is an ISO-format timestamp or empty string.
    """

    provider_name: str
    configured: bool
    approved: bool
    last_checked: str
    status_message: str
    gaps: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class LiveProviderAdapter(Protocol):
    """Protocol that all live provider adapters implement."""

    PROVIDER_NAME: str

    def fetch(self, request: LiveProviderRequest) -> LiveProviderResponse:
        """Fetch live context for *request*.

        Returns a ``LiveProviderResponse``.  Never raises.
        """
        ...


# ---------------------------------------------------------------------------
# DisabledLiveProviderAdapter — default fail-closed adapter
# ---------------------------------------------------------------------------


class DisabledLiveProviderAdapter:
    """Default adapter — always returns fail-closed response.

    No network. No env reads. Never fabricates data.
    """

    PROVIDER_NAME = "disabled"

    def fetch(self, request: LiveProviderRequest) -> LiveProviderResponse:
        return LiveProviderResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            gaps=("provider_disabled",),
            caveats=("Live provider is disabled by default",),
            network_called=False,
            env_read=False,
        )


# ---------------------------------------------------------------------------
# TheSportsDbLiveProviderAdapter — ALWAYS needs_more_info (NOT approved)
# ---------------------------------------------------------------------------


class TheSportsDbLiveProviderAdapter:
    """Wraps the existing TheSportsDB adapter.

    TheSportsDB is ALWAYS marked as ``needs_more_info`` — it is NOT approved
    for live adapter use.  Only attempts fetch if ``allow_live=True`` AND
    config has ``live_opt_in=True``.  Otherwise returns gap/caveat.

    Even when both conditions are met, the adapter still reports the provider
    as needs_more_info.  No network calls are made by default.
    """

    PROVIDER_NAME = "thesportsdb"

    def __init__(self, config: LiveProviderConfig | None = None) -> None:
        self._config = config or LiveProviderConfig()

    def fetch(self, request: LiveProviderRequest) -> LiveProviderResponse:
        now = datetime.now(timezone.utc)

        if not request.allow_live or not self._config.live_opt_in:
            return LiveProviderResponse(
                provider_name=self.PROVIDER_NAME,
                success=False,
                gaps=("live_not_opted_in",),
                caveats=(
                    "TheSportsDB live provider requires allow_live=True and "
                    "live_opt_in=True. TheSportsDB is NOT approved for live "
                    "adapter — needs_more_info.",
                ),
                network_called=False,
                env_read=False,
                fetched_at=now,
            )

        # Even with live opt-in, TheSportsDB is NOT approved for live adapter.
        # Data quality requires human review before approval.
        return LiveProviderResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            gaps=("provider_needs_more_info",),
            caveats=(
                "TheSportsDB is NOT approved for live adapter. "
                "Data quality requires human review before approval. "
                "needs_more_info.",
            ),
            network_called=False,
            env_read=False,
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_live_provider(
    provider_name: str,
    *,
    allow_live: bool = False,
) -> LiveProviderAdapter:
    """Factory that returns a live provider adapter.

    Args:
        provider_name: Name of the provider ("thesportsdb" or other).
        allow_live: If False (default), always returns
            ``DisabledLiveProviderAdapter``.

    Returns:
        - ``DisabledLiveProviderAdapter`` if ``allow_live`` is False.
        - ``TheSportsDbLiveProviderAdapter`` if ``allow_live`` is True and
          ``provider_name`` is ``"thesportsdb"``.  TheSportsDB is always
          marked as needs_more_info (NOT approved).
        - ``DisabledLiveProviderAdapter`` for any other provider name
          (provider not recognized).
    """
    if not allow_live:
        return DisabledLiveProviderAdapter()

    if provider_name == "thesportsdb":
        return TheSportsDbLiveProviderAdapter()

    return DisabledLiveProviderAdapter()


# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------


def fetch_provider_context(
    adapter: LiveProviderAdapter,
    request: LiveProviderRequest,
) -> LiveProviderResponse:
    """Run *adapter*.fetch(*request*), catching errors.

    Args:
        adapter: A ``LiveProviderAdapter`` implementation.
        request: The ``LiveProviderRequest`` to send.

    Returns:
        ``LiveProviderResponse`` — the adapter's response on success, or a
        fail-closed response with gaps/caveats on error.

    Never raises.  Never fabricates data on failure.
    """
    try:
        return adapter.fetch(request)
    except Exception as exc:
        return LiveProviderResponse(
            provider_name=getattr(adapter, "PROVIDER_NAME", "unknown"),
            success=False,
            gaps=("fetch_error",),
            caveats=(
                f"Provider fetch raised {type(exc).__name__}: {exc}",
            ),
            network_called=False,
            env_read=False,
        )
