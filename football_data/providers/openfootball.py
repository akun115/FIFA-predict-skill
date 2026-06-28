"""OpenFootball public JSON adapter."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import hashlib
from typing import Callable, Mapping

from football_data.domain import MatchRecord, Provenance
from football_data.http import HttpRequestError, JsonHttpClient
from .base import (
    Capability, ProviderDescriptor, ProviderSchemaError, ProviderUnavailableError,
)


DEFAULT_CATALOG = {("PL", "2025"): "2025-26/en.1.json"}


class OpenFootballProvider:
    descriptor = ProviderDescriptor(
        "openfootball",
        frozenset({Capability.RESULTS, Capability.FIXTURES}),
        False,
        "https://github.com/openfootball/football.json",
    )

    def __init__(
        self,
        client: JsonHttpClient,
        *,
        base_url: str = "https://raw.githubusercontent.com/openfootball/football.json/master",
        catalog: Mapping[tuple[str, str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.catalog = dict(catalog or DEFAULT_CATALOG)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def get_matches(self, competition: str, season: str) -> tuple[MatchRecord, ...]:
        path = self.catalog.get((competition, season))
        if path is None:
            raise ProviderUnavailableError("openfootball does not support that dataset")
        try:
            payload = self.client.get_json(f"{self.base_url}/{path}")
        except HttpRequestError as error:
            raise ProviderUnavailableError(
                f"openfootball request failed: {error.category}"
            ) from error
        try:
            matches = payload["matches"]
            if not isinstance(matches, list):
                raise TypeError
            return tuple(self._normalize(competition, item) for item in matches)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            raise ProviderSchemaError("openfootball response schema is invalid") from error

    def _normalize(self, competition: str, item: dict) -> MatchRecord:
        match_date = datetime.strptime(item["date"], "%Y-%m-%d").date()
        raw_time = item.get("time")
        if raw_time:
            match_time = datetime.strptime(raw_time, "%H:%M").time()
            warnings: tuple[str, ...] = ()
        else:
            match_time = time(12, 0)
            warnings = ("date_only_kickoff",)
        kickoff = datetime.combine(match_date, match_time, tzinfo=timezone.utc)
        home = str(item["team1"])
        away = str(item["team2"])
        round_name = str(item.get("round", ""))
        identity = "|".join((competition, item["date"], round_name, home, away))
        provider_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

        raw_score = item.get("score")
        if isinstance(raw_score, dict):
            score = raw_score.get("ft")
        elif isinstance(raw_score, list):
            score = raw_score
        elif raw_score is None:
            score = None
        else:
            raise TypeError("score must be an object, array, or null")
        home_score = away_score = None
        observed_at = None
        status = "scheduled"
        if score is not None:
            if len(score) != 2:
                raise ValueError("score must contain two values")
            home_score, away_score = int(score[0]), int(score[1])
            observed_at = (
                datetime.combine(match_date, time(23, 59, 59), tzinfo=timezone.utc)
                if warnings
                else kickoff + timedelta(hours=3)
            )
            status = "finished"
        return MatchRecord(
            match_id=f"openfootball:{provider_id}",
            competition_id=competition,
            kickoff=kickoff,
            home_team=home,
            away_team=away,
            status=status,
            home_score=home_score,
            away_score=away_score,
            provenance=Provenance(
                "openfootball", provider_id, self.clock(), observed_at, warnings
            ),
        )
