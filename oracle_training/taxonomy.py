"""Reviewed tournament categories and explicit team aliases."""

from __future__ import annotations

import unicodedata

from .types import TournamentCategory


TAXONOMY_VERSION = "national-taxonomy-v2"

_TOURNAMENTS = {
    "fifa world cup": TournamentCategory.WORLD_CUP,
    "fifa world cup qualification": TournamentCategory.WORLD_CUP_QUALIFIER,
    "uefa euro": TournamentCategory.CONTINENTAL_FINAL,
    "copa américa": TournamentCategory.CONTINENTAL_FINAL,
    "african cup of nations": TournamentCategory.CONTINENTAL_FINAL,
    "afc asian cup": TournamentCategory.CONTINENTAL_FINAL,
    "gold cup": TournamentCategory.CONTINENTAL_FINAL,
    "ofc nations cup": TournamentCategory.CONTINENTAL_FINAL,
    "oceania nations cup": TournamentCategory.CONTINENTAL_FINAL,
    "aff championship": TournamentCategory.CONTINENTAL_FINAL,
    "uefa euro qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
    "african cup of nations qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
    "afc asian cup qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
    "gold cup qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
    "aff championship qualification": TournamentCategory.CONTINENTAL_QUALIFIER,
    "uefa nations league": TournamentCategory.NATIONS_LEAGUE,
    "concacaf nations league": TournamentCategory.NATIONS_LEAGUE,
    "concacaf nations league qualification": TournamentCategory.NATIONS_LEAGUE,
    "friendly": TournamentCategory.FRIENDLY,
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


def classify_tournament(name: str) -> TournamentCategory:
    return _TOURNAMENTS.get(_normalize(name), TournamentCategory.OTHER)


class AmbiguousTeamMappingError(ValueError):
    pass


class TeamAliasMap:
    version = "national-team-aliases-v1"

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self._aliases = {_normalize(key): value for key, value in (aliases or {}).items()}

    def resolve(self, name: str) -> str:
        if not name.strip():
            raise ValueError("team name must not be empty")
        normalized = _normalize(name)
        return self._aliases.get(normalized, " ".join(name.strip().split()))


