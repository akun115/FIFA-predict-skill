"""Provider routing and match-context orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .cache import SQLiteResponseCache
from .domain import MatchRecord, Provenance
from .entities import EntityAmbiguityError, EntityRegistry
from .providers.base import MatchProvider, ProviderError
from .quality import QualityReport, assess_quality
from .snapshots import SnapshotStore


@dataclass(frozen=True)
class MatchContext:
    records: tuple[MatchRecord, ...]
    quality: QualityReport
    snapshot_id: str

    def to_dict(self) -> dict:
        return {
            "records": [record.to_dict() for record in self.records],
            "quality": self.quality.to_dict(),
            "snapshot_id": self.snapshot_id,
        }


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_from_dict(value: dict) -> MatchRecord:
    source = value["provenance"]
    return MatchRecord(
        match_id=value["match_id"],
        competition_id=value["competition_id"],
        kickoff=_parse_time(value["kickoff"]),
        home_team=value["home_team"],
        away_team=value["away_team"],
        status=value["status"],
        home_score=value["home_score"],
        away_score=value["away_score"],
        provenance=Provenance(
            provider=source["provider"],
            provider_object_id=source["provider_object_id"],
            retrieved_at=_parse_time(source["retrieved_at"]),
            observed_at=_parse_time(source["observed_at"]),
            warnings=tuple(source.get("warnings", [])),
        ),
    )


class FootballDataHub:
    def __init__(
        self,
        *,
        cache: SQLiteResponseCache,
        registry: EntityRegistry,
        snapshots: SnapshotStore,
        providers: list[MatchProvider],
        cache_ttl_seconds: float = 6 * 60 * 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.cache = cache
        self.registry = registry
        self.snapshots = snapshots
        self.providers = list(providers)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_errors: dict[str, str] = {}

    def _enabled(self, provider: MatchProvider) -> bool:
        if not provider.descriptor.requires_credentials:
            return True
        return bool(getattr(provider, "token", ""))

    def provider_status(self) -> list[dict]:
        result = []
        for provider in self.providers:
            item = provider.descriptor.to_dict()
            item["enabled"] = self._enabled(provider)
            item["last_error"] = self._last_errors.get(provider.descriptor.name)
            result.append(item)
        return result

    def sync_matches(
        self,
        competition: str,
        season: str,
        *,
        as_of: datetime,
        allow_stale: bool = False,
    ) -> MatchContext:
        if not competition.strip() or not season.strip():
            raise ValueError("competition and season must not be empty")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        retrieval_time = self.clock()
        if retrieval_time.tzinfo is None or retrieval_time.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        cache_time = retrieval_time.timestamp()
        params = {"competition": competition, "season": season}
        errors: list[str] = []
        records: tuple[MatchRecord, ...] = ()
        used_cache = False
        stale_fields: set[str] = set()

        for provider in self.providers:
            name = provider.descriptor.name
            if not self._enabled(provider):
                errors.append(f"{name}: configuration")
                continue
            hit = self.cache.get(name, "matches", params, now=cache_time)
            if hit is not None:
                records = tuple(_record_from_dict(item) for item in hit.value)
                used_cache = True
                break
            try:
                records = provider.get_matches(competition, season)
                self.cache.put(
                    name,
                    "matches",
                    params,
                    [record.to_dict() for record in records],
                    ttl_seconds=self.cache_ttl_seconds,
                    now=cache_time,
                )
                self._last_errors.pop(name, None)
                break
            except ProviderError as error:
                self._last_errors[name] = error.category
                errors.append(f"{name}: {error.category}")
                if allow_stale:
                    hit = self.cache.get(
                        name,
                        "matches",
                        params,
                        now=cache_time,
                        allow_stale=True,
                    )
                    if hit is not None:
                        records = tuple(_record_from_dict(item) for item in hit.value)
                        used_cache = True
                        stale_fields.add("matches")
                        break

        blocked: list[str] = []
        if any(
            record.provenance.observed_at is not None
            and record.provenance.observed_at > as_of
            for record in records
        ):
            records = tuple(
                record
                for record in records
                if record.provenance.observed_at is None
                or record.provenance.observed_at <= as_of
            )
            blocked.append("matches observed after cutoff")

        for record in records:
            for team in (record.home_team, record.away_team):
                try:
                    entity_id = self.registry.resolve("team", name=team)
                    if entity_id is None:
                        entity_id = self.registry.create("team", team)
                        self.registry.add_alias(
                            entity_id, record.provenance.provider, "", team
                        )
                except EntityAmbiguityError:
                    blocked.append(f"ambiguous team: {team}")

        quality = assess_quality(
            required={"matches"},
            available={"matches"} if records else set(),
            as_of=as_of,
            stale=stale_fields,
            provider_errors=tuple(errors),
            blocked=tuple(blocked),
            used_cache=used_cache,
        )
        payload = {
            "competition": competition,
            "season": season,
            "records": [record.to_dict() for record in records],
        }
        snapshot_id = self.snapshots.record("match-context", payload, quality)
        return MatchContext(records, quality, snapshot_id)
