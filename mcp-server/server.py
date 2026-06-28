"""World Cup Oracle MCP server for Claude Code."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib as _hashlib
import json
import os
from pathlib import Path
import sys

MCP_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = MCP_ROOT.parent
for path in (PLUGIN_ROOT, MCP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mcp.server.fastmcp import FastMCP

from football_data.cache import SQLiteResponseCache
from football_data.config import DataHubSettings
from football_data.entities import EntityAmbiguityError, EntityRegistry
from football_data.http import UrllibJsonClient
from football_data.providers import FootballDataOrgProvider, OpenFootballProvider
from football_data.service import FootballDataHub
from football_data.snapshots import SnapshotStore
from oracle_core.fitted import load_current_model
from oracle_core.knockout import (
    ExtraTimePenaltyContext,
    compute_advancement_probabilities,
)
from oracle_core.logging import (
    PredictionLogEntry,
    PredictionLogger,
    _input_hash,
    _score_hash,
)
from oracle_core.model import TeamSnapshot, predict_match as predict_score
from oracle_core.storage import KnowledgeStore
from tools.fetch_live_odds import build_odds_queries
from tools.get_tournament_state import run_get_tournament_state
from tools.query_kb import query_kb
from tools.search_prematch import build_search_queries
from tools.update_post_match import update_post_match


DEFAULT_KNOWLEDGE_ROOT = PLUGIN_ROOT / "knowledge"
DEFAULT_LOG_DIR = PLUGIN_ROOT / "logs" / "predictions"


def _prediction_logger() -> PredictionLogger:
    return PredictionLogger(
        Path(os.environ.get("WORLD_CUP_ORACLE_LOG_DIR", str(DEFAULT_LOG_DIR)))
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fitted_model_hash(fitted_root: Path) -> str:
    """SHA256 of the current model.json artifact."""
    pointer = json.loads((fitted_root / "current.json").read_text(encoding="utf-8"))
    version = str(pointer.get("version", ""))
    model_path = fitted_root / version / "model.json"
    if model_path.is_file():
        return _hashlib.sha256(model_path.read_bytes()).hexdigest()
    return "unknown"


def _build_log_entry(
    *,
    prediction: "Prediction",
    match_id: str,
    category: str,
    neutral_site: bool,
    model_artifact_hash: str,
    input_context_hash: str,
    tournament_context_available: bool,
    source_snapshot_refs: dict[str, str],
) -> PredictionLogEntry:
    match_id_source = "provided" if match_id else "missing"
    return PredictionLogEntry(
        prediction_id=f"pred-{prediction.team_a}-{prediction.team_b}-"
        f"{_now_utc().replace(':', '').replace('-', '').replace('T', '-')[:20]}",
        predicted_at=_now_utc(),
        match_id=match_id,
        match_id_source=match_id_source,
        team_a=prediction.team_a,
        team_b=prediction.team_b,
        model_name=prediction.model_version,
        model_version=prediction.model_version,
        model_artifact_hash=model_artifact_hash,
        input_context_hash=input_context_hash,
        category=category,
        neutral_site=neutral_site,
        expected_goals=prediction.expected_goals,
        result_probabilities=dict(prediction.result_probabilities),
        over_under=dict(getattr(prediction, "over_under", {})),
        top_scores=prediction.top_scores,
        score_matrix_hash=_score_hash(prediction.score_probabilities),
        tournament_context_available=tournament_context_available,
        advancement_probabilities=prediction.advancement_probabilities,
        limitations=prediction.limitations,
        source_snapshot_refs=source_snapshot_refs,
    )


mcp = FastMCP(
    "world-cup-oracle",
    instructions=(
        "Deterministic football score probabilities, knowledge storage, and data-provider tools. "
        "Search-plan tools generate queries; they do not fetch live web data."
    ),
)


_NEUTRAL_CONTEXT_NOTE = (
    "Tournament context detected but not quantitatively modeled;"
    " rotation, motivation, qualification pressure,"
    " and tactical conservatism may affect realized score."
)

_NON_PREMATCH_NOTE = (
    "Tournament context state_mode is '{state_mode}', not 'pre_match';"
    " use pre_match context for forecast-grade predictions."
)

_CONTEXT_PARSE_FAIL_NOTE = (
    "Tournament context JSON could not be parsed;"
    " context not applied to this prediction."
)

_SCHEDULE_INTEGRITY_NOTE = (
    "Schedule integrity warning for group {group}: {issues}."
    " Tournament context may not reflect a valid single-round-robin schedule."
    " Standings and incentives derived from this schedule should be treated"
    " as provisional."
)


def _parse_tournament_context(
    raw: str,
) -> tuple[dict | None, bool, list[str]]:
    """Parse tournament_context_json → (context_dict, available_bool, notes).

    Returns:
        context: Parsed dict or None.
        available: True if context was successfully loaded.
        notes: Warnings or state-mode notes for limitations.
    """
    if not raw or not raw.strip():
        return None, False, []

    try:
        tc = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, False, [_CONTEXT_PARSE_FAIL_NOTE]

    if not isinstance(tc, dict):
        return None, False, [_CONTEXT_PARSE_FAIL_NOTE]

    notes: list[str] = []
    state_mode = tc.get("state_mode", "")
    if state_mode != "pre_match":
        notes.append(_NON_PREMATCH_NOTE.format(state_mode=state_mode or "unknown"))
    notes.append(_NEUTRAL_CONTEXT_NOTE)
    return tc, True, notes


def _enrich_prediction(
    prediction: "Prediction",
    tc: dict | None,
    tc_notes: list[str],
) -> "Prediction":
    """Return a new Prediction with tournament_context injected.

    Probabilities are NEVER modified. Only limitations and the
    tournament_context field are updated.
    """
    if tc is None and not tc_notes:
        return prediction

    # Build a compact tournament_context payload
    ctx_payload: dict | None = None
    if tc is not None:
        ctx_payload = {
            "state_mode": tc.get("state_mode"),
            "state_timestamp_utc": tc.get("state_timestamp_utc"),
            "match_id": tc.get("match_id"),
            "team_a_incentive": tc.get("team_a_incentive"),
            "team_b_incentive": tc.get("team_b_incentive"),
            "excluded_matches": tc.get("excluded_matches"),
            "simultaneous_group_matches": tc.get("simultaneous_group_matches"),
        }
        # Propagate data_quality from tournament_state into the prediction context
        dq = tc.get("data_quality")
        if isinstance(dq, dict):
            ctx_payload["data_quality"] = dq

    current_limits = list(prediction.limitations)
    for note in tc_notes:
        if note not in current_limits:
            current_limits.append(note)

    # If tournament context has a schedule integrity warning, surface it
    if tc is not None:
        dq = tc.get("data_quality")
        if isinstance(dq, dict) and dq.get("status") == "warning":
            issues_text = "; ".join(dq.get("issues", []))
            group = tc.get("match_context", {}).get("group_or_round", "?")
            dq_note = _SCHEDULE_INTEGRITY_NOTE.format(
                group=group, issues=issues_text,
            )
            if dq_note not in current_limits:
                current_limits.append(dq_note)

    return replace(
        prediction,
        tournament_context=ctx_payload,
        limitations=tuple(current_limits),
    )


_ADVANCEMENT_DERIVED_NOTE = (
    "Advancement probabilities are derived from regulation-time probabilities"
    " and do not alter them."
)

_ADVANCEMENT_DEFAULTS_NOTE = (
    "Extra-time/penalty assumptions use default symmetric parameters"
    " (ET resolve probability=0.35, symmetric 50/50)."
)

_ADVANCEMENT_PROVIDED_NOTE = (
    "Extra-time/penalty assumptions were provided by knockout_context."
)

_ADVANCEMENT_WARNING_NOTE = (
    "Advancement context has data quality warning: {issues}."
    " Treat advancement probabilities as provisional."
)

_ADVANCEMENT_NO_TEAMS_NOTE = (
    "Advancement context provided but team_a or team_b is unresolved;"
    " advancement probabilities not computed."
)

_MIXED_CONTEXT_NOTE = (
    "Both tournament_context_json and knockout_context_json were provided;"
    " knockout_context_json is used for advancement_probabilities."
    " Group context is not treated as knockout context."
)


def _parse_knockout_context(raw: str) -> dict | None:
    """Parse knockout_context_json → dict or None."""
    if not raw or not raw.strip():
        return None
    try:
        kc = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(kc, dict):
        return None
    return kc


def _enrich_advancement(
    prediction: "Prediction",
    tc: dict | None,
    kc: dict | None,
) -> "Prediction":
    """Return a new Prediction with advancement_probabilities injected.

    Regulation-time probabilities are NEVER modified. Only the
    advancement_probabilities field and limitations are updated.
    """
    # Determine the knockout context source and detect mixed context
    kc_dict: dict | None = None
    mixed_context = False

    if kc is not None:
        kc_dict = kc
        if tc is not None:
            mixed_context = True  # Both external params provided simultaneously
    elif tc is not None:
        kc_dict = tc.get("knockout_context")

    if kc_dict is None:
        return prediction  # Not a knockout match — nothing to do

    current_limits = list(prediction.limitations)

    if mixed_context and _MIXED_CONTEXT_NOTE not in current_limits:
        current_limits.append(_MIXED_CONTEXT_NOTE)

    team_a = kc_dict.get("team_a")
    team_b = kc_dict.get("team_b")
    if team_a is None or team_b is None:
        if _ADVANCEMENT_NO_TEAMS_NOTE not in current_limits:
            current_limits.append(_ADVANCEMENT_NO_TEAMS_NOTE)
        return replace(prediction, limitations=tuple(current_limits))

    # Build ET/PK context from knockout context if provided
    et_params = kc_dict.get("extra_time_penalty_context")
    et_source = "default"
    et_context = None

    if isinstance(et_params, dict):
        try:
            et_context = ExtraTimePenaltyContext(**et_params)
            et_source = "provided"
        except (TypeError, ValueError):
            et_context = None  # fall back to defaults

    # Capture the actual ET/PK parameters used (default or provided)
    actual_et = et_context if et_context is not None else ExtraTimePenaltyContext()

    # Compute advancement probabilities from regulation-time probs
    reg_probs = dict(prediction.result_probabilities)
    advancement = compute_advancement_probabilities(reg_probs, et_context)
    advancement_dict = {
        "team_a_advances": advancement.team_a_advances,
        "team_b_advances": advancement.team_b_advances,
        "decided_in_regulation": advancement.decided_in_regulation,
        "decided_in_extra_time": advancement.decided_in_extra_time,
        "decided_on_penalties": advancement.decided_on_penalties,
        "team_a_regulation_component": advancement.team_a_regulation_component,
        "team_b_regulation_component": advancement.team_b_regulation_component,
        "team_a_extra_time_component": advancement.team_a_extra_time_component,
        "team_b_extra_time_component": advancement.team_b_extra_time_component,
        "team_a_penalty_component": advancement.team_a_penalty_component,
        "team_b_penalty_component": advancement.team_b_penalty_component,
        # Audit trail — ET/PK parameter source and values
        "et_pk_source": et_source,
        "extra_time_resolves_probability": actual_et.extra_time_resolves_probability,
        "team_a_extra_time_win_share": actual_et.team_a_extra_time_win_share,
        "team_b_extra_time_win_share": actual_et.team_b_extra_time_win_share,
        "team_a_penalty_win_probability": actual_et.team_a_penalty_win_probability,
        "team_b_penalty_win_probability": actual_et.team_b_penalty_win_probability,
    }

    # Build limitations
    if _ADVANCEMENT_DERIVED_NOTE not in current_limits:
        current_limits.append(_ADVANCEMENT_DERIVED_NOTE)

    if et_source == "default":
        if _ADVANCEMENT_DEFAULTS_NOTE not in current_limits:
            current_limits.append(_ADVANCEMENT_DEFAULTS_NOTE)
    else:
        if _ADVANCEMENT_PROVIDED_NOTE not in current_limits:
            current_limits.append(_ADVANCEMENT_PROVIDED_NOTE)

    # Data quality warning
    dq = kc_dict.get("data_quality", {})
    if isinstance(dq, dict) and dq.get("status") == "warning":
        issues = dq.get("issues", [])
        note = _ADVANCEMENT_WARNING_NOTE.format(issues=issues)
        if note not in current_limits:
            current_limits.append(note)

    return replace(
        prediction,
        advancement_probabilities=advancement_dict,
        limitations=tuple(current_limits),
    )


@mcp.tool(name="predict_match")
def predict_match_tool(
    team_a: str,
    team_b: str,
    neutral_site: bool = True,
    home_team: str = "",
    team_a_overrides_json: str = "{}",
    team_b_overrides_json: str = "{}",
    knowledge_root: str = "",
    models_root: str = "",
    category: str = "other",
    tournament_context_json: str = "",
    knockout_context_json: str = "",
) -> str:
    """Calculate deterministic normalized probabilities from a promoted model or fallback.

    Optional tournament_context_json: pre-match state from get_tournament_state.
    When provided, incentives/context are annotated in limitations and output;
    probabilities are NEVER modified by tournament context.

    Optional knockout_context_json: knockout bracket context from get_knockout_state.
    When provided and both teams are resolved, advancement_probabilities are
    computed from regulation-time result_probabilities. Regulation-time
    probabilities are NEVER modified.
    """
    fitted_root = Path(
        models_root
        or os.environ.get(
            "WORLD_CUP_ORACLE_MODELS",
            Path.home() / ".world-cup-oracle" / "models",
        )
    )
    overrides_a = _json_object(team_a_overrides_json, "team_a_overrides_json")
    overrides_b = _json_object(team_b_overrides_json, "team_b_overrides_json")
    ctx_hash = _input_hash(
        team_a, team_b, neutral_site, category,
        home_team, overrides_a, overrides_b,
    )
    logger = _prediction_logger()

    # --- Parse tournament context and knockout context ---
    tc, tc_available, tc_notes = _parse_tournament_context(tournament_context_json)
    kc = _parse_knockout_context(knockout_context_json)

    if (fitted_root / "current.json").is_file():
        fitted = load_current_model(fitted_root)
        prediction = fitted.predict(
            team_a,
            team_b,
            neutral_site=neutral_site,
            category=category,
            home_team=(home_team or None),
        )
        prediction = _enrich_prediction(prediction, tc, tc_notes)
        prediction = _enrich_advancement(prediction, tc, kc)
        payload = prediction.to_dict(include_score_matrix=False)
        artifact_dir = str(fitted_root / fitted.version)
        payload["data_quality"] = {
            "status": "fitted_artifact",
            "training_cutoff": fitted.training_cutoff,
            "artifact": artifact_dir,
        }
        log_entry = _build_log_entry(
            prediction=prediction,
            match_id="",
            category=category,
            neutral_site=neutral_site,
            model_artifact_hash=_fitted_model_hash(fitted_root),
            input_context_hash=ctx_hash,
            tournament_context_available=tc_available,
            source_snapshot_refs={
                "model_artifact": artifact_dir,
                "training_cutoff": fitted.training_cutoff,
            },
        )
        logger.write(log_entry)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    root = Path(knowledge_root) if knowledge_root else DEFAULT_KNOWLEDGE_ROOT
    teams = KnowledgeStore(root).load_teams()
    quality = {"missing_teams": [], "defaults_used": []}
    snapshot_a = _team_snapshot(team_a, teams.get(team_a), overrides_a, quality)
    snapshot_b = _team_snapshot(team_b, teams.get(team_b), overrides_b, quality)
    prediction = predict_score(
        snapshot_a, snapshot_b, neutral_site=neutral_site, home_team=(home_team or None)
    )
    prediction = _enrich_prediction(prediction, tc, tc_notes)
    prediction = _enrich_advancement(prediction, tc, kc)
    payload = prediction.to_dict(include_score_matrix=False)
    quality_status = "complete" if not quality["defaults_used"] else "defaults_used"
    payload["data_quality"] = {**quality, "status": quality_status}
    log_entry = _build_log_entry(
        prediction=prediction,
        match_id="",
        category=category,
        neutral_site=neutral_site,
        model_artifact_hash="provisional-no-artifact",
        input_context_hash=ctx_hash,
        tournament_context_available=tc_available,
        source_snapshot_refs={
            "knowledge_root": str(root),
            "model_version": prediction.model_version,
        },
    )
    logger.write(log_entry)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="get_tournament_state")
def get_tournament_state_tool(
    match_id: str,
    knowledge_root: str = "",
    state_mode: str = "current",
) -> str:
    """Return group standings, qualification scenarios, and tournament incentives for one match.

    state_mode:
      - \"current\" (default): Standings include all completed matches.
      - \"pre_match\": Standings exclude the target match and simultaneous group matches,
        reconstructing the table as it was before kickoff.
    """
    return run_get_tournament_state(
        match_id=match_id,
        knowledge_root=knowledge_root,
        state_mode=state_mode,
    )


@mcp.tool(name="record_prediction")
def record_prediction_tool(
    match_id: str,
    team_a: str,
    team_b: str,
    probabilities_json: str,
    expected_goals_json: str,
    input_snapshot_json: str = "{}",
    replace: bool = False,
    knowledge_root: str = "",
) -> str:
    """Persist a pre-match probability forecast for later settlement."""
    root = Path(knowledge_root) if knowledge_root else DEFAULT_KNOWLEDGE_ROOT
    result = KnowledgeStore(root).record_prediction(
        match_id,
        team_a,
        team_b,
        _json_object(probabilities_json, "probabilities_json"),
        _json_list(expected_goals_json, "expected_goals_json"),
        _json_object(input_snapshot_json, "input_snapshot_json"),
        replace=replace,
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="query_kb")
def query_kb_tool(
    entity_type: str,
    entity_name: str,
    layer: str = "",
    fields: str = "",
    knowledge_root: str = "",
) -> str:
    """Read one entity from the layered YAML knowledge base."""
    result = query_kb(
        entity_type,
        entity_name,
        layer or None,
        [field.strip() for field in fields.split(",") if field.strip()] or None,
        knowledge_root=(knowledge_root or None),
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="update_post_match")
def update_post_match_tool(
    match_id: str,
    date: str,
    stage: str,
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    neutral_site: bool = True,
    stats_json: str = "{}",
    knowledge_root: str = "",
) -> str:
    """Record one verified result, settle its forecast, and update Elo once."""
    result = update_post_match(
        match_id=match_id,
        date=date,
        stage=stage,
        home_team=team_a,
        away_team=team_b,
        score=[score_a, score_b],
        stats=_json_object(stats_json, "stats_json"),
        neutral_site=neutral_site,
        knowledge_root=(knowledge_root or None),
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="calibration_report")
def calibration_report_tool(knowledge_root: str = "") -> str:
    """Report proper scoring and reliability metrics without changing coefficients."""
    root = Path(knowledge_root) if knowledge_root else DEFAULT_KNOWLEDGE_ROOT
    return json.dumps(
        KnowledgeStore(root).calibration_report(), ensure_ascii=False, sort_keys=True
    )


@mcp.tool(name="search_prematch")
def search_prematch_tool(team_a: str, team_b: str, match_date: str) -> str:
    """Generate sourced web-search tasks; this tool does not execute web searches."""
    return json.dumps(
        build_search_queries(team_a, team_b, match_date), ensure_ascii=False, sort_keys=True
    )


@mcp.tool(name="fetch_live_odds")
def fetch_live_odds_tool(team_a: str, team_b: str) -> str:
    """Generate odds-search tasks; this tool does not fetch or verify live odds."""
    return json.dumps(build_odds_queries(team_a, team_b), ensure_ascii=False, sort_keys=True)


def _data_hub(database_path: str = "") -> tuple[FootballDataHub, DataHubSettings]:
    settings = DataHubSettings.from_env(database_path=database_path)
    client = UrllibJsonClient(settings.request_timeout_seconds)
    hub = FootballDataHub(
        cache=SQLiteResponseCache(
            settings.database_path, max_bytes=settings.max_cache_bytes
        ),
        registry=EntityRegistry(settings.database_path),
        snapshots=SnapshotStore(settings.database_path),
        providers=[
            OpenFootballProvider(client, base_url=settings.openfootball_base_url),
            FootballDataOrgProvider(
                client,
                token=settings.football_data_org_token,
                base_url=settings.football_data_org_base_url,
            ),
        ],
    )
    return hub, settings


@mcp.tool(name="provider_status")
def provider_status_tool(database_path: str = "") -> str:
    """Report provider capabilities and availability without exposing credentials."""
    hub, settings = _data_hub(database_path)
    return json.dumps(
        {"settings": settings.public_summary(), "providers": hub.provider_status()},
        ensure_ascii=False,
        sort_keys=True,
    )


@mcp.tool(name="sync_match_context")
def sync_match_context_tool(
    competition: str,
    season: str,
    as_of: str,
    allow_stale: bool = True,
    database_path: str = "",
) -> str:
    """Fetch or cache one competition-season context at an explicit cutoff."""
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    hub, _ = _data_hub(database_path)
    result = hub.sync_matches(
        competition, season, as_of=cutoff, allow_stale=allow_stale
    )
    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)


@mcp.tool(name="resolve_football_entity")
def resolve_football_entity_tool(
    kind: str,
    name: str = "",
    provider: str = "",
    provider_id: str = "",
    database_path: str = "",
) -> str:
    """Resolve a canonical entity without creating an unknown entity."""
    settings = DataHubSettings.from_env(database_path=database_path)
    registry = EntityRegistry(settings.database_path)
    try:
        entity_id = registry.resolve(
            kind, name=name, provider=provider, provider_id=provider_id
        )
        payload = {
            "status": "resolved" if entity_id else "not_found",
            "entity_id": entity_id,
        }
    except EntityAmbiguityError as error:
        payload = {"status": "ambiguous", "entity_id": None, "error": str(error)}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _snapshot(snapshot_id: str, database_path: str) -> dict:
    settings = DataHubSettings.from_env(database_path=database_path)
    value = SnapshotStore(settings.database_path).load(snapshot_id)
    if value is None:
        raise ValueError(f"snapshot not found: {snapshot_id}")
    return value


@mcp.tool(name="get_data_quality")
def get_data_quality_tool(snapshot_id: str, database_path: str = "") -> str:
    """Read an immutable quality report."""
    return json.dumps(
        _snapshot(snapshot_id, database_path)["quality"],
        ensure_ascii=False,
        sort_keys=True,
    )


@mcp.tool(name="get_prediction_snapshot")
def get_prediction_snapshot_tool(snapshot_id: str, database_path: str = "") -> str:
    """Read an immutable data or prediction-input snapshot."""
    return json.dumps(
        _snapshot(snapshot_id, database_path), ensure_ascii=False, sort_keys=True
    )


@mcp.tool(name="cache_status")
def cache_status_tool(database_path: str = "") -> str:
    """Report the evictable cache size."""
    settings = DataHubSettings.from_env(database_path=database_path)
    status = SQLiteResponseCache(
        settings.database_path, max_bytes=settings.max_cache_bytes
    ).status()
    return json.dumps(status, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="purge_cache")
def purge_cache_tool(provider: str = "", database_path: str = "") -> str:
    """Delete only evictable response-cache rows."""
    settings = DataHubSettings.from_env(database_path=database_path)
    removed = SQLiteResponseCache(
        settings.database_path, max_bytes=settings.max_cache_bytes
    ).purge(provider)
    return json.dumps(
        {"removed": removed, "provider": provider or None}, sort_keys=True
    )


def _team_snapshot(
    name: str, stored: dict | None, overrides: dict, quality: dict
) -> TeamSnapshot:
    record = dict(stored or {})
    if stored is None:
        quality["missing_teams"].append(name)
    record.update(overrides)
    values = {}
    for output_key, source_keys, default in (
        ("elo", ("elo",), 1500.0),
        ("attack", ("attack", "attack_rating"), 70.0),
        ("defense", ("defense", "defense_rating"), 70.0),
        ("form", ("form",), 0.0),
        ("availability", ("availability",), 0.0),
    ):
        found = next((record[key] for key in source_keys if key in record), None)
        if found is None:
            found = default
            quality["defaults_used"].append(f"{name}.{output_key}")
        values[output_key] = float(found)
    return TeamSnapshot(name=name, **values)


def _json_object(raw: str, label: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _json_list(raw: str, label: str) -> list:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return value


if __name__ == "__main__":
    mcp.run(transport="stdio")


