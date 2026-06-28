"""MVP end-to-end command — Patch 35.

Builds a complete synthetic end-to-end prediction report using only
FIC-* fictional data.  No network.  No env reads.  No live API calls.
No live payload saved.

The E2E pipeline:
  1. synthetic ProviderFetchResult
  2. map_thesportsdb_teams / map_thesportsdb_matches
  3. assemble_match_context_from_mapping_results
  4. save/load replay path
  5. attach_external_context_to_prediction_output
  6. build_web_scout_requests + Disabled/Fake WebScout fallback
  7. build_mvp_report_input
  8. render_chinese_mvp_report
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
    _compute_payload_hash,
)
from oracle_core.free_provider_mappers import (
    map_thesportsdb_teams,
    map_thesportsdb_matches,
    MappingResult,
)
from oracle_core.free_provider_context_assembly import (
    assemble_match_context_from_mapping_results,
    MatchContextAssemblyResult,
)
from oracle_core.mvp_snapshot_replay import (
    MvpSnapshotStore,
    save_mvp_context_snapshot,
    load_mvp_context_snapshot,
    SavedMvpSnapshotMetadata,
)
from oracle_core.prediction_context_boundary import (
    attach_external_context_to_prediction_output,
    ContextualizedPredictionOutput,
)
from oracle_core.web_scout_fallback import (
    build_web_scout_requests,
    run_web_scout_fallback,
    WebScoutResult,
    DisabledWebScoutAdapter,
    DeterministicFakeWebScoutAdapter,
)
from oracle_core.mvp_report_input_builder import (
    build_mvp_report_input,
    MVPReportInput,
)
from oracle_core.chinese_mvp_report_renderer import (
    render_chinese_mvp_report,
)

import tempfile


# ---------------------------------------------------------------------------
# Command result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MvpCommandResult:
    """Result of the MVP end-to-end command."""

    report_text: str
    """The rendered Chinese report string."""

    snapshot_metadata: SavedMvpSnapshotMetadata | None = None
    """Replay snapshot metadata."""

    gap_list: tuple[str, ...] = ()
    """All data gaps."""

    caveats: tuple[str, ...] = ()
    """All caveats."""

    model_output_used: Mapping[str, Any] = field(default_factory=dict)
    """The synthetic model output that was used."""

    completed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Synthetic payloads (FIC-* fictional data only)
# ---------------------------------------------------------------------------


def _build_synthetic_teams_fetch() -> ProviderFetchResult:
    """Build a synthetic TheSportsDB teams fetch result.  FIC-* only."""
    import json
    payload = {
        "teams": [
            {"idTeam": "FIC-001", "strTeam": "Fictional Alpha FC",
             "strCountry": "Fiction"},
            {"idTeam": "FIC-002", "strTeam": "Fictional Beta FC",
             "strCountry": "Fiction"},
        ],
    }
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.TEAMS,
        fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        source_reference="fixture://thesportsdb/searchteams",
        raw_payload_hash=_compute_payload_hash(payload),
        payload=payload,
        license_notes="FIC-* fictional fixture — no license required",
        completeness={"available": True},
    )


def _build_synthetic_matches_fetch() -> ProviderFetchResult:
    """Build a synthetic TheSportsDB matches fetch result.  FIC-* only."""
    import json
    payload = {
        "events": [
            {"idEvent": "FIC-MATCH-001",
             "strEvent": "Fictional Alpha FC vs Fictional Beta FC",
             "idHomeTeam": "FIC-001", "idAwayTeam": "FIC-002",
             "strHomeTeam": "Fictional Alpha FC",
             "strAwayTeam": "Fictional Beta FC",
             "dateEvent": "2026-06-16", "strTime": "20:00:00",
             "strVenue": "Fictional Stadium One"},
        ],
    }
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.MATCHES,
        fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        source_reference="fixture://thesportsdb/events",
        raw_payload_hash=_compute_payload_hash(payload),
        payload=payload,
        license_notes="FIC-* fictional fixture — no license required",
        completeness={"available": True},
    )


def _build_synthetic_model_output() -> dict:
    """Build a synthetic model output for E2E testing.  FIC-* only."""
    return {
        "team_a": "Fictional Alpha FC",
        "team_b": "Fictional Beta FC",
        "expected_goals": [1.45, 0.92],
        "result_probabilities": {
            "team_a_win": 0.48,
            "draw": 0.27,
            "team_b_win": 0.25,
        },
        "score_probabilities": {},
        "top_scores": [
            {"score": [1, 0], "probability": 0.18},
            {"score": [2, 0], "probability": 0.12},
            {"score": [1, 1], "probability": 0.11},
        ],
        "over_under": {"over_2.5": 0.42, "under_2.5": 0.58},
        "advancement_probabilities": {
            "Fictional Alpha FC": 0.65,
            "Fictional Beta FC": 0.35,
        },
        "model_version": "provisional-v1",
        "model_status": "provisional",
        "assumptions": [
            "neutral site",
            "full squad availability (synthetic)",
        ],
        "limitations": [
            "provisional priors — not calibrated against real tournament data",
        ],
    }


# ---------------------------------------------------------------------------
# Synthetic dry-run E2E command
# ---------------------------------------------------------------------------


def build_synthetic_mvp_end_to_end_report(
    *,
    use_fake_scout: bool = False,
) -> MvpCommandResult:
    """Build a complete synthetic MVP end-to-end prediction report.

    Uses only FIC-* fictional data.  No network.  No env reads.
    No real teams.  No live API.  No live payload saved.

    Pipeline:
      1. Build synthetic ProviderFetchResult (teams + matches).
      2. Map through TheSportsDB mappers → MappingResult.
      3. Assemble MatchContextAssemblyResult.
      4. Save/load snapshot replay (temp store).
      5. Attach context to synthetic model_output (boundary).
      6. Build Web Scout requests + run Disabled/Fake fallback.
      7. Build MVPReportInput.
      8. Render Chinese report.

    Args:
        use_fake_scout: If True, use DeterministicFakeWebScoutAdapter.
            Default False (DisabledWebScoutAdapter).

    Returns:
        ``MvpCommandResult`` with report text, metadata, gaps, and caveats.
    """
    # ── Step 1: Synthetic provider fetch results ──
    teams_fetch = _build_synthetic_teams_fetch()
    matches_fetch = _build_synthetic_matches_fetch()

    # ── Step 2: Map to canonical entities ──
    teams_mapping: MappingResult = map_thesportsdb_teams(teams_fetch)
    matches_mapping: MappingResult = map_thesportsdb_matches(matches_fetch)

    # ── Step 3: Assemble context ──
    assembly: MatchContextAssemblyResult = (
        assemble_match_context_from_mapping_results(
            teams_mapping, matches_mapping,
        )
    )

    # ── Step 4: Save + load replay path ──
    tmpdir = tempfile.mkdtemp(prefix="mvp_e2e_")
    store = MvpSnapshotStore(tmpdir)
    saved_meta = save_mvp_context_snapshot(store, assembly)
    loaded_data = load_mvp_context_snapshot(store, saved_meta.snapshot_id)

    # ── Step 5: Build synthetic model output + attach context ──
    model_output = _build_synthetic_model_output()
    contextualized: ContextualizedPredictionOutput = (
        attach_external_context_to_prediction_output(
            model_output=model_output,
            context_snapshot=loaded_data,
            data_gaps=assembly.gap_list,
        )
    )

    # ── Step 6: Web Scout fallback ──
    scout_requests = build_web_scout_requests(
        gap_list=assembly.gap_list,
        match_id="FIC-MATCH-001",
        team_ids=("FIC-001", "FIC-002"),
    )
    if use_fake_scout:
        scout_adapter = DeterministicFakeWebScoutAdapter()
    else:
        scout_adapter = DisabledWebScoutAdapter()
    scout_result: WebScoutResult = run_web_scout_fallback(
        scout_requests, scout_adapter,
    )

    # ── Step 7: Build report input ──
    report_input: MVPReportInput = build_mvp_report_input(
        model_output=model_output,
        context_view_or_assembly_result=assembly,
        market_comparison=None,
        scout_result=scout_result,
    )

    # ── Step 8: Render Chinese report ──
    report_text = render_chinese_mvp_report(report_input)

    # ── Return ──
    return MvpCommandResult(
        report_text=report_text,
        snapshot_metadata=saved_meta,
        gap_list=assembly.gap_list,
        caveats=report_input.caveats,
        model_output_used=model_output,
    )


def run_mvp_prediction_report_command(
    command_input: Mapping[str, Any] | None = None,
) -> MvpCommandResult:
    """Run the MVP prediction report command.

    Currently only supports synthetic/offline dry run.
    Accepts ``command_input`` for future live-mode extension (opt-in only).

    Args:
        command_input: Reserved for future use.  Ignored in current version.

    Returns:
        ``MvpCommandResult``.
    """
    # Future: parse command_input for live mode, match_id, etc.
    # For now: always synthetic dry run.
    return build_synthetic_mvp_end_to_end_report()


# ---------------------------------------------------------------------------
# CLI entry point — python -m oracle_core.mvp_end_to_end_command
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse
    import sys
    import os as _os

    parser = argparse.ArgumentParser(
        description="World Cup Oracle — Synthetic MVP E2E Prediction Report",
        epilog=(
            "This is a SYNTHETIC / OFFLINE command using ONLY FIC-* fictional data. "
            "No live API. No env/API keys. No real teams. "
            "It is NOT a real match prediction command."
        ),
    )
    parser.add_argument(
        "--fake-scout",
        action="store_true",
        help="Use DeterministicFakeWebScoutAdapter (FIC-* synthetic evidence). "
             "Default: DisabledWebScoutAdapter (fail-closed).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write report to file instead of stdout. "
             "Must not be a live/repo data path.",
    )
    parser.add_argument(
        "--json-metadata",
        type=str,
        default=None,
        help="Write JSON metadata (snapshot ID, gaps, caveats) to file.",
    )
    args = parser.parse_args()

    # Enforce: no env/API key reads
    for var in _os.environ:
        if any(token in var.upper() for token in
               ("API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD", "LIVE")):
            print(
                f"[WARNING] Environment variable '{var}' is set. "
                f"This command does NOT use env vars. "
                f"All data is FIC-* synthetic.",
                file=sys.stderr,
            )

    # Run synthetic E2E
    result = build_synthetic_mvp_end_to_end_report(use_fake_scout=args.fake_scout)

    # Output report
    report = result.report_text
    if args.output:
        out_path = _os.path.abspath(args.output)
        # Guard: don't write to repo data dirs
        repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if out_path.startswith(_os.path.join(repo_root, "knowledge")):
            print(
                f"[ERROR] Refusing to write to repo knowledge dir: {out_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Report written to: {out_path}", file=sys.stderr)
    else:
        print(report)

    # Optional JSON metadata
    if args.json_metadata:
        import json as _json
        meta = {
            "snapshot_id": (
                result.snapshot_metadata.snapshot_id
                if result.snapshot_metadata else None
            ),
            "gap_list": list(result.gap_list),
            "caveats": list(result.caveats),
            "model_boundary": {
                "affects_model": False,
                "report_only_or_context_only": True,
                "enters_prediction_engine": False,
            },
            "data_source": "FIC-* synthetic only",
            "live_api_called": False,
            "env_read": False,
            "real_teams_used": False,
            "fake_scout_used": args.fake_scout,
        }
        with open(args.json_metadata, "w", encoding="utf-8") as fh:
            _json.dump(meta, fh, indent=2, sort_keys=True)
        print(f"Metadata written to: {args.json_metadata}", file=sys.stderr)
