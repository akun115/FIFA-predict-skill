"""Environment-backed data hub settings."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class DataHubSettings:
    database_path: Path = Path.home() / ".world-cup-oracle" / "data-hub.sqlite3"
    max_cache_bytes: int = 500 * 1024 * 1024
    football_data_org_token: str = field(default="", repr=False)
    request_timeout_seconds: float = 15.0
    openfootball_base_url: str = "https://raw.githubusercontent.com/openfootball/football.json/master"
    football_data_org_base_url: str = "https://api.football-data.org/v4"

    @property
    def football_data_org_enabled(self) -> bool:
        return bool(self.football_data_org_token)

    @classmethod
    def from_env(cls, *, database_path: str = "") -> "DataHubSettings":
        cache_mb = int(os.environ.get("WORLD_CUP_ORACLE_CACHE_MB", "500"))
        if cache_mb < 1:
            raise ValueError("WORLD_CUP_ORACLE_CACHE_MB must be at least 1")
        path = database_path or os.environ.get("WORLD_CUP_ORACLE_DB", "")
        return cls(
            database_path=Path(path) if path else cls().database_path,
            max_cache_bytes=cache_mb * 1024 * 1024,
            football_data_org_token=os.environ.get("FOOTBALL_DATA_ORG_TOKEN", ""),
        )

    def public_summary(self) -> dict:
        return {
            "database_path": str(self.database_path),
            "max_cache_bytes": self.max_cache_bytes,
            "request_timeout_seconds": self.request_timeout_seconds,
            "providers": {
                "openfootball": {"enabled": True, "base_url": self.openfootball_base_url},
                "football-data.org": {
                    "enabled": self.football_data_org_enabled,
                    "base_url": self.football_data_org_base_url,
                },
            },
        }
