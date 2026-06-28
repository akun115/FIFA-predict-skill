"""Data quality validator — Data Service v1.

Patch 17 + 17.1 — comprehensive validation rules for provider provenance,
fetch results, canonical entities, MatchContextSnapshot, forbidden model
output keys, and model boundary report_only checks.

Pure functions; no prediction engine integration.  No live providers.
No network.

IMPORTANT — this validator is an *audit and reporting* tool, NOT a
prediction gate.  BLOCKING severity issues are informational — the
caller decides whether to proceed with prediction.  The validator
does not modify probabilities, adjust xG, or call the prediction engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from oracle_core.data_service_types import DataQualityIssue, DataQualitySeverity


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationReport:
    """Aggregated result of running validation rules against a subject."""

    subject_id: str
    subject_type: str
    issues: tuple[DataQualityIssue, ...] = ()

    @property
    def has_blocking(self) -> bool:
        return any(issue.blocking for issue in self.issues)

    @property
    def has_errors(self) -> bool:
        return any(
            issue.severity in (DataQualitySeverity.ERROR, DataQualitySeverity.BLOCKING)
            for issue in self.issues
        )

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == DataQualitySeverity.WARNING)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == DataQualitySeverity.ERROR)

    @property
    def blocking_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == DataQualitySeverity.BLOCKING)

    def by_severity(self, severity: DataQualitySeverity) -> tuple[DataQualityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == severity)

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "issues": [i.to_dict() for i in self.issues],
            "has_blocking": self.has_blocking,
            "has_errors": self.has_errors,
            "counts": {
                "total": len(self.issues),
                "info": sum(1 for i in self.issues if i.severity == DataQualitySeverity.INFO),
                "warning": self.warning_count,
                "error": self.error_count,
                "blocking": self.blocking_count,
            },
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue(
    severity: DataQualitySeverity,
    code: str,
    message: str,
    field_path: str | None = None,
    provenance_refs: tuple[str, ...] = (),
) -> DataQualityIssue:
    return DataQualityIssue(
        severity=severity, code=code, message=message,
        field_path=field_path, provenance_refs=provenance_refs,
    )


def has_blocking_issues(issues: Sequence[DataQualityIssue]) -> bool:
    """Return ``True`` if any issue has severity ``BLOCKING``."""
    return any(i.blocking for i in issues)


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_valid_64hex(s: str) -> bool:
    return bool(_HEX64_RE.match(s))


def _is_aware_datetime_str(s: str) -> bool:
    """Check if *s* is a parseable ISO-8601 string with timezone info."""
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return False
    return dt.tzinfo is not None and dt.utcoffset() is not None


def _try_parse_iso(s: str) -> datetime | None:
    """Parse ISO string; preserve naive (do NOT auto-convert to UTC).

    Callers that need UTC comparison should check ``tzinfo`` and convert
    explicitly if appropriate.
    """
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _try_parse_iso_utc(s: str) -> datetime | None:
    """Parse ISO string; if naive, assume UTC (for comparison use)."""
    dt = _try_parse_iso(s)
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Forbidden model output keys (recursive scan) ──

_FORBIDDEN_MODEL_KEYS = frozenset({
    "result_probabilities", "expected_goals", "top_scores",
    "over_under", "over_under_probabilities", "advancement_probabilities",
    "prediction", "predicted_score", "model_probability", "model_probabilities",
})


def _scan_forbidden_model_keys(
    data: Any, path: str = "$", issues: list[DataQualityIssue] | None = None,
) -> list[DataQualityIssue]:
    """Recursively scan *data* for forbidden model output keys.

    Returns a list of BLOCKING issues, one per forbidden key found.
    """
    if issues is None:
        issues = []
    if isinstance(data, dict):
        for key, val in data.items():
            if key in _FORBIDDEN_MODEL_KEYS:
                issues.append(_issue(
                    DataQualitySeverity.BLOCKING,
                    "MODEL_BOUNDARY_FORBIDDEN_MODEL_OUTPUT",
                    f"Forbidden model output key '{key}' found in data at {path}",
                    field_path=f"{path}.{key}",
                ))
            _scan_forbidden_model_keys(val, f"{path}.{key}", issues)
    elif isinstance(data, (list, tuple)):
        for i, item in enumerate(data):
            _scan_forbidden_model_keys(item, f"{path}[{i}]", issues)
    return issues


# ── Model boundary report_only checks ──

_CONTEXT_FIELD_CHECKS: tuple[tuple[str, str], ...] = (
    ("odds_context", "odds_context"),
    ("lineup_context", "lineup_context"),
    ("injury_context", "injury_context"),
    ("suspension_context", "suspension_context"),
    ("prematch_signals", "prematch_signals"),
)


def _check_context_report_only(data: dict) -> list[DataQualityIssue]:
    """Verify all context fields have ``report_only=True`` or equivalent."""
    issues: list[DataQualityIssue] = []
    for key, label in _CONTEXT_FIELD_CHECKS:
        ctx = data.get(key)
        if ctx is None:
            continue
        items = ctx if isinstance(ctx, (list, tuple)) else [ctx]
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            ro = item.get("report_only")
            co = item.get("context_only")
            if ro is False or co is False:
                issues.append(_issue(
                    DataQualitySeverity.BLOCKING,
                    "MODEL_BOUNDARY_CONTEXT_NOT_REPORT_ONLY",
                    f"{label}[{i}]: report_only=False or context_only=False — "
                    f"model boundary violation; context data must not feed prediction engine.",
                    field_path=f"{label}[{i}]",
                ))
            elif ro is not True and co is not True:
                issues.append(_issue(
                    DataQualitySeverity.ERROR,
                    "MODEL_BOUNDARY_CONTEXT_NOT_REPORT_ONLY",
                    f"{label}[{i}]: missing report_only/context_only flag — "
                    f"model boundary unclear.",
                    field_path=f"{label}[{i}]",
                ))
    return issues


# ==========================================================================
# Public API — provider provenance validation
# ==========================================================================


def validate_provider_provenance(
    prov: Any,
    *,
    subject_id: str = "",
) -> tuple[DataQualityIssue, ...]:
    """Validate a ``ProviderProvenance`` dataclass or dict.

    Returns issues; BLOCKING = required field missing or invalid.
    """
    issues: list[DataQualityIssue] = []
    d = prov.to_dict() if hasattr(prov, "to_dict") else (prov if isinstance(prov, dict) else {})

    # provider_name
    pn = d.get("provider_name")
    if not pn or (isinstance(pn, str) and not pn.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_PROVIDER_NAME_MISSING", "provider_name is missing.",
            field_path="provider_name"))

    # adapter_version
    av = d.get("adapter_version")
    if not av or (isinstance(av, str) and not av.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_ADAPTER_VERSION_MISSING", "adapter_version is missing.",
            field_path="adapter_version"))

    # fetched_at
    fa = d.get("fetched_at")
    if fa is None:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_FETCHED_AT_MISSING", "fetched_at is missing.",
            field_path="fetched_at"))
    elif isinstance(fa, str):
        dt = _try_parse_iso(fa)
        if dt is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "PROV_FETCHED_AT_INVALID", f"fetched_at is unparseable: {fa!r}",
                field_path="fetched_at"))
        elif dt.tzinfo is None or dt.utcoffset() is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "PROV_FETCHED_AT_NAIVE", "fetched_at is naive (no timezone).",
                field_path="fetched_at"))
    elif hasattr(fa, "tzinfo"):
        if fa.tzinfo is None or fa.utcoffset() is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "PROV_FETCHED_AT_NAIVE", "fetched_at is naive (no timezone).",
                field_path="fetched_at"))

    # raw_payload_hash
    rh = d.get("raw_payload_hash")
    if not rh:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_RAW_HASH_MISSING", "raw_payload_hash is missing.",
            field_path="raw_payload_hash"))
    elif isinstance(rh, str) and not _is_valid_64hex(rh):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_RAW_HASH_INVALID",
            f"raw_payload_hash must be 64-char lowercase hex, got: {rh!r}",
            field_path="raw_payload_hash"))

    # source_reference
    sr = d.get("source_reference")
    if not sr or (isinstance(sr, str) and not sr.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "PROV_SOURCE_REFERENCE_MISSING", "source_reference is missing.",
            field_path="source_reference"))

    return tuple(issues)


# ==========================================================================
# Public API — provider fetch result validation
# ==========================================================================


def validate_provider_fetch_result(
    result: Any,
    *,
    subject_id: str = "",
) -> tuple[DataQualityIssue, ...]:
    """Validate a ``ProviderFetchResult`` dataclass or dict.

    Checks mandatory envelope fields and scans payload for forbidden
    model output keys.
    """
    issues: list[DataQualityIssue] = []
    d = result.to_dict() if hasattr(result, "to_dict") else (result if isinstance(result, dict) else {})

    # Mandatory fields
    for key, code, label in (
        ("provider_name", "RESULT_PROVIDER_NAME_MISSING", "provider_name"),
        ("adapter_version", "RESULT_ADAPTER_VERSION_MISSING", "adapter_version"),
        ("capability", "RESULT_CAPABILITY_MISSING", "capability"),
        ("source_reference", "RESULT_SOURCE_REFERENCE_MISSING", "source_reference"),
    ):
        val = d.get(key)
        if not val or (isinstance(val, str) and not val.strip()):
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                code, f"{label} is missing.", field_path=key))

    # raw_payload_hash
    rh = d.get("raw_payload_hash")
    if not rh:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "RESULT_RAW_HASH_MISSING", "raw_payload_hash is missing.",
            field_path="raw_payload_hash"))
    elif isinstance(rh, str) and not _is_valid_64hex(rh):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "RESULT_RAW_HASH_INVALID",
            f"raw_payload_hash must be 64-char lowercase hex.",
            field_path="raw_payload_hash"))

    # fetched_at
    fa = d.get("fetched_at")
    if fa is None:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "RESULT_FETCHED_AT_MISSING", "fetched_at is missing.",
            field_path="fetched_at"))
    elif isinstance(fa, str):
        dt = _try_parse_iso(fa)
        if dt is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "RESULT_FETCHED_AT_INVALID", f"fetched_at unparseable.",
                field_path="fetched_at"))
        elif dt.tzinfo is None or dt.utcoffset() is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "RESULT_FETCHED_AT_NAIVE", "fetched_at is naive.",
                field_path="fetched_at"))

    # completeness
    comp = d.get("completeness") or {}
    if isinstance(comp, dict) and not comp:
        issues.append(_issue(DataQualitySeverity.WARNING,
            "RESULT_COMPLETENESS_EMPTY", "completeness metadata is empty.",
            field_path="completeness"))

    # warnings
    warns = d.get("warnings") or []
    if warns:
        issues.append(_issue(DataQualitySeverity.INFO,
            "RESULT_HAS_WARNINGS",
            f"Provider result carries {len(warns)} warning(s).",
            field_path="warnings"))

    # Forbidden model output scan on entire result
    _scan_forbidden_model_keys(d, "$", issues)

    return tuple(issues)


# ==========================================================================
# Public API — canonical entity validation
# ==========================================================================


def validate_canonical_team(
    team: Any,
    *,
    subject_id: str = "",
) -> tuple[DataQualityIssue, ...]:
    """Validate a ``CanonicalTeam`` dataclass or dict."""
    issues: list[DataQualityIssue] = []
    d = team.to_dict() if hasattr(team, "to_dict") else (team if isinstance(team, dict) else {})

    # team_id
    tid = d.get("team_id")
    if not tid or (isinstance(tid, str) and not tid.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "TEAM_ID_MISSING", "team_id is missing.", field_path="team_id"))

    # display_name
    dn = d.get("display_name")
    if not dn or (isinstance(dn, str) and not dn.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "TEAM_DISPLAY_NAME_MISSING", "display_name is missing.",
            field_path="display_name"))

    # provenance_refs
    pr = d.get("provenance_refs") or []
    if not pr:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "TEAM_PROVENANCE_MISSING", "provenance_refs is empty.",
            field_path="provenance_refs"))

    # data_quality — propagate existing blocking issues
    dq = d.get("data_quality") or []
    for iq in (dq if isinstance(dq, (list, tuple)) else []):
        sev_str = iq.get("severity") if isinstance(iq, dict) else getattr(iq, "severity", None)
        if sev_str and str(sev_str) in ("blocking", "BLOCKING"):
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "TEAM_HAS_BLOCKING_DQ",
                f"CanonicalTeam data_quality already contains blocking issue.",
                field_path="data_quality"))
            break

    # country_code missing → INFO
    if not d.get("country_code"):
        issues.append(_issue(DataQualitySeverity.INFO,
            "TEAM_COUNTRY_CODE_MISSING", "country_code is missing.",
            field_path="country_code"))

    return tuple(issues)


def validate_canonical_match(
    match: Any,
    *,
    subject_id: str = "",
) -> tuple[DataQualityIssue, ...]:
    """Validate a ``CanonicalMatch`` dataclass or dict."""
    issues: list[DataQualityIssue] = []
    d = match.to_dict() if hasattr(match, "to_dict") else (match if isinstance(match, dict) else {})

    # match_id
    mid = d.get("match_id")
    if not mid or (isinstance(mid, str) and not mid.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_ID_MISSING", "match_id is missing.", field_path="match_id"))

    # team ids
    ta = d.get("team_a_id")
    tb = d.get("team_b_id")
    if not ta or (isinstance(ta, str) and not ta.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_TEAM_A_MISSING", "team_a_id is missing.", field_path="team_a_id"))
    if not tb or (isinstance(tb, str) and not tb.strip()):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_TEAM_B_MISSING", "team_b_id is missing.", field_path="team_b_id"))
    if ta and tb and ta == tb:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_SAME_TEAM", "team_a_id == team_b_id; match cannot have same team on both sides.",
            field_path="team_a_id"))

    # kickoff_at
    ka = d.get("kickoff_at")
    if ka is None:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_KICKOFF_MISSING", "kickoff_at is missing.", field_path="kickoff_at"))
    elif isinstance(ka, str):
        dt = _try_parse_iso(ka)
        if dt is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "MATCH_KICKOFF_INVALID", f"kickoff_at unparseable: {ka!r}",
                field_path="kickoff_at"))
        elif dt.tzinfo is None or dt.utcoffset() is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "MATCH_KICKOFF_NAIVE", "kickoff_at is naive (no timezone).",
                field_path="kickoff_at"))
    elif hasattr(ka, "tzinfo") and (ka.tzinfo is None or ka.utcoffset() is None):
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_KICKOFF_NAIVE", "kickoff_at is naive.", field_path="kickoff_at"))

    # stage
    st = d.get("stage")
    if not st:
        issues.append(_issue(DataQualitySeverity.ERROR,
            "MATCH_STAGE_MISSING", "stage is missing.", field_path="stage"))

    # provenance_refs
    pr = d.get("provenance_refs") or []
    if not pr:
        issues.append(_issue(DataQualitySeverity.BLOCKING,
            "MATCH_PROVENANCE_MISSING", "provenance_refs is empty.",
            field_path="provenance_refs"))

    # data_quality propagation
    dq = d.get("data_quality") or []
    for iq in (dq if isinstance(dq, (list, tuple)) else []):
        sev_str = iq.get("severity") if isinstance(iq, dict) else getattr(iq, "severity", None)
        if sev_str and str(sev_str) in ("blocking", "BLOCKING"):
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "MATCH_HAS_BLOCKING_DQ",
                "CanonicalMatch data_quality already contains blocking issue.",
                field_path="data_quality"))
            break

    # venue
    if not d.get("venue"):
        issues.append(_issue(DataQualitySeverity.INFO,
            "MATCH_VENUE_MISSING", "venue is missing.", field_path="venue"))

    # stage-specific
    if st and st.lower() == "group" and not d.get("group"):
        issues.append(_issue(DataQualitySeverity.WARNING,
            "MATCH_GROUP_MISSING", "Group-stage match missing group field.",
            field_path="group"))
    if st and st.lower() not in ("group", "") and not d.get("round_name"):
        issues.append(_issue(DataQualitySeverity.WARNING,
            "MATCH_ROUND_NAME_MISSING", "Knockout match missing round_name.",
            field_path="round_name"))

    return tuple(issues)


# ==========================================================================
# Public API — MatchContextSnapshot / snapshot dict validation
# ==========================================================================


def _check_missing_kickoff(snapshot: dict) -> list[DataQualityIssue]:
    match = snapshot.get("match") or {}
    kickoff = match.get("kickoff_at")
    if kickoff is None or (isinstance(kickoff, str) and not kickoff.strip()):
        return [_issue(DataQualitySeverity.BLOCKING,
            "MISSING_KICKOFF", "Kickoff time is not present.",
            field_path="match.kickoff_at")]
    if isinstance(kickoff, str) and not _is_aware_datetime_str(kickoff):
        return [_issue(DataQualitySeverity.BLOCKING,
            "INVALID_KICKOFF", f"Kickoff is not a valid tz-aware ISO: {kickoff!r}",
            field_path="match.kickoff_at")]
    return []


def _check_missing_match_id(snapshot: dict) -> list[DataQualityIssue]:
    match = snapshot.get("match") or {}
    mid = match.get("match_id")
    if mid is None or (isinstance(mid, str) and not mid.strip()):
        return [_issue(DataQualitySeverity.BLOCKING,
            "MISSING_MATCH_ID", "Match ID is not present.",
            field_path="match.match_id")]
    return []


def _check_missing_team_mapping(snapshot: dict) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for key, label in (("team_a", "team_a"), ("team_b", "team_b")):
        team = snapshot.get(key)
        if team is None:
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "MISSING_TEAM_MAPPING", f"{label} is missing.",
                field_path=key))
        elif isinstance(team, dict) and not team.get("team_id", "").strip():
            issues.append(_issue(DataQualitySeverity.BLOCKING,
                "MISSING_TEAM_MAPPING", f"{label}.team_id is empty.",
                field_path=f"{key}.team_id"))
    return issues


def _check_knockout_missing_bracket(
    snapshot: dict,
    require_bracket: bool = False,
) -> list[DataQualityIssue]:
    """Knockout matches without bracket context.

    Default: WARNING (validator is advisory, not a prediction gate).
    With ``require_bracket=True``: BLOCKING.
    """
    match = snapshot.get("match") or {}
    stage = match.get("stage", "")
    if stage and stage.lower() not in ("group", ""):
        knockout = snapshot.get("knockout_context")
        if knockout is None:
            sev = DataQualitySeverity.BLOCKING if require_bracket else DataQualitySeverity.WARNING
            return [_issue(sev,
                "KNOCKOUT_MISSING_BRACKET",
                f"Knockout stage '{stage}' requires knockout_context; not present. "
                f"(validator is advisory; this does not block prediction unless strict mode is used.)",
                field_path="knockout_context")]
    return []


def _check_stale_lineup(snapshot: dict) -> list[DataQualityIssue]:
    """Lineup staleness check — malformed timestamps now produce issues."""
    issues: list[DataQualityIssue] = []
    match = snapshot.get("match") or {}
    kickoff_str = match.get("kickoff_at")
    if not kickoff_str:
        return issues
    kickoff = _try_parse_iso_utc(kickoff_str)
    if kickoff is None:
        return issues

    lineups = snapshot.get("lineup_context") or []
    for i, lc in enumerate(lineups):
        if not isinstance(lc, dict):
            continue
        lu_str = lc.get("last_updated")
        if not lu_str:
            continue
        if not isinstance(lu_str, str):
            issues.append(_issue(DataQualitySeverity.WARNING,
                "LINEUP_LAST_UPDATED_INVALID",
                f"lineup_context[{i}].last_updated is not a string: {lu_str!r}",
                field_path=f"lineup_context[{i}].last_updated"))
            continue
        lu = _try_parse_iso(lu_str)
        if lu is None:
            issues.append(_issue(DataQualitySeverity.WARNING,
                "LINEUP_LAST_UPDATED_INVALID",
                f"lineup_context[{i}].last_updated is unparseable: {lu_str!r}",
                field_path=f"lineup_context[{i}].last_updated"))
            continue
        if lu.tzinfo is None or lu.utcoffset() is None:
            issues.append(_issue(DataQualitySeverity.WARNING,
                "LINEUP_LAST_UPDATED_NAIVE",
                f"lineup_context[{i}].last_updated is naive (no timezone).",
                field_path=f"lineup_context[{i}].last_updated"))
            continue
        # Convert to UTC for comparison
        lu_utc = lu if lu.tzinfo is not None else lu.replace(tzinfo=timezone.utc)
        if (kickoff - lu_utc) > timedelta(hours=24):
            team_id = lc.get("team_id", "unknown")
            issues.append(_issue(DataQualitySeverity.WARNING,
                "STALE_LINEUP",
                f"Lineup for {team_id} was last updated > 24h before kickoff.",
                field_path=f"lineup_context[{i}].last_updated"))
    return issues


def _check_missing_optional_odds(snapshot: dict) -> list[DataQualityIssue]:
    odds = snapshot.get("odds_context")
    if odds is None:
        match = snapshot.get("match") or {}
        stage = match.get("stage", "")
        sev = DataQualitySeverity.WARNING if stage and stage.lower() != "group" else DataQualitySeverity.INFO
        return [_issue(sev,
            "MISSING_OPTIONAL_ODDS",
            "Odds context not available; market comparison skipped.",
            field_path="odds_context")]
    return []


def _check_single_provider_odds(snapshot: dict) -> list[DataQualityIssue]:
    odds = snapshot.get("odds_context")
    if odds is None or not isinstance(odds, dict):
        return []
    prov_refs = odds.get("provenance_refs") or []
    if len(prov_refs) <= 1:
        return [_issue(DataQualitySeverity.WARNING,
            "SINGLE_PROVIDER_ODDS",
            "Odds data from a single provider; no cross-validation available.",
            field_path="odds_context.provenance_refs")]
    return []


def _check_provenance_completeness(snapshot: dict) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for key, label in (("match", "match"), ("team_a", "team_a"), ("team_b", "team_b")):
        entity = snapshot.get(key)
        if entity is None:
            continue
        prov = entity.get("provenance_refs") if isinstance(entity, dict) else None
        if prov is None or len(prov) == 0:
            issues.append(_issue(DataQualitySeverity.WARNING,
                "MISSING_PROVENANCE", f"{label} has no provenance references.",
                field_path=f"{key}.provenance_refs"))
    return issues


# ── Rule registry ──

_SNAPSHOT_RULES: tuple[tuple[str, Callable[[dict], list[DataQualityIssue]]], ...] = (
    ("blocking", _check_missing_match_id),
    ("blocking", _check_missing_kickoff),
    ("blocking", _check_missing_team_mapping),
    ("knockout", lambda d: _check_knockout_missing_bracket(d, require_bracket=False)),
    ("squad", _check_stale_lineup),
    ("market", _check_missing_optional_odds),
    ("market", _check_single_provider_odds),
    ("provenance", _check_provenance_completeness),
    ("boundary", _check_context_report_only),
    ("forbidden", lambda d: _scan_forbidden_model_keys(d)),
)


def validate_snapshot_dict(
    snapshot: dict[str, Any],
    *,
    snapshot_id: str | None = None,
) -> ValidationReport:
    """Run all validation rules against a snapshot dict.

    *snapshot* should be ``MatchContextSnapshot.to_dict()`` output or a
    canonical dict from the local store.  Includes forbidden model output
    scan and report_only boundary checks.
    """
    sid = snapshot_id or snapshot.get("snapshot_id", "unknown")
    all_issues: list[DataQualityIssue] = []
    for _cat, rule in _SNAPSHOT_RULES:
        all_issues.extend(rule(snapshot))
    return ValidationReport(subject_id=sid, subject_type="MatchContextSnapshot",
                            issues=tuple(all_issues))


# Backward-compat alias
validate_snapshot = validate_snapshot_dict


def validate_match_context_snapshot(
    snapshot: Any,
    *,
    snapshot_id: str | None = None,
) -> ValidationReport:
    """Validate a ``MatchContextSnapshot`` dataclass or dict.

    Accepts either form; converts to dict internally.
    """
    d = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
    return validate_snapshot_dict(d, snapshot_id=snapshot_id)


# ==========================================================================
# Provenance chain validation
# ==========================================================================


def validate_provenance_chain(
    raw_result: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    subject_id: str | None = None,
) -> ValidationReport:
    """Verify that *snapshot* provenance traces back to *raw_result*."""
    issues: list[DataQualityIssue] = []
    sid = subject_id or snapshot.get("snapshot_id", "unknown")
    raw_hash = raw_result.get("raw_payload_hash", "")
    raw_provider = raw_result.get("provider_name", "")

    if not raw_hash:
        issues.append(_issue(DataQualitySeverity.ERROR,
            "RAW_MISSING_HASH", "Raw fetch result missing raw_payload_hash.",
            field_path="raw_result.raw_payload_hash"))
    if not raw_provider:
        issues.append(_issue(DataQualitySeverity.ERROR,
            "RAW_MISSING_PROVIDER", "Raw fetch result missing provider_name.",
            field_path="raw_result.provider_name"))

    prov_refs = snapshot.get("provenance_refs") or []
    if not prov_refs:
        issues.append(_issue(DataQualitySeverity.WARNING,
            "SNAPSHOT_NO_PROVENANCE", "Snapshot has no provenance_refs.",
            field_path="snapshot.provenance_refs"))
    else:
        matched = False
        for ref in prov_refs:
            if isinstance(ref, dict):
                rh = ref.get("raw_payload_hash", "")
                if rh and raw_hash and rh == raw_hash:
                    matched = True
                    break
        if raw_hash and not matched:
            issues.append(_issue(DataQualitySeverity.ERROR,
                "PROVENANCE_CHAIN_BROKEN",
                "No snapshot provenance ref hash matches raw fetch result hash.",
                field_path="snapshot.provenance_refs"))

    return ValidationReport(subject_id=sid, subject_type="ProvenanceChain",
                            issues=tuple(issues))
