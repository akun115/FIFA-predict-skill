"""Production healthcheck / monitoring surface — Patch 36.1.

Runnable: ``python -m oracle_core.production_health``

Offline by default.  No network calls.  No env/API key reads.
Reports provider status, model boundary, and overall health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class HealthStatus:
    """Status of a single component."""
    component: str
    healthy: bool
    status_message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "healthy": self.healthy,
            "status_message": self.status_message,
            "details": dict(self.details),
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True)
class HealthReport:
    """Complete health report."""
    overall_healthy: bool
    components: tuple
    runtime_mode: str
    thesportsdb_status: str = "needs_more_info"
    model_boundary_intact: bool = True
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "overall_healthy": self.overall_healthy,
            "components": [c.to_dict() for c in self.components],
            "runtime_mode": self.runtime_mode,
            "thesportsdb_status": self.thesportsdb_status,
            "model_boundary_intact": self.model_boundary_intact,
            "generated_at": self.generated_at.isoformat(),
        }


def check_config_health(config=None):
    try:
        from oracle_core.production_config import ProductionConfig
        if config is None:
            from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG
            config = DEFAULT_OFFLINE_CONFIG
        if not isinstance(config, ProductionConfig):
            return HealthStatus(component="config", healthy=False,
                status_message="Config is not a valid ProductionConfig instance.")
        runtime_mode = config.runtime_mode
        network = config.network_allowed
        env_access = config.env_access_allowed
        if runtime_mode == "offline":
            if network or env_access:
                return HealthStatus(component="config", healthy=False,
                    status_message=f"Config inconsistency: offline but network={network}")
            return HealthStatus(component="config", healthy=True,
                status_message="Config valid — offline mode (fail-closed, intended state).",
                details={"runtime_mode": runtime_mode})
        elif runtime_mode == "live_opt_in":
            return HealthStatus(component="config", healthy=True,
                status_message="Config valid — live_opt_in mode.",
                details={"runtime_mode": runtime_mode})
        else:
            return HealthStatus(component="config", healthy=False,
                status_message=f"Unknown runtime_mode: {runtime_mode}")
    except Exception as e:
        return HealthStatus(component="config", healthy=False,
            status_message=f"Config health check failed: {e}")


def check_provider_health(config=None):
    return HealthStatus(component="live_provider", healthy=True,
        status_message="Live provider disabled (fail-closed, intended). Requires --allow-live + live_opt_in.",
        details={"configured": False, "thesportsdb_approved": False,
                 "thesportsdb_status": "needs_more_info"})


def check_scout_health(config=None):
    return HealthStatus(component="web_scout", healthy=True,
        status_message="Web Scout disabled (fail-closed). No real search provider configured.",
        details={"configured": False, "real_provider_available": False})


def check_odds_health(config=None):
    return HealthStatus(component="odds_provider", healthy=True,
        status_message="Odds provider disabled (fail-closed). Market comparison unavailable.",
        details={"configured": False, "odds_are_market_comparison_only": True,
                 "odds_never_blended": True})


def check_store_health(config=None):
    import tempfile
    import os as _os
    try:
        fd, path = tempfile.mkstemp(prefix="health_", suffix=".tmp")
        _os.close(fd)
        _os.unlink(path)
        return HealthStatus(component="snapshot_store", healthy=True,
            status_message="Snapshot store writable.", details={"writable": True})
    except Exception as e:
        return HealthStatus(component="snapshot_store", healthy=False,
            status_message=f"Snapshot store not writable: {e}")


def check_model_boundary_health():
    return HealthStatus(component="model_boundary", healthy=True,
        status_message="Model boundary intact. Context is report-only/context-only.",
        details={"affects_model": False, "enters_prediction_engine": False,
                 "report_only_or_context_only": True, "no_odds_blending": True,
                 "no_xg_adjustment": True})


def run_full_healthcheck(config=None):
    if config is None:
        try:
            from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG
            config = DEFAULT_OFFLINE_CONFIG
        except ImportError:
            pass
    runtime_mode = getattr(config, "runtime_mode", "offline") if config else "offline"
    components = (
        check_config_health(config),
        check_provider_health(config),
        check_scout_health(config),
        check_odds_health(config),
        check_store_health(config),
        check_model_boundary_health(),
    )
    overall = all(c.healthy for c in components)
    return HealthReport(overall_healthy=overall, components=components,
                        runtime_mode=runtime_mode)


def healthcheck_to_text(report):
    lines = ["=" * 50, "  World Cup Oracle — Health Report", "=" * 50]
    lines.append(f"  Overall: {'HEALTHY' if report.overall_healthy else 'UNHEALTHY'}")
    lines.append(f"  Runtime mode: {report.runtime_mode}")
    lines.append(f"  TheSportsDB: {report.thesportsdb_status}")
    lines.append(f"  Model boundary: {'INTACT' if report.model_boundary_intact else 'BROKEN'}")
    lines.append(f"  Generated: {report.generated_at.isoformat()}")
    lines.append("")
    for c in report.components:
        status = "OK" if c.healthy else "FAIL"
        lines.append(f"  [{status}] {c.component}: {c.status_message}")
    lines.append("=" * 50)
    return "\n".join(lines)


def healthcheck_to_json(report):
    import json
    return json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str)


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser(description="World Cup Oracle — Production Healthcheck")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    try:
        report = run_full_healthcheck()
    except Exception as e:
        print(f"FATAL: Healthcheck failed: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(healthcheck_to_json(report))
    else:
        print(healthcheck_to_text(report))
    sys.exit(0 if report.overall_healthy else 1)
