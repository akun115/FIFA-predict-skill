"""football-data.org v4 adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Callable

from football_data.domain import MatchRecord, Provenance
from football_data.http import HttpRequestError, JsonHttpClient
from .base import (
    Capability, ProviderConfigurationError, ProviderDescriptor,
    ProviderSchemaError, ProviderUnavailableError,
)


class FootballDataOrgProvider:
    descriptor = ProviderDescriptor(
        "football-data.org",
        frozenset({Capability.RESULTS, Capability.FIXTURES}),
        True,
        "https://www.football-data.org/",
    )

    def __init__(
        self,
        client: JsonHttpClient,
        *,
        token: str,
        base_url: str = "https://api.football-data.org/v4",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def get_matches(self, competition: str, season: str) -> tuple[MatchRecord, ...]:
        if not self.token:
            raise ProviderConfigurationError("football-data.org token is not configured")
        if re.fullmatch(r"[A-Za-z0-9]+", competition) is None:
            raise ValueError("competition must be alphanumeric")
        if re.fullmatch(r"\d{4}", season) is None:
            raise ValueError("season must be four digits")
        url = f"{self.base_url}/competitions/{competition}/matches?season={season}"
        try:
            payload = self.client.get_json(url, headers={"X-Auth-Token": self.token})
        except HttpRequestError as error:
            raise ProviderUnavailableError(
                f"football-data.org request failed: {error.category}"
            ) from error
        try:
            matches = payload["matches"]
            if not isinstance(matches, list):
                raise TypeError
            return tuple(
                self._normalize(competition, item)
                for item in matches
                if item.get("homeTeam", {}).get("name") is not None
                and item.get("awayTeam", {}).get("name") is not None
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderSchemaError("football-data.org response schema is invalid") from error

    def _normalize(self, competition: str, item: dict) -> MatchRecord:
        provider_id = str(item["id"])
        kickoff = datetime.fromisoformat(item["utcDate"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            raise ValueError("utcDate must include timezone")
        kickoff = kickoff.astimezone(timezone.utc)
        home = str(item["homeTeam"]["name"])
        away = str(item["awayTeam"]["name"])
        full_time = item["score"]["fullTime"]
        home_score = full_time.get("home")
        away_score = full_time.get("away")
        if (home_score is None) != (away_score is None):
            raise ValueError("partial score")
        if home_score is not None:
            home_score, away_score = int(home_score), int(away_score)
        observed_at = kickoff + timedelta(hours=3) if home_score is not None else None
        return MatchRecord(
            match_id=f"football-data.org:{provider_id}",
            competition_id=competition,
            kickoff=kickoff,
            home_team=home,
            away_team=away,
            status=str(item["status"]).lower(),
            home_score=home_score,
            away_score=away_score,
            provenance=Provenance(
                "football-data.org", provider_id, self.clock(), observed_at
            ),
        )
