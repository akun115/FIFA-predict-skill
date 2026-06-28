"""Provider contracts and structured failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from football_data.domain import MatchRecord


class Capability(str, Enum):
    RESULTS = "results"
    FIXTURES = "fixtures"


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    capabilities: frozenset[Capability]
    requires_credentials: bool
    attribution_url: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "capabilities": sorted(item.value for item in self.capabilities),
            "requires_credentials": self.requires_credentials,
            "attribution_url": self.attribution_url,
        }


class ProviderError(RuntimeError):
    category = "provider"


class ProviderConfigurationError(ProviderError):
    category = "configuration"


class ProviderUnavailableError(ProviderError):
    category = "unavailable"


class ProviderSchemaError(ProviderError):
    category = "schema"


class MatchProvider(Protocol):
    descriptor: ProviderDescriptor

    def get_matches(self, competition: str, season: str) -> tuple[MatchRecord, ...]: ...
