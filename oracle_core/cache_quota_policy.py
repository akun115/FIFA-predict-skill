"""Cache, quota, and stale data policy — Patch 38.

Default fail-closed behaviour:
  * Stale data produces caveats, never refreshed silently.
  * Quota-exceeded budgets return ``fail_closed=True`` — no fake refresh.
  * No default network access.  No env reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CachePolicy:
    """Policy governing cache behaviour for a single provider."""

    provider_name: str
    """Provider this policy applies to."""

    ttl_seconds: int
    """Maximum time (in seconds) a cached entry is considered fresh."""

    max_entries: int
    """Maximum number of entries to cache for this provider."""

    stale_threshold_seconds: int
    """Age at which data is considered stale (may differ from TTL)."""


@dataclass(frozen=True)
class QuotaBudget:
    """Budget tracking API usage for a single provider."""

    provider_name: str
    daily_limit: int
    hourly_limit: int
    used_today: int = 0
    used_this_hour: int = 0

    @property
    def exceeded(self) -> bool:
        """``True`` if usage meets or exceeds the daily limit."""
        return self.used_today >= self.daily_limit

    @property
    def hourly_exceeded(self) -> bool:
        """``True`` if usage meets or exceeds the hourly limit."""
        return self.used_this_hour >= self.hourly_limit


@dataclass(frozen=True)
class StaleStatus:
    """Result of a staleness check on cached data."""

    is_stale: bool
    """``True`` if the data is older than the stale threshold."""

    age_seconds: float
    """Actual age of the data in seconds."""

    threshold_seconds: int
    """Threshold that was used for comparison."""

    caveat: str = ""
    """Human-readable caveat when data is stale, empty otherwise."""


@dataclass(frozen=True)
class QuotaCheckResult:
    """Result of a quota check for a provider."""

    provider_name: str
    quota_ok: bool
    """``True`` if the budget has remaining capacity."""

    budget_remaining: int
    """Remaining calls for the current day."""

    fail_closed: bool
    """``True`` when quota is exceeded — no fallback refresh."""

    caveats: tuple[str, ...] = ()


# ------------------------------------------------------------------
# Default cache policies
# ------------------------------------------------------------------

DEFAULT_CACHE_POLICIES: dict[str, CachePolicy] = {
    "thesportsdb": CachePolicy(
        provider_name="thesportsdb",
        ttl_seconds=300,
        max_entries=500,
        stale_threshold_seconds=600,
    ),
    "web_scout": CachePolicy(
        provider_name="web_scout",
        ttl_seconds=600,
        max_entries=200,
        stale_threshold_seconds=900,
    ),
    "odds_provider": CachePolicy(
        provider_name="odds_provider",
        ttl_seconds=120,
        max_entries=300,
        stale_threshold_seconds=300,
    ),
}
"""Default cache policies keyed by provider name."""


# ------------------------------------------------------------------
# Staleness check
# ------------------------------------------------------------------


def check_staleness(
    data_timestamp: datetime,
    policy: CachePolicy,
) -> StaleStatus:
    """Check whether cached data is stale according to *policy*.

    Parameters
    ----------
    data_timestamp:
        When the data was originally fetched.
    policy:
        The ``CachePolicy`` defining staleness thresholds.

    Returns
    -------
    StaleStatus
        ``is_stale=True`` with a caveat if the data exceeds the stale
        threshold.
    """
    now = datetime.now(timezone.utc)
    if data_timestamp.tzinfo is None or data_timestamp.utcoffset() is None:
        data_timestamp = data_timestamp.replace(tzinfo=timezone.utc)

    age = (now - data_timestamp).total_seconds()
    is_stale = age > policy.stale_threshold_seconds

    caveat = ""
    if is_stale:
        caveat = (
            f"Data for '{policy.provider_name}' is {age:.0f}s old "
            f"(threshold: {policy.stale_threshold_seconds}s)"
        )

    return StaleStatus(
        is_stale=is_stale,
        age_seconds=age,
        threshold_seconds=policy.stale_threshold_seconds,
        caveat=caveat,
    )


def is_fresh(data_timestamp: datetime, policy: CachePolicy) -> bool:
    """Convenience: return ``True`` if data is not stale."""
    return not check_staleness(data_timestamp, policy).is_stale


# ------------------------------------------------------------------
# Quota check & record
# ------------------------------------------------------------------


def check_quota(budget: QuotaBudget) -> QuotaCheckResult:
    """Check whether the provider budget has remaining capacity.

    When the budget is exceeded, ``fail_closed=True`` is returned —
    no fallback refresh is attempted.

    Returns
    -------
    QuotaCheckResult
    """
    exceeded = budget.exceeded
    remaining = max(0, budget.daily_limit - budget.used_today)
    caveats: list[str] = []

    if exceeded:
        caveats.append(
            f"Daily quota exceeded for '{budget.provider_name}' "
            f"({budget.used_today}/{budget.daily_limit})"
        )
    if budget.hourly_exceeded:
        caveats.append(
            f"Hourly quota exceeded for '{budget.provider_name}' "
            f"({budget.used_this_hour}/{budget.hourly_limit})"
        )

    return QuotaCheckResult(
        provider_name=budget.provider_name,
        quota_ok=not exceeded and not budget.hourly_exceeded,
        budget_remaining=remaining,
        fail_closed=exceeded,
        caveats=tuple(caveats),
    )


def record_quota_usage(budget: QuotaBudget, count: int = 1) -> QuotaBudget:
    """Increment usage counters on a budget.

    Returns a new ``QuotaBudget`` with updated counters (the original
    is not modified since it is frozen).
    """
    return QuotaBudget(
        provider_name=budget.provider_name,
        daily_limit=budget.daily_limit,
        hourly_limit=budget.hourly_limit,
        used_today=budget.used_today + count,
        used_this_hour=budget.used_this_hour + count,
    )
