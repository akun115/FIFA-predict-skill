"""Free provider adapter skeletons — Data Service v1 (Patch 22).

Provides offline-ready adapter classes for Football-Data.org and API-Football.
All adapters use an ``HttpTransport`` Protocol for HTTP — the default
transport is ``DisabledNetworkTransport`` which fails closed.

No real API calls.  No real data.  No prediction integration.

IMPORTANT — Model boundary (v1):
  Odds data is market comparison only.  Lineup/injury/suspension/signal data
  is report-only context.  No xG adjustment.  No odds blending.  No model
  probability modification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderConfigurationError,
    ProviderDescriptor,
    ProviderError,
    ProviderFetchResult,
    ProviderUnavailableError,
    _compute_payload_hash,
)


# ---------------------------------------------------------------------------
# HTTP transport abstraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpRequest:
    """Immutable HTTP request descriptor.  No network I/O here."""
    method: str = "GET"
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class HttpResponse:
    """Immutable HTTP response.  Timestamped for provenance."""
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    body_text: str = ""
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


class HttpTransport(Protocol):
    """Protocol for sending HTTP requests.

    Implementations:
      - ``FakeHttpTransport`` — deterministic synthetic responses for tests.
      - ``DisabledNetworkTransport`` — always raises (fail-closed default).
      - Future: real urllib-based transport (separate patch, opt-in only).
    """

    def send(self, request: HttpRequest) -> HttpResponse: ...


# ---------------------------------------------------------------------------
# Transport implementations
# ---------------------------------------------------------------------------


class DisabledNetworkTransport:
    """Default transport — always fails closed.  No network calls.

    Raises ``ProviderUnavailableError`` on every ``send()``.
    """

    def send(self, request: HttpRequest) -> HttpResponse:
        raise ProviderUnavailableError(
            "Network transport is disabled (fail-closed).  "
            "Set live_mode=True and provide credentials to enable."
        )


class FakeHttpTransport:
    """Deterministic fake HTTP transport for offline tests.

    Returns synthetic JSON payloads keyed by URL path.  All data is
    fictional (FIC-* prefix).  No real teams, players, or matches.
    """

    def __init__(self, responses: Mapping[str, str] | None = None):
        self._responses: dict[str, str] = dict(responses or {})

    def add(self, path: str, body_text: str) -> None:
        self._responses[path] = body_text

    def send(self, request: HttpRequest) -> HttpResponse:
        path = request.url
        if path in self._responses:
            return HttpResponse(
                status_code=200,
                body_text=self._responses[path],
                fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            )
        return HttpResponse(
            status_code=404,
            body_text=json.dumps({"error": "not_found", "path": path}),
            fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )


# ---------------------------------------------------------------------------
# Stdlib HTTP transport (Patch 26 — opt-in live mode only)
# ---------------------------------------------------------------------------


class StdlibHttpTransport:
    """Real HTTP transport using Python standard library (``urllib``).

    **Opt-in only.**  Never used by default.  Only instantiated when
    ``live_mode=True`` and a provider is explicitly configured for live
    fetch.
    """

    def send(self, request: HttpRequest) -> HttpResponse:
        import urllib.request
        import urllib.error
        now = datetime.now(timezone.utc)
        try:
            req = urllib.request.Request(
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
            )
            timeout = request.timeout_seconds or 30.0
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResponse(
                    status_code=resp.status,
                    body_text=body,
                    fetched_at=now,
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return HttpResponse(
                status_code=e.code,
                body_text=body,
                fetched_at=now,
            )
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ProviderUnavailableError(
                f"Network request failed: {e}"
            ) from e


# ---------------------------------------------------------------------------
# Credential config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeProviderConfig:
    """Configuration for a free-tier provider adapter.

    In offline/disabed mode, the adapter uses ``DisabledNetworkTransport``
    and all fetch methods return empty results with warnings.
    """

    api_key_env_var: str = ""
    """Environment variable name for the API key (never stored here)."""

    base_url: str = ""
    """Base URL for the provider API (placeholder in skeleton)."""

    enabled: bool = False
    """Whether this provider is active."""

    live_mode: bool = False
    """If True, use real HTTP transport.  Default False (fail-closed)."""

    timeout_seconds: float = 30.0
    """Request timeout in seconds."""

    public_free_mode: bool = False
    """If True, this provider uses a public-free (no-account) API key.
    The key is NOT a private user secret (e.g., TheSportsDB test key)."""

    public_api_key: str | None = None
    """Public API key for public-free providers.  Not a private secret.
    Never stored in ProviderFetchResult, logs, or snapshots."""

    attribution: str = ""
    """Attribution text required by provider license."""

    def require_api_key(self) -> str:
        """Return the API key from the environment, or raise.

        Never reads the key in default (offline) mode.
        Raises ``ProviderConfigurationError`` on any failure (fail-closed).
        """
        import os
        if not self.live_mode:
            raise ProviderConfigurationError(
                "Cannot read API key: live_mode is disabled."
            )
        if not self.api_key_env_var:
            raise ProviderConfigurationError(
                "api_key_env_var is not configured."
            )
        key = os.environ.get(self.api_key_env_var, "")
        if not key.strip():
            raise ProviderConfigurationError(
                f"API key not found in environment variable "
                f"'{self.api_key_env_var}'.  Provider is fail-closed."
            )
        return key


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderCapabilityNotSupportedError(ProviderError):
    """The requested capability is not supported by this provider."""
    category = "unsupported"


# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _build_result(
    provider_name: str,
    adapter_version: str,
    capability: ProviderCapability,
    payload: Mapping[str, Any],
    *,
    source_reference: str = "",
    license_notes: str = "",
    completeness: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> ProviderFetchResult:
    return ProviderFetchResult(
        provider_name=provider_name,
        adapter_version=adapter_version,
        capability=capability,
        fetched_at=_now(),
        source_reference=source_reference or f"fixture://{provider_name}/{capability.value}",
        raw_payload_hash=_compute_payload_hash(payload),
        payload=payload,
        license_notes=license_notes or "Free tier — license review pending (<needs_human_review>)",
        completeness=completeness or {},
        warnings=warnings,
    )


def _empty_result(
    provider_name: str,
    adapter_version: str,
    capability: ProviderCapability,
    *,
    reason: str = "not supported",
) -> ProviderFetchResult:
    return _build_result(
        provider_name, adapter_version, capability, {},
        completeness={"available": False, "reason": reason},
        warnings=(f"Capability '{capability.value}' {reason}.",),
    )


# ---------------------------------------------------------------------------
# Synthetic fixture payloads (FIC-* fictional data only)
# ---------------------------------------------------------------------------

_FIC_TEAMS_JSON = json.dumps({
    "teams": [
        {"id": "FIC-001", "name": "Fictional Alpha FC", "country_code": "FIC"},
        {"id": "FIC-002", "name": "Fictional Beta FC", "country_code": "FIC"},
        {"id": "FIC-003", "name": "Fictional Gamma FC", "country_code": "FIC"},
        {"id": "FIC-004", "name": "Fictional Delta FC", "country_code": "FIC"},
    ],
}, sort_keys=True)

_FIC_MATCHES_JSON = json.dumps({
    "matches": [
        {"id": "FIC-MATCH-001", "home_team": "FIC-001", "away_team": "FIC-002",
         "utc_date": "2026-06-16T20:00:00Z", "stage": "GROUP",
         "group": "Fake Group A", "matchday": 1,
         "venue": "Fictional Stadium One"},
        {"id": "FIC-MATCH-002", "home_team": "FIC-003", "away_team": "FIC-004",
         "utc_date": "2026-06-16T23:00:00Z", "stage": "GROUP",
         "group": "Fake Group A", "matchday": 1,
         "venue": "Fictional Stadium Two"},
    ],
}, sort_keys=True)

_FIC_STANDINGS_JSON = json.dumps({
    "standings": [{
        "group": "Fake Group A",
        "table": [
            {"position": 1, "team": "FIC-001", "played": 2, "won": 2, "draw": 0,
             "lost": 0, "goals_for": 5, "goals_against": 1, "points": 6},
            {"position": 2, "team": "FIC-002", "played": 2, "won": 1, "draw": 0,
             "lost": 1, "goals_for": 2, "goals_against": 3, "points": 3},
        ],
    }],
}, sort_keys=True)

_FIC_ODDS_JSON = json.dumps({
    "odds": [{
        "match_id": "FIC-MATCH-001",
        "bookmaker": "Fictional Bookmaker",
        "markets": [
            {"type": "1X2", "outcomes": [
                {"name": "home", "odds": 2.10},
                {"name": "draw", "odds": 3.50},
                {"name": "away", "odds": 3.80},
            ]},
        ],
    }],
}, sort_keys=True)

_FIC_LINEUPS_JSON = json.dumps({
    "lineups": [{
        "match_id": "FIC-MATCH-001",
        "team_id": "FIC-001",
        "formation": "4-3-3",
        "starters": [
            {"name": "Fake Player One", "number": 1, "position": "GK"},
            {"name": "Fake Player Two", "number": 4, "position": "CB"},
        ],
        "coach": "Fake Coach Alpha",
    }],
}, sort_keys=True)

# TheSportsDB synthetic fixtures (public-free bootstrap)
_THESPORTSDB_TEAMS_JSON = json.dumps({
    "teams": [
        {"idTeam": "FIC-001", "strTeam": "Fictional Alpha FC",
         "strCountry": "Fiction", "strLeague": "Fake Cup",
         "strSport": "Soccer"},
        {"idTeam": "FIC-002", "strTeam": "Fictional Beta FC",
         "strCountry": "Fiction", "strLeague": "Fake Cup",
         "strSport": "Soccer"},
    ],
}, sort_keys=True)

_THESPORTSDB_MATCHES_JSON = json.dumps({
    "events": [
        {"idEvent": "FIC-MATCH-001", "strEvent": "Fictional Alpha FC vs Fictional Beta FC",
         "idHomeTeam": "FIC-001", "idAwayTeam": "FIC-002",
         "strHomeTeam": "Fictional Alpha FC", "strAwayTeam": "Fictional Beta FC",
         "dateEvent": "2026-06-16", "strTime": "20:00:00",
         "strVenue": "Fictional Stadium One", "strSeason": "Fake Season",
         "strLeague": "Fake Cup"},
    ],
}, sort_keys=True)


# ==========================================================================
# FootballDataOrgProviderAdapter
# ==========================================================================


class FootballDataOrgProviderAdapter:
    """Offline-ready adapter skeleton for football-data.org.

    **Capabilities:** TEAMS, MATCHES, GROUP_STANDINGS.
    Lineups, injuries, odds are NOT supported (returns empty result).

    **Default mode:** disabled/offline.  Uses ``DisabledNetworkTransport``
    until ``live_mode=True`` and credentials are provided.

    **Live mode:** requires explicit ``FreeProviderConfig(live_mode=True)``
    and a valid ``HttpTransport`` implementation (not in this patch).
    """

    PROVIDER_NAME = "football-data.org"
    ADAPTER_VERSION = "0.1.0-skeleton"

    def __init__(
        self,
        config: FreeProviderConfig | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config or FreeProviderConfig()
        self._transport = transport or DisabledNetworkTransport()

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.PROVIDER_NAME,
            adapter_version=self.ADAPTER_VERSION,
            capabilities=frozenset({
                ProviderCapability.TEAMS,
                ProviderCapability.MATCHES,
                ProviderCapability.GROUP_STANDINGS,
            }),
            requires_credentials=True,
            attribution_url="<needs_human_review>",
            enabled=self._config.enabled,
        )

    # ── Supported ──

    def fetch_teams(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.TEAMS, "teams", _FIC_TEAMS_JSON)

    def fetch_matches(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.MATCHES, "matches", _FIC_MATCHES_JSON)

    def fetch_group_standings(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.GROUP_STANDINGS, "standings", _FIC_STANDINGS_JSON)

    # ── Not supported ──

    def fetch_knockout_bracket(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.KNOCKOUT_BRACKET)

    def fetch_odds(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.ODDS)

    def fetch_lineups(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.LINEUPS)

    def fetch_injuries(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.INJURIES)

    def fetch_suspensions(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.SUSPENSIONS)

    def fetch_prematch_signals(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.PREMATCH_SIGNALS)

    # ── Internal ──

    def _fetch(
        self,
        capability: ProviderCapability,
        endpoint: str,
        fixture_json: str,
    ) -> ProviderFetchResult:
        if not self._config.enabled and not self._config.live_mode:
            return _empty_result(
                self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                reason="provider disabled",
            )
        try:
            response = self._transport.send(HttpRequest(
                url=f"fixture://football-data.org/{endpoint}",
            ))
        except ProviderError:
            return _empty_result(
                self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                reason="transport unavailable",
            )
        payload = json.loads(response.body_text)
        return _build_result(
            self.PROVIDER_NAME, self.ADAPTER_VERSION, capability, payload,
            source_reference=f"fixture://football-data.org/{endpoint}",
            completeness={"available": True},
        )


# ==========================================================================
# ApiFootballProviderAdapter
# ==========================================================================


class ApiFootballProviderAdapter:
    """Offline-ready adapter skeleton for API-Football (API-SPORTS).

    **Capabilities:** TEAMS, MATCHES, GROUP_STANDINGS, ODDS, LINEUPS.
    Injuries and suspensions are NOT supported (returns empty result).

    **Odds boundary:** Odds are raw market data for comparison only.
    They are NEVER blended into model probabilities.

    **Lineup boundary:** Lineups are raw context data for report only.
    They are NEVER used for xG adjustment.

    **Default mode:** disabled/offline.  See ``FootballDataOrgProviderAdapter``.
    """

    PROVIDER_NAME = "api-football"
    ADAPTER_VERSION = "0.1.0-skeleton"

    def __init__(
        self,
        config: FreeProviderConfig | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config or FreeProviderConfig()
        self._transport = transport or DisabledNetworkTransport()

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.PROVIDER_NAME,
            adapter_version=self.ADAPTER_VERSION,
            capabilities=frozenset({
                ProviderCapability.TEAMS,
                ProviderCapability.MATCHES,
                ProviderCapability.GROUP_STANDINGS,
                ProviderCapability.ODDS,
                ProviderCapability.LINEUPS,
            }),
            requires_credentials=True,
            attribution_url="<needs_human_review>",
            enabled=self._config.enabled,
        )

    # ── Supported ──

    def fetch_teams(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.TEAMS, "teams", _FIC_TEAMS_JSON)

    def fetch_matches(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.MATCHES, "fixtures", _FIC_MATCHES_JSON)

    def fetch_group_standings(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.GROUP_STANDINGS, "standings", _FIC_STANDINGS_JSON)

    def fetch_odds(self) -> ProviderFetchResult:
        """Odds — market comparison only.  NOT blended into model."""
        return self._fetch(ProviderCapability.ODDS, "odds", _FIC_ODDS_JSON)

    def fetch_lineups(self) -> ProviderFetchResult:
        """Lineups — report-only context.  NOT used for xG adjustment."""
        return self._fetch(ProviderCapability.LINEUPS, "lineups", _FIC_LINEUPS_JSON)

    # ── Not supported ──

    def fetch_knockout_bracket(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.KNOCKOUT_BRACKET)

    def fetch_injuries(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.INJURIES)

    def fetch_suspensions(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.SUSPENSIONS)

    def fetch_prematch_signals(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.PREMATCH_SIGNALS)

    # ── Internal ──

    def _fetch(
        self,
        capability: ProviderCapability,
        endpoint: str,
        fixture_json: str,
    ) -> ProviderFetchResult:
        if not self._config.enabled and not self._config.live_mode:
            return _empty_result(
                self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                reason="provider disabled",
            )
        try:
            response = self._transport.send(HttpRequest(
                url=f"fixture://api-football/{endpoint}",
            ))
        except ProviderError:
            return _empty_result(
                self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                reason="transport unavailable",
            )
        payload = json.loads(response.body_text)
        return _build_result(
            self.PROVIDER_NAME, self.ADAPTER_VERSION, capability, payload,
            source_reference=f"fixture://api-football/{endpoint}",
            completeness={"available": True},
        )


# ==========================================================================
# TheSportsDbProviderAdapter — public-free bootstrap (Patch 25)
# ==========================================================================


class TheSportsDbProviderAdapter:
    """Public-free / no-account adapter for TheSportsDB.

    TheSportsDB provides a public test API key — no user registration
    required.  This is the Tier A (public-free bootstrap) provider.

    **Capabilities:** TEAMS, MATCHES (conservative).
    All other capabilities return empty results.

    **Data quality:** TheSportsDB is crowd-sourced.  It is NOT an
    authoritative sole source.  Data must be cross-checked.

    **Default mode:** offline/disabled.  ``FakeHttpTransport`` for tests.
    """

    PROVIDER_NAME = "thesportsdb"
    ADAPTER_VERSION = "0.1.0-skeleton"

    def __init__(
        self,
        config: FreeProviderConfig | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config or FreeProviderConfig()
        self._transport = transport or DisabledNetworkTransport()

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.PROVIDER_NAME,
            adapter_version=self.ADAPTER_VERSION,
            capabilities=frozenset({
                ProviderCapability.TEAMS,
                ProviderCapability.MATCHES,
            }),
            requires_credentials=False,
            attribution_url="<needs_human_review>",
            enabled=self._config.enabled,
        )

    # ── Supported ──

    def fetch_teams(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.TEAMS, "searchteams", _THESPORTSDB_TEAMS_JSON)

    def fetch_matches(self) -> ProviderFetchResult:
        return self._fetch(ProviderCapability.MATCHES, "events", _THESPORTSDB_MATCHES_JSON)

    # ── Not supported ──

    def fetch_group_standings(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.GROUP_STANDINGS)

    def fetch_knockout_bracket(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.KNOCKOUT_BRACKET)

    def fetch_odds(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.ODDS)

    def fetch_lineups(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.LINEUPS)

    def fetch_injuries(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.INJURIES)

    def fetch_suspensions(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.SUSPENSIONS)

    def fetch_prematch_signals(self) -> ProviderFetchResult:
        return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                             ProviderCapability.PREMATCH_SIGNALS)

    # ── Internal ──

    # TheSportsDB public test key (Patch 26.1)
    # Official free/test key "123" — NOT a private user secret.
    # Still must be redacted from ProviderFetchResult.source_reference.
    _PUBLIC_TEST_KEY = "123"

    _ENDPOINTS = {
        ProviderCapability.TEAMS: "/api/v1/json/{key}/searchteams.php?t=United",
        ProviderCapability.MATCHES: "/api/v1/json/{key}/eventsnextleague.php?id=4328",
    }

    _BASE_URL = "https://www.thesportsdb.com"

    @classmethod
    def _resolve_base_url(cls, config_base_url: str = "") -> str:
        if config_base_url and "<needs_human_review>" not in config_base_url:
            return config_base_url
        return cls._BASE_URL

    @classmethod
    def _build_live_url(cls, capability: ProviderCapability, base_url: str = "", key: str = "") -> str:
        ep_template = cls._ENDPOINTS.get(capability, "")
        k = key or cls._PUBLIC_TEST_KEY
        ep = ep_template.format(key=k)
        base = cls._resolve_base_url(base_url)
        return f"{base}{ep}"

    @classmethod
    def _build_redacted_source_reference(cls, capability: ProviderCapability, base_url: str = "") -> str:
        ep_template = cls._ENDPOINTS.get(capability, "")
        ep = ep_template.format(key="<public_test_key>")
        base = cls._resolve_base_url(base_url)
        return f"{base}{ep}"

    def _fetch(self, capability, endpoint, fixture_json):
        if not self._config.enabled and not self._config.live_mode:
            return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                                 capability, reason="provider disabled")

        if self._config.live_mode and self._config.public_free_mode:
            url = self._build_live_url(capability, self._config.base_url, self._config.public_api_key or "")
            source_ref = self._build_redacted_source_reference(capability, self._config.base_url)
            try:
                response = self._transport.send(HttpRequest(
                    url=url, timeout_seconds=self._config.timeout_seconds))
            except ProviderError:
                return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                                     capability, reason="transport unavailable")
            if response.status_code != 200:
                return _empty_result(
                    self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                    reason=f"HTTP {response.status_code}",
                )
            try:
                payload = json.loads(response.body_text)
            except json.JSONDecodeError:
                return _empty_result(
                    self.PROVIDER_NAME, self.ADAPTER_VERSION, capability,
                    reason="malformed JSON response",
                )
            return _build_result(
                self.PROVIDER_NAME, self.ADAPTER_VERSION, capability, payload,
                source_reference=source_ref,
                completeness={"available": True},
            )

        # Offline / test path — use FakeHttpTransport with fixture data
        try:
            response = self._transport.send(HttpRequest(
                url=f"fixture://thesportsdb/{endpoint}",
            ))
        except ProviderError:
            return _empty_result(self.PROVIDER_NAME, self.ADAPTER_VERSION,
                                 capability, reason="transport unavailable")
        payload = json.loads(response.body_text)
        return _build_result(
            self.PROVIDER_NAME, self.ADAPTER_VERSION, capability, payload,
            source_reference=f"fixture://thesportsdb/{endpoint}",
            completeness={"available": True},
        )
