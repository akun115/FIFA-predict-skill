"""Chronological annual walk-forward folds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .types import HistoricalMatch


@dataclass(frozen=True)
class AnnualFold:
    test_year: int
    training: tuple[HistoricalMatch, ...]
    test: tuple[HistoricalMatch, ...]
    partial: bool


def annual_folds(
    matches: tuple[HistoricalMatch, ...],
    *,
    first_test_year: int,
    as_of: date,
) -> tuple[AnnualFold, ...]:
    eligible = tuple(sorted(
        (match for match in matches if match.date <= as_of),
        key=lambda item: (item.date, item.home_team, item.away_team, item.source_row),
    ))
    folds: list[AnnualFold] = []
    for year in range(first_test_year, as_of.year + 1):
        training = tuple(match for match in eligible if match.date.year < year)
        test = tuple(match for match in eligible if match.date.year == year)
        if not test:
            continue
        if not training:
            raise ValueError(f"test year {year} has no prior training data")
        folds.append(
            AnnualFold(
                test_year=year,
                training=training,
                test=test,
                partial=(year == as_of.year and as_of < date(year, 12, 31)),
            )
        )
    return tuple(folds)
