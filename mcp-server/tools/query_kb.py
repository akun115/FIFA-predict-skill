"""Query records from the layered YAML knowledge base."""

from pathlib import Path
from typing import Iterable

import yaml


DEFAULT_KB_ROOT = Path(__file__).resolve().parents[2] / "knowledge"
LAYER_MAP = {"L1": "L1-events", "L2": "L2-states", "L3": "L3-patterns"}
ENTITY_FILE_MAP = {
    "team": ("teams.yaml", "teams"),
    "player": ("players.yaml", "players"),
    "coach": ("coaches.yaml", "coaches"),
    "match": ("match-results.yaml", "matches"),
    "lineup": ("lineups.yaml", "lineups"),
    "player_log": ("player-match-logs.yaml", "logs"),
    "pattern": ("tactical-matrix.yaml", None),
    "referee": ("referee-tendency.yaml", "referees"),
    "calibration": ("model-calibration.yaml", None),
}


def query_kb(
    entity_type: str,
    entity_name: str,
    layer: str | None = None,
    fields: list[str] | None = None,
    *,
    knowledge_root: str | Path | None = None,
) -> dict:
    mapping = ENTITY_FILE_MAP.get(entity_type)
    if mapping is None:
        return {"error": "invalid_entity_type", "entity_type": entity_type}
    if layer is not None and layer not in LAYER_MAP:
        return {"error": "invalid_layer", "layer": layer, "valid_layers": list(LAYER_MAP)}

    root = Path(knowledge_root) if knowledge_root is not None else DEFAULT_KB_ROOT
    directories: Iterable[str] = [LAYER_MAP[layer]] if layer else LAYER_MAP.values()
    file_name, top_key = mapping
    for directory in directories:
        path = root / directory / file_name
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        result = _find(data, top_key, entity_type, entity_name)
        if result is not None:
            return _filter_fields(result, fields)
    return {
        "error": "not_found",
        "entity_type": entity_type,
        "entity_name": entity_name,
        "suggestion": "Use sourced pre-match research or record verified data before prediction.",
    }


def _find(data: dict, top_key: str | None, entity_type: str, name: str):
    if top_key is None:
        if entity_type == "calibration" and name == "calibration":
            return data
        if name == "all":
            return data
        return data.get(name)
    records = data.get(top_key, {})
    if isinstance(records, dict):
        return records.get(name)
    if isinstance(records, list):
        return next(
            (
                row for row in records
                if row.get("id") == name or row.get("player") == name or row.get("team") == name
            ),
            None,
        )
    return None


def _filter_fields(data, fields: list[str] | None):
    if not fields or not isinstance(data, dict):
        return data
    return {key: value for key, value in data.items() if key in fields}
