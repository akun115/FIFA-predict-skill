"""Historical international-result ingestion and immutable snapshots."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile

from .taxonomy import TAXONOMY_VERSION, TeamAliasMap, classify_tournament
from .types import DataManifest, HistoricalMatch


@dataclass(frozen=True)
class IngestionResult:
    matches: tuple[HistoricalMatch, ...]
    manifest: DataManifest


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _boolean(raw: str) -> bool:
    value = raw.strip().casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("neutral must be TRUE or FALSE")


def ingest_csv(
    raw: bytes,
    *,
    as_of: date,
    source_url: str,
    aliases: TeamAliasMap | None = None,
) -> IngestionResult:
    alias_map = aliases or TeamAliasMap()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    rejections = {
        "before_start": 0,
        "future": 0,
        "missing_score": 0,
        "negative_score": 0,
        "malformed": 0,
        "duplicate": 0,
        "conflict": 0,
    }
    by_key: dict[tuple[str, str, str], list[HistoricalMatch]] = {}
    source_rows = 0
    for row_number, row in enumerate(reader, start=2):
        source_rows += 1
        try:
            match_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if match_date < date(2002, 1, 1):
                rejections["before_start"] += 1
                continue
            if match_date > as_of:
                rejections["future"] += 1
                continue
            raw_home = row["home_score"].strip()
            raw_away = row["away_score"].strip()
            if not raw_home or not raw_away or raw_home.upper() == "NA" or raw_away.upper() == "NA":
                rejections["missing_score"] += 1
                continue
            home_score, away_score = int(raw_home), int(raw_away)
            if home_score < 0 or away_score < 0:
                rejections["negative_score"] += 1
                continue
            home = alias_map.resolve(row["home_team"])
            away = alias_map.resolve(row["away_team"])
            tournament = row["tournament"].strip()
            neutral = _boolean(row["neutral"])
            key = (match_date.isoformat(), home, away)
            source_id = "international-results:" + hashlib.sha256(
                "|".join(key).encode("utf-8")
            ).hexdigest()[:24]
            match = HistoricalMatch(
                match_date,
                home,
                away,
                home_score,
                away_score,
                tournament,
                neutral,
                classify_tournament(tournament),
                row_number,
                source_id,
            )
            by_key.setdefault(key, []).append(match)
        except (KeyError, TypeError, ValueError, UnicodeError):
            rejections["malformed"] += 1

    accepted: list[HistoricalMatch] = []
    for key in sorted(by_key):
        rows = by_key[key]
        variants = {
            (row.home_score, row.away_score, row.tournament, row.neutral) for row in rows
        }
        if len(variants) > 1:
            rejections["conflict"] += len(rows)
            continue
        accepted.append(rows[0])
        rejections["duplicate"] += len(rows) - 1
    accepted.sort(key=lambda item: (item.date, item.home_team, item.away_team, item.source_row))
    normalized_bytes = _canonical([match.to_dict() for match in accepted])
    teams = {team for match in accepted for team in (match.home_team, match.away_team)}
    manifest = DataManifest(
        source_url=source_url,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=hashlib.sha256(normalized_bytes).hexdigest(),
        as_of=as_of.isoformat(),
        source_rows=source_rows,
        accepted_rows=len(accepted),
        rejections=rejections,
        min_date=accepted[0].date.isoformat() if accepted else None,
        max_date=accepted[-1].date.isoformat() if accepted else None,
        team_count=len(teams),
        taxonomy_version=TAXONOMY_VERSION,
    )
    return IngestionResult(tuple(accepted), manifest)


def write_snapshot(result: IngestionResult, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot-{result.manifest.as_of}-{result.manifest.normalized_sha256[:12]}"
    destination = root / name
    if destination.exists():
        existing = json.loads(
            (destination / "data-manifest.json").read_text(encoding="utf-8")
        )
        if existing != result.manifest.to_dict():
            raise ValueError("snapshot directory exists with different manifest")
        return destination
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=root))
    try:
        payload = _canonical([match.to_dict() for match in result.matches])
        (temporary / "matches.json.gz").write_bytes(gzip.compress(payload, mtime=0))
        (temporary / "data-manifest.json").write_text(
            json.dumps(result.manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination
