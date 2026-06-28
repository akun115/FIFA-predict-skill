"""Knockout-stage advancement probabilities — pure schema and computation.

Probabilities from ``predict_match`` are NEVER modified.
ET/PK parameters are configurable via ``ExtraTimePenaltyContext``.

Patch 10 adds bracket data structures and ``get_knockout_state()``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Knockout round enumeration
# ---------------------------------------------------------------------------


class KnockoutRound(str, Enum):
    R32 = "R32"
    R16 = "R16"
    QF = "QF"
    SF = "SF"
    THIRD_PLACE = "THIRD_PLACE"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# ET / PK context — tunable parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtraTimePenaltyContext:
    """Controls how a drawn 90-minute result resolves into advancement.

    Defaults are symmetric (50/50) and treat ET resolution as 35% likely
    (i.e. 65% of draws go to penalties). These are placeholder priors
    and should be replaced with empirically-derived values when available.
    """

    extra_time_resolves_probability: float = 0.35
    team_a_extra_time_win_share: float = 0.50
    team_b_extra_time_win_share: float = 0.50
    team_a_penalty_win_probability: float = 0.50
    team_b_penalty_win_probability: float = 0.50

    def __post_init__(self) -> None:
        if not (0 <= self.extra_time_resolves_probability <= 1):
            raise ValueError(
                f"extra_time_resolves_probability must be between 0 and 1, "
                f"got {self.extra_time_resolves_probability}"
            )
        for field_name, value in [
            ("team_a_extra_time_win_share", self.team_a_extra_time_win_share),
            ("team_b_extra_time_win_share", self.team_b_extra_time_win_share),
        ]:
            if not (0 <= value <= 1):
                raise ValueError(f"{field_name} must be between 0 and 1, got {value}")
        if not math.isclose(
            self.team_a_extra_time_win_share + self.team_b_extra_time_win_share, 1.0
        ):
            raise ValueError(
                "team_a_extra_time_win_share + team_b_extra_time_win_share "
                f"must equal 1, got "
                f"{self.team_a_extra_time_win_share + self.team_b_extra_time_win_share}"
            )
        for field_name, value in [
            ("team_a_penalty_win_probability", self.team_a_penalty_win_probability),
            ("team_b_penalty_win_probability", self.team_b_penalty_win_probability),
        ]:
            if not (0 <= value <= 1):
                raise ValueError(f"{field_name} must be between 0 and 1, got {value}")
        if not math.isclose(
            self.team_a_penalty_win_probability + self.team_b_penalty_win_probability,
            1.0,
        ):
            raise ValueError(
                "team_a_penalty_win_probability + team_b_penalty_win_probability "
                f"must equal 1, got "
                f"{self.team_a_penalty_win_probability + self.team_b_penalty_win_probability}"
            )


# ---------------------------------------------------------------------------
# Advancement probabilities — result of the pure computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdvancementProbabilities:
    """Decomposed advancement probabilities for a single knockout match.

    Summation invariant: ``team_a_advances + team_b_advances == 1.0``.

    Component decomposition::

        team_a_advances = team_a_regulation_component
                        + team_a_extra_time_component
                        + team_a_penalty_component

        decided_in_regulation + decided_in_extra_time
            + decided_on_penalties == 1.0
    """

    team_a_advances: float
    team_b_advances: float
    decided_in_regulation: float
    decided_in_extra_time: float
    decided_on_penalties: float
    team_a_regulation_component: float
    team_b_regulation_component: float
    team_a_extra_time_component: float
    team_b_extra_time_component: float
    team_a_penalty_component: float
    team_b_penalty_component: float


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_advancement_probabilities(
    regulation_probs: dict[str, float],
    et_context: ExtraTimePenaltyContext | None = None,
) -> AdvancementProbabilities:
    """Convert 90-minute result probabilities into advancement probabilities.

    Parameters
    ----------
    regulation_probs:
        Dict with keys ``team_a_win``, ``draw``, ``team_b_win``.
        Values must be finite, between 0 and 1, and sum to approximately 1.
    et_context:
        Extra-time / penalty resolution parameters.
        Uses symmetric defaults when ``None``.

    Returns
    -------
    AdvancementProbabilities
        Decomposed advancement probabilities.

    Raises
    ------
    ValueError
        If regulation_probs is missing required keys, contains non-finite
        or out-of-range values, or does not sum to 1 within tolerance.
    """
    if et_context is None:
        et_context = ExtraTimePenaltyContext()

    # -- Validate regulation_probs keys --
    required = {"team_a_win", "draw", "team_b_win"}
    missing = required - set(regulation_probs.keys())
    if missing:
        raise ValueError(
            f"regulation_probs must contain keys {sorted(required)}, "
            f"missing {sorted(missing)}"
        )

    team_a_win = regulation_probs["team_a_win"]
    draw = regulation_probs["draw"]
    team_b_win = regulation_probs["team_b_win"]

    # -- Validate regulation_probs values --
    for key, value in [("team_a_win", team_a_win), ("draw", draw), ("team_b_win", team_b_win)]:
        if not math.isfinite(value):
            raise ValueError(f"{key} must be finite, got {value}")
        if not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1, got {value}")

    prob_sum = team_a_win + draw + team_b_win
    if not math.isclose(prob_sum, 1.0, rel_tol=1e-9):
        raise ValueError(
            f"regulation probabilities must sum to 1, got {prob_sum}"
        )

    # -- Compute decomposition --
    et_resolve = et_context.extra_time_resolves_probability
    et_share_a = et_context.team_a_extra_time_win_share
    et_share_b = et_context.team_b_extra_time_win_share
    pk_a = et_context.team_a_penalty_win_probability
    pk_b = et_context.team_b_penalty_win_probability

    decided_in_regulation = team_a_win + team_b_win
    decided_in_extra_time = draw * et_resolve
    decided_on_penalties = draw * (1.0 - et_resolve)

    team_a_regulation_component = team_a_win
    team_b_regulation_component = team_b_win
    team_a_extra_time_component = draw * et_resolve * et_share_a
    team_b_extra_time_component = draw * et_resolve * et_share_b
    team_a_penalty_component = draw * (1.0 - et_resolve) * pk_a
    team_b_penalty_component = draw * (1.0 - et_resolve) * pk_b

    team_a_advances = (
        team_a_regulation_component
        + team_a_extra_time_component
        + team_a_penalty_component
    )
    team_b_advances = (
        team_b_regulation_component
        + team_b_extra_time_component
        + team_b_penalty_component
    )

    # -- Final sanity check --
    if not math.isclose(team_a_advances + team_b_advances, 1.0):
        raise ValueError(
            f"team_a_advances + team_b_advances must equal 1, "
            f"got {team_a_advances + team_b_advances}"
        )

    return AdvancementProbabilities(
        team_a_advances=team_a_advances,
        team_b_advances=team_b_advances,
        decided_in_regulation=decided_in_regulation,
        decided_in_extra_time=decided_in_extra_time,
        decided_on_penalties=decided_on_penalties,
        team_a_regulation_component=team_a_regulation_component,
        team_b_regulation_component=team_b_regulation_component,
        team_a_extra_time_component=team_a_extra_time_component,
        team_b_extra_time_component=team_b_extra_time_component,
        team_a_penalty_component=team_a_penalty_component,
        team_b_penalty_component=team_b_penalty_component,
    )


# ---------------------------------------------------------------------------
# Bracket slot — source of a team in a knockout match
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BracketSlot:
    """Describes where a team in a knockout match comes from.

    ``source_type`` determines which fields are meaningful:
      - ``group_rank``: *group* and *rank* are set.
      - ``match_winner`` / ``match_loser``: *source_match_id* is set.
      - ``fixed_team``: *resolved_team* holds the team name.
      - ``unknown``: nothing is resolved.
    """

    slot_id: str  # e.g. "1A", "2B", "W-R32-01"
    source_type: str  # group_rank / match_winner / match_loser / fixed_team / unknown
    group: str | None = None
    rank: int | None = None
    source_match_id: str | None = None
    resolved_team: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BracketSlot":
        return cls(
            slot_id=str(data.get("slot_id", "")),
            source_type=str(data.get("source_type", "")),
            group=data.get("group"),
            rank=data.get("rank"),
            source_match_id=data.get("source_match_id"),
            resolved_team=data.get("resolved_team"),
        )


# ---------------------------------------------------------------------------
# Knockout match — one fixture in the bracket
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnockoutMatch:
    """A single knockout-stage fixture with its bracket slots."""

    match_id: str
    round: KnockoutRound
    team_a_slot: BracketSlot
    team_b_slot: BracketSlot
    team_a: str | None = None
    team_b: str | None = None
    kickoff_utc: str | None = None
    status: str = "scheduled"  # scheduled / completed
    regulation_score: tuple[int, int] | None = None
    extra_time_score: tuple[int, int] | None = None
    penalties_score: tuple[int, int] | None = None
    winner: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnockoutMatch":
        reg_score = data.get("regulation_score")
        et_score = data.get("extra_time_score")
        pk_score = data.get("penalties_score")
        return cls(
            match_id=str(data.get("match_id", "")),
            round=KnockoutRound(data["round"]),
            team_a_slot=BracketSlot.from_dict(data.get("team_a_slot", {})),
            team_b_slot=BracketSlot.from_dict(data.get("team_b_slot", {})),
            team_a=data.get("team_a"),
            team_b=data.get("team_b"),
            kickoff_utc=data.get("kickoff_utc"),
            status=str(data.get("status", "scheduled")),
            regulation_score=tuple(reg_score) if reg_score else None,
            extra_time_score=tuple(et_score) if et_score else None,
            penalties_score=tuple(pk_score) if pk_score else None,
            winner=data.get("winner"),
        )


# ---------------------------------------------------------------------------
# Knockout context — the output of get_knockout_state()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnockoutDataQuality:
    """Data quality assessment for a knockout match context."""

    status: str  # "ok" | "warning"
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnockoutContext:
    """Resolved knockout match context suitable for consumption by predict_match.

    Designed as a read-only output — no mutation methods.
    """

    match_id: str
    round: str
    team_a: str | None
    team_b: str | None
    team_a_slot: dict[str, Any]
    team_b_slot: dict[str, Any]
    winner_advances_to: str | None
    loser_eliminated: bool
    extra_time_possible: bool
    penalties_possible: bool
    data_quality: dict[str, Any]


# ---------------------------------------------------------------------------
# Bracket loading
# ---------------------------------------------------------------------------


def load_knockout_bracket(path: str) -> list[KnockoutMatch]:
    """Load a knockout bracket from a YAML file.

    The YAML file must contain a top-level ``bracket`` key whose value is
    a list of match dicts.  If ``bracket`` is absent the whole document is
    treated as a plain list.

    Parameters
    ----------
    path:
        Path to a YAML file on disk.

    Returns
    -------
    list[KnockoutMatch]
        Parsed bracket matches in file order.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the YAML cannot be parsed or a required field is missing.
    """
    import yaml

    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if data is None:
        raise ValueError(f"bracket file {path!r} is empty")

    if isinstance(data, list):
        matches = data
    elif isinstance(data, dict):
        matches = data.get("bracket", [])
    else:
        raise ValueError(f"unexpected YAML root type in {path!r}: {type(data)}")

    if not isinstance(matches, list):
        raise ValueError(f"'bracket' must be a list, got {type(matches)}")

    return [KnockoutMatch.from_dict(m) for m in matches]


# ---------------------------------------------------------------------------
# Knockout state resolver
# ---------------------------------------------------------------------------


def get_knockout_state(
    match_id: str,
    bracket: list[KnockoutMatch],
) -> KnockoutContext:
    """Resolve knockout context for a single match from the bracket.

    The returned context is **annotative** — it describes the bracket
    situation but does NOT modify probabilities.

    Parameters
    ----------
    match_id:
        The match to look up.
    bracket:
        The full knockout bracket (from ``load_knockout_bracket``).

    Returns
    -------
    KnockoutContext
        Resolved context with data_quality assessment.

    Raises
    ------
    ValueError
        If *match_id* is not found in *bracket*.
    """
    # -- Find the match --
    match: KnockoutMatch | None = None
    for m in bracket:
        if m.match_id == match_id:
            match = m
            break

    if match is None:
        raise ValueError(f"match_id {match_id!r} not found in bracket")

    issues: list[str] = []

    # -- Unresolved slots --
    team_a_resolved = match.team_a or match.team_a_slot.resolved_team
    team_b_resolved = match.team_b or match.team_b_slot.resolved_team
    if team_a_resolved is None:
        issues.append("unresolved_slot: team_a")
    if team_b_resolved is None:
        issues.append("unresolved_slot: team_b")

    # -- Completed but missing winner --
    if match.status == "completed" and match.winner is None:
        issues.append("missing_winner")

    # -- Penalties without extra_time_score --
    if match.penalties_score is not None and match.extra_time_score is None:
        issues.append("penalties_without_extra_time_score")

    # -- Find where the winner advances to --
    winner_advances_to: str | None = None
    for other in bracket:
        for slot in (other.team_a_slot, other.team_b_slot):
            if slot.source_match_id == match_id and slot.source_type == "match_winner":
                winner_advances_to = other.match_id
                break
        if winner_advances_to is not None:
            break

    # -- Loser elimination --
    # In THIRD_PLACE and FINAL, the tournament ends for both teams.
    loser_eliminated = match.round not in (
        KnockoutRound.THIRD_PLACE,
        KnockoutRound.FINAL,
    )

    # -- Extra time / penalties possible --
    # All knockout rounds can go to extra time except THIRD_PLACE
    # (which goes straight to penalties).  Penalties are always possible
    # in knockout football.
    extra_time_possible = match.round != KnockoutRound.THIRD_PLACE
    penalties_possible = True

    status = "ok" if not issues else "warning"

    return KnockoutContext(
        match_id=match.match_id,
        round=match.round.value,
        team_a=team_a_resolved,
        team_b=team_b_resolved,
        team_a_slot=dataclasses.asdict(match.team_a_slot),
        team_b_slot=dataclasses.asdict(match.team_b_slot),
        winner_advances_to=winner_advances_to,
        loser_eliminated=loser_eliminated,
        extra_time_possible=extra_time_possible,
        penalties_possible=penalties_possible,
        data_quality={"status": status, "issues": issues},
    )
