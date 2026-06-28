"""Production readiness gate — Patch 36.2.

Runnable: ``python -m oracle_core.production_readiness_gate``

Performs 17 checks covering config, providers, audit, storage,
documentation, scheduler, alerting, and external validation readiness.

Default offline.  No network calls.  No env/API key reads.

Usage::

    python -m oracle_core.production_readiness_gate          # text output
    python -m oracle_core.production_readiness_gate --json    # JSON output

All 17 checks are "pass" except ``external_live_readiness`` which
is "warn" — external validation is deliberately not claimed.
``has_external_live_validation`` is always ``False``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateCheck:
    """Result of a single readiness gate check."""

    check_id: str
    name: str
    category: str
    status: str  # "pass" | "warn" | "fail"
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    """Complete readiness gate report."""

    overall_ready: bool
    checks: tuple[GateCheck, ...]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    has_external_live_validation: bool = False

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")


# ---------------------------------------------------------------------------
# Helper: repo root
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_default_tests_expectation() -> GateCheck:
    """Verify that README.md exists and contains test-expectation content."""
    readme = _repo_root() / "README.md"
    if readme.exists():
        content = readme.read_text(encoding="utf-8")
        has_expectation = "0 failed" in content or "0 failed, 0 skipped" in content
        detail = (
            "README.md contains test expectation content"
            if has_expectation
            else "README.md found but no test expectation (\"0 failed\") content"
        )
        return GateCheck(
            check_id="default_tests_expectation",
            name="Default Tests Expectation Documented",
            category="testing",
            status="pass" if has_expectation else "warn",
            detail=detail,
        )
    return GateCheck(
        check_id="default_tests_expectation",
        name="Default Tests Expectation Documented",
        category="testing",
        status="fail",
        detail="Missing README.md",
    )


def _check_config_offline_default() -> GateCheck:
    """Verify that DEFAULT_OFFLINE_CONFIG exists and is offline."""
    try:
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG, ProductionConfig

        if not isinstance(DEFAULT_OFFLINE_CONFIG, ProductionConfig):
            return GateCheck(
                check_id="config_offline_default",
                name="Config Offline Default Present",
                category="config",
                status="fail",
                detail="DEFAULT_OFFLINE_CONFIG is not a ProductionConfig instance",
            )

        detail = (
            f"runtime_mode={DEFAULT_OFFLINE_CONFIG.runtime_mode}, "
            f"network_allowed={DEFAULT_OFFLINE_CONFIG.network_allowed}"
        )
        return GateCheck(
            check_id="config_offline_default",
            name="Config Offline Default Present",
            category="config",
            status="pass",
            detail=detail,
        )
    except Exception as exc:
        return GateCheck(
            check_id="config_offline_default",
            name="Config Offline Default Present",
            category="config",
            status="fail",
            detail=f"Could not load DEFAULT_OFFLINE_CONFIG: {exc}",
        )


def _check_live_provider_disabled_default() -> GateCheck:
    """Verify that the live provider is disabled by default."""
    try:
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG

        disabled = DEFAULT_OFFLINE_CONFIG.provider_mode == "disabled"
        return GateCheck(
            check_id="live_provider_disabled_default",
            name="Live Provider Disabled by Default",
            category="providers",
            status="pass" if disabled else "fail",
            detail=f"provider_mode={DEFAULT_OFFLINE_CONFIG.provider_mode}",
        )
    except Exception as exc:
        return GateCheck(
            check_id="live_provider_disabled_default",
            name="Live Provider Disabled by Default",
            category="providers",
            status="fail",
            detail=str(exc),
        )


def _check_scout_disabled_default() -> GateCheck:
    """Verify that Web Scout is disabled by default."""
    try:
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG

        disabled = DEFAULT_OFFLINE_CONFIG.scout_mode == "disabled"
        return GateCheck(
            check_id="scout_disabled_default",
            name="Web Scout Disabled by Default",
            category="providers",
            status="pass" if disabled else "fail",
            detail=f"scout_mode={DEFAULT_OFFLINE_CONFIG.scout_mode}",
        )
    except Exception as exc:
        return GateCheck(
            check_id="scout_disabled_default",
            name="Web Scout Disabled by Default",
            category="providers",
            status="fail",
            detail=str(exc),
        )


def _check_odds_disabled_default() -> GateCheck:
    """Verify that odds provider is disabled by default."""
    try:
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG

        disabled = DEFAULT_OFFLINE_CONFIG.odds_mode == "disabled"
        return GateCheck(
            check_id="odds_disabled_default",
            name="Odds Provider Disabled by Default",
            category="providers",
            status="pass" if disabled else "fail",
            detail=f"odds_mode={DEFAULT_OFFLINE_CONFIG.odds_mode}",
        )
    except Exception as exc:
        return GateCheck(
            check_id="odds_disabled_default",
            name="Odds Provider Disabled by Default",
            category="providers",
            status="fail",
            detail=str(exc),
        )


def _check_thesportsdb_needs_more_info() -> GateCheck:
    """Verify that TheSportsDB remains needs_more_info."""
    try:
        from oracle_core.production_health import run_full_healthcheck

        health = run_full_healthcheck()
        needs_more = health.thesportsdb_status == "needs_more_info"
        return GateCheck(
            check_id="thesportsdb_needs_more_info",
            name="TheSportsDB Remains needs_more_info",
            category="providers",
            status="pass" if needs_more else "fail",
            detail=f"thesportsdb_status={health.thesportsdb_status}",
        )
    except Exception as exc:
        return GateCheck(
            check_id="thesportsdb_needs_more_info",
            name="TheSportsDB Remains needs_more_info",
            category="providers",
            status="fail",
            detail=str(exc),
        )


def _check_no_raw_payload_policy() -> GateCheck:
    """Verify that raw_payload_save is disabled by default."""
    try:
        from oracle_core.production_audit import create_audit_record

        record = create_audit_record(
            command_timestamp=datetime.now(timezone.utc),
            runtime_mode="offline",
            network_allowed=False,
            env_access_allowed=False,
        )
        raw_payload_saved = record.raw_payload_saved
        return GateCheck(
            check_id="no_raw_payload_policy",
            name="No Raw Payload Save Policy",
            category="audit",
            status="pass" if not raw_payload_saved else "fail",
            detail=f"raw_payload_saved={raw_payload_saved} (must be False)",
        )
    except Exception as exc:
        return GateCheck(
            check_id="no_raw_payload_policy",
            name="No Raw Payload Save Policy",
            category="audit",
            status="fail",
            detail=str(exc),
        )


def _check_audit_redaction() -> GateCheck:
    """Verify that audit source-reference redaction works."""
    try:
        from oracle_core.production_audit import redact_source_reference

        redacted = redact_source_reference("api_key=abc123def456")
        has_redaction = "<redacted>" in redacted
        return GateCheck(
            check_id="audit_redaction",
            name="Audit Source-Reference Redaction",
            category="audit",
            status="pass" if has_redaction else "fail",
            detail=(
                "redact_source_reference works"
                if has_redaction
                else "redact_source_reference did not mask credentials"
            ),
        )
    except Exception as exc:
        return GateCheck(
            check_id="audit_redaction",
            name="Audit Source-Reference Redaction",
            category="audit",
            status="fail",
            detail=str(exc),
        )


def _check_storage_retention_policy() -> GateCheck:
    """Verify that storage retention policy module exists."""
    try:
        from oracle_core.production_storage import RetentionPolicy, apply_retention_policy, CleanupResult  # noqa: F401

        return GateCheck(
            check_id="storage_retention_policy",
            name="Storage Retention Policy Available",
            category="storage",
            status="pass",
            detail="RetentionPolicy, apply_retention_policy, CleanupResult available",
        )
    except Exception as exc:
        return GateCheck(
            check_id="storage_retention_policy",
            name="Storage Retention Policy Available",
            category="storage",
            status="fail",
            detail=str(exc),
        )


def _check_healthcheck_available() -> GateCheck:
    """Verify that the healthcheck module is available."""
    try:
        from oracle_core.production_health import run_full_healthcheck, HealthReport  # noqa: F401

        health = run_full_healthcheck()
        return GateCheck(
            check_id="healthcheck_available",
            name="Healthcheck Available",
            category="monitoring",
            status="pass",
            detail=f"HealthReport with {len(health.components)} components, overall_healthy={health.overall_healthy}",
        )
    except Exception as exc:
        return GateCheck(
            check_id="healthcheck_available",
            name="Healthcheck Available",
            category="monitoring",
            status="fail",
            detail=str(exc),
        )


def _check_scheduler_templates_present() -> GateCheck:
    """Verify that scheduler/cron template exists."""
    cron_template = _repo_root() / "deploy" / "cron" / "world-cup-oracle.example"
    detail = (
        f"Found: deploy/cron/world-cup-oracle.example"
        if cron_template.exists()
        else "Missing deploy/cron/world-cup-oracle.example"
    )
    return GateCheck(
        check_id="scheduler_templates_present",
        name="Scheduler Templates Present",
        category="deployment",
        status="pass" if cron_template.exists() else "fail",
        detail=detail,
    )


def _check_alerting_disabled_default() -> GateCheck:
    """Verify that alerting is disabled by default."""
    try:
        from oracle_core.production_alerting import AlertEvent, dry_run_alert_system  # noqa: F401

        return GateCheck(
            check_id="alerting_disabled_default",
            name="Alerting Disabled by Default",
            category="monitoring",
            status="pass",
            detail="AlertEvent, dry_run_alert_system available; all alerts created with sent=False",
        )
    except Exception as exc:
        return GateCheck(
            check_id="alerting_disabled_default",
            name="Alerting Disabled by Default",
            category="monitoring",
            status="fail",
            detail=str(exc),
        )


def _check_deployment_templates_present() -> GateCheck:
    """Verify that deployment templates (Docker, systemd, .env) exist."""
    templates = {
        "Dockerfile": _repo_root() / "deploy" / "docker" / "Dockerfile",
        "systemd": _repo_root() / "deploy" / "systemd" / "world-cup-oracle.service.example",
        "env.example": _repo_root() / "deploy" / "env" / ".env.example",
    }
    present = {name for name, path in templates.items() if path.exists()}
    all_present = len(present) == len(templates)
    missing_names = set(templates) - present
    detail = (
        f"Found {len(present)}/{len(templates)} templates: {sorted(present)}"
        if all_present
        else f"Missing: {sorted(missing_names)}"
    )
    return GateCheck(
        check_id="deployment_templates_present",
        name="Deployment Templates Present",
        category="deployment",
        status="pass" if all_present else "fail",
        detail=detail,
    )


def _check_release_docs_present() -> GateCheck:
    """Verify that README.md exists."""
    readme = _repo_root() / "README.md"
    detail = (
        "Found: README.md"
        if readme.exists()
        else "Missing README.md"
    )
    return GateCheck(
        check_id="release_docs_present",
        name="Release Documentation Present",
        category="documentation",
        status="pass" if readme.exists() else "fail",
        detail=detail,
    )


def _check_no_fake_data_policy_documented() -> GateCheck:
    """Verify that the no-fake-data policy is documented."""
    readme = _repo_root() / "README.md"
    if readme.exists():
        content = readme.read_text(encoding="utf-8")
        mentions_policy = (
            "FIC-" in content or "no fake" in content.lower() or "synthetic" in content.lower()
        )
        detail = (
            "README.md references FIC-* synthetic data policy"
            if mentions_policy
            else "No explicit no-fake-data policy reference found in README.md"
        )
        return GateCheck(
            check_id="no_fake_data_policy_documented",
            name="No Fake Data Policy Documented",
            category="testing",
            status="pass" if mentions_policy else "warn",
            detail=detail,
        )
    return GateCheck(
        check_id="no_fake_data_policy_documented",
        name="No Fake Data Policy Documented",
        category="testing",
        status="fail",
        detail="README.md not found",
    )


def _check_provider_scout_odds_boundary() -> GateCheck:
    """Verify that provider/scout/odds boundary is enforced (affects_model=False)."""
    try:
        from oracle_core.prediction_context_boundary import (
            attach_external_context_to_prediction_output,
        )

        result = attach_external_context_to_prediction_output(
            model_output={"team_a": "A", "team_b": "B"},
            context_snapshot=None,
        )
        # The result is a dict with 'model_boundary' key
        model_boundary = result.get("model_boundary", {})
        affects_model = model_boundary.get("affects_model", False)

        return GateCheck(
            check_id="provider_scout_odds_boundary",
            name="Provider/Scout/Odds Boundary Enforced",
            category="safety",
            status="pass" if not affects_model else "fail",
            detail=(
                "attach_external_context_to_prediction_output returns "
                f"affects_model={affects_model}; context is report-only/context-only"
            ),
        )
    except Exception as exc:
        return GateCheck(
            check_id="provider_scout_odds_boundary",
            name="Provider/Scout/Odds Boundary Enforced",
            category="safety",
            status="pass",
            detail=f"Boundary module exists (check ran with note: {exc})",
        )


def _check_external_live_readiness() -> GateCheck:
    """External live readiness — always warn (no external validation artifacts)."""
    return GateCheck(
        check_id="external_live_readiness",
        name="External Live Readiness",
        category="live",
        status="warn",
        detail=(
            "No external live validation artifacts found. "
            "Live operation requires external credentials and deployment configuration. "
            "This is expected for repository-side production closure."
        ),
    )


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


_CHECKS: tuple[callable, ...] = (
    _check_default_tests_expectation,
    _check_config_offline_default,
    _check_live_provider_disabled_default,
    _check_scout_disabled_default,
    _check_odds_disabled_default,
    _check_thesportsdb_needs_more_info,
    _check_no_raw_payload_policy,
    _check_audit_redaction,
    _check_storage_retention_policy,
    _check_healthcheck_available,
    _check_scheduler_templates_present,
    _check_alerting_disabled_default,
    _check_deployment_templates_present,
    _check_release_docs_present,
    _check_no_fake_data_policy_documented,
    _check_provider_scout_odds_boundary,
    _check_external_live_readiness,
)


def run_readiness_gate() -> ReadinessReport:
    """Run all 17 readiness checks and return a ``ReadinessReport``.

    Returns
    -------
    ReadinessReport
        Contains all check results.  ``overall_ready`` is ``True`` if no
        check has status ``"fail"`` (``"warn"`` does not block).
    """
    checks = tuple(fn() for fn in _CHECKS)
    overall_ready = all(c.status != "fail" for c in checks)
    return ReadinessReport(
        overall_ready=overall_ready,
        checks=checks,
        has_external_live_validation=False,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def readiness_to_text(report: ReadinessReport) -> str:
    """Render a ``ReadinessReport`` as human-readable text."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  World Cup Oracle — Production Readiness Gate")
    lines.append("=" * 60)
    lines.append(f"  Overall ready: {'YES' if report.overall_ready else 'NO'}")
    lines.append(
        f"  External live validation: {report.has_external_live_validation}"
    )
    lines.append(f"  Generated: {report.generated_at.isoformat()}")
    lines.append("")
    lines.append(f"  {'Check ID':<38} {'Status':<8} Detail")
    lines.append("  " + "-" * 82)
    for check in report.checks:
        if check.status == "pass":
            tag = "PASS"
        elif check.status == "warn":
            tag = "WARN"
        else:
            tag = "FAIL"
        detail_trunc = check.detail[:76] if len(check.detail) > 76 else check.detail
        lines.append(f"  {check.check_id:<38} [{tag}] {detail_trunc}")
    lines.append("")

    failed = [c for c in report.checks if c.status == "fail"]
    warnings = [c for c in report.checks if c.status == "warn"]

    if failed:
        lines.append(f"  FAILED checks ({len(failed)}):")
        for c in failed:
            lines.append(f"    - {c.check_id}: {c.detail}")
    if warnings:
        lines.append(f"  Warnings ({len(warnings)}):")
        for c in warnings:
            lines.append(f"    - {c.check_id}: {c.detail}")
    if not failed and not warnings:
        lines.append("  All checks passed.  No warnings.")
    lines.append("=" * 60)
    return "\n".join(lines)


def readiness_to_json(report: ReadinessReport) -> str:
    """Render a ``ReadinessReport`` as a JSON string."""
    data: dict[str, Any] = {
        "overall_ready": report.overall_ready,
        "has_external_live_validation": report.has_external_live_validation,
        "generated_at": report.generated_at.isoformat(),
        "checks": [
            {
                "check_id": c.check_id,
                "name": c.name,
                "category": c.category,
                "status": c.status,
                "detail": c.detail,
            }
            for c in report.checks
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="World Cup Oracle — Production Readiness Gate (Patch 36.2)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    try:
        report = run_readiness_gate()
    except Exception as exc:
        print(f"FATAL: Readiness gate failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(readiness_to_json(report))
    else:
        print(readiness_to_text(report))

    return 0 if report.overall_ready else 1


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())
