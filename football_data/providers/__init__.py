"""Football data provider adapters."""

from .football_data_org import FootballDataOrgProvider
from .openfootball import OpenFootballProvider

__all__ = ["FootballDataOrgProvider", "OpenFootballProvider"]
