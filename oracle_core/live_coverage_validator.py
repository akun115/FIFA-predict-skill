"""Opt-in live coverage validator.

CLI-runnable module that validates provider coverage without making any
network calls by default.  Coverage checks always start from a dry-run
state where every category is reported as uncovered.

The ``--allow-live`` flag enables evaluation of live-capable providers,
but even then TheSportsDB is never marked as approved.

**Never approves TheSportsDB.**  ``approved_recommendation`` is always
``False`` in every coverage report.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from oracle_core.provider_plugging import (
    ProviderApprovalStatus,
    get_provider_spec,
)


# ---------------------------------------------------------------------------
# Standard coverage categories
# ---------------------------------------------------------------------------

COVERAGE_CATEGORIES: tuple[str, ...] = (
    "teams",
    "fixtures",
    "dates",
    "standings",
)


# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageCheck:
    """Result of a single coverage check for one category."""

    category: str
    """Category being checked, e.g. ``"teams"``, ``"fixtures"``."""

    covered: bool = False
    """``True`` if coverage was confirmed for this category."""

    detail: str = ""
    """Human-readable explanation of the coverage status."""


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Complete coverage validation report for a single provider."""

    provider_name: str
    """Name of the provider being validated."""

    competition: str = ""
    """Optional competition name context, e.g. ``"World Cup 2026"``."""

    checks: tuple[CoverageCheck, ...] = ()
    """Individual coverage check results per category."""

    gaps: tuple[str, ...] = ()
    """Gap codes identified during coverage validation."""

    caveats: tuple[str, ...] = ()
    """Caveats or warnings about coverage."""

    approved_recommendation: bool = False
    """**Always ``False``.**  No provider is automatically approved for live use."""

    generated_at: str = ""
    """ISO-8601 timestamp of when this report was generated."""

    allow_live_used: bool = False
    """``True`` if ``--allow-live`` was passed when generating this report."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize this report to a JSON-compatible dict."""
        return {
            "provider_name": self.provider_name,
            "competition": self.competition,
            "checks": [
                {
                    "category": c.category,
                    "covered": c.covered,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "approved_recommendation": self.approved_recommendation,
            "generated_at": self.generated_at,
            "allow_live_used": self.allow_live_used,
        }

    def to_text(self) -> str:
        """Render this report as human-readable text."""
        lines: list[str] = [
            f"Coverage Report for: {self.provider_name}",
            f"  Competition: {self.competition or '(not specified)'}",
            f"  Generated at: {self.generated_at}",
            f"  Allow-live used: {self.allow_live_used}",
            f"  Approved recommendation: {self.approved_recommendation}",
            "",
        ]

        if self.checks:
            lines.append("Coverage checks:")
            for check in self.checks:
                status = "COVERED" if check.covered else "NOT COVERED"
                lines.append(f"  [{status}] {check.category}")
                if check.detail:
                    lines.append(f"         {check.detail}")
            lines.append("")

        if self.gaps:
            lines.append("Gaps:")
            for gap in self.gaps:
                lines.append(f"  - {gap}")
            lines.append("")

        if self.caveats:
            lines.append("Caveats:")
            for caveat in self.caveats:
                lines.append(f"  - {caveat}")
            lines.append("")

        return "\n".join(lines)

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")


# ---------------------------------------------------------------------------
# Dry-run coverage
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def run_coverage_dry_run(
    provider_name: str,
    competition: str = "",
) -> CoverageReport:
    """Run a dry-run coverage validation for the given provider.

    Every coverage category is reported as ``covered=False`` with caveats
    explaining that the provider is disabled or needs more information.

    No network calls are made.  ``approved_recommendation`` is always
    ``False``.
    """
    caveats: list[str] = ["dry-run mode — no live data fetched"]

    try:
        spec = get_provider_spec(provider_name)
        if spec.approval_status is ProviderApprovalStatus.DISABLED:
            caveats.append(f"provider is disabled: {spec.provider_name}")
        elif spec.approval_status is ProviderApprovalStatus.NEEDS_MORE_INFO:
            caveats.append(
                f"provider needs more info before live use: {spec.provider_name}"
            )
        else:
            caveats.append(
                f"dry-run — would attempt live fetch for {spec.provider_name}"
            )
    except ValueError:
        caveats.append(f"unknown provider: {provider_name}")

    checks = tuple(
        CoverageCheck(
            category=cat,
            covered=False,
            detail="dry-run — no live data fetched",
        )
        for cat in COVERAGE_CATEGORIES
    )

    return CoverageReport(
        provider_name=provider_name,
        competition=competition,
        checks=checks,
        gaps=("dry_run_no_data",),
        caveats=tuple(caveats),
        approved_recommendation=False,
        generated_at=_now_iso(),
        allow_live_used=False,
    )


# ---------------------------------------------------------------------------
# Live-aware coverage check
# ---------------------------------------------------------------------------


def run_coverage_check(
    provider_name: str,
    *,
    competition: str = "",
    allow_live: bool = False,
) -> CoverageReport:
    """Run a coverage validation, optionally allowing live evaluation.

    When ``allow_live`` is ``False`` (the default), this is equivalent to
    ``run_coverage_dry_run``.

    When ``allow_live`` is ``True``, the provider's spec is inspected:
      * If the provider is TheSportsDB (or any provider with
        ``NEEDS_MORE_INFO`` status), a caveat is recorded explaining that
        the provider still needs more information and is not approved.
      * No provider is ever given an ``approved_recommendation`` of
        ``True``.
    """
    if not allow_live:
        return run_coverage_dry_run(provider_name, competition=competition)

    # allow_live=True path — inspect the spec but never approve.
    caveats: list[str] = []
    gaps: list[str] = []

    try:
        spec = get_provider_spec(provider_name)
    except ValueError:
        return CoverageReport(
            provider_name=provider_name,
            competition=competition,
            checks=tuple(
                CoverageCheck(category=cat, covered=False, detail="unknown provider")
                for cat in COVERAGE_CATEGORIES
            ),
            gaps=("unknown_provider",),
            caveats=(f"no built-in spec found for provider: {provider_name}",),
            approved_recommendation=False,
            generated_at=_now_iso(),
            allow_live_used=True,
        )

    if spec.approval_status is ProviderApprovalStatus.NEEDS_MORE_INFO:
        caveats.append(
            f"provider {spec.provider_name} is in needs_more_info status — "
            f"not approved for live use"
        )
        gaps.append("provider_not_approved")
    elif spec.approval_status is ProviderApprovalStatus.DISABLED:
        caveats.append(
            f"provider {spec.provider_name} is disabled — not available for live use"
        )
        gaps.append("provider_disabled")

    if spec.approval_status in (
        ProviderApprovalStatus.NEEDS_MORE_INFO,
        ProviderApprovalStatus.DISABLED,
    ):
        checks = tuple(
            CoverageCheck(
                category=cat,
                covered=False,
                detail=f"provider status: {spec.approval_status.value}",
            )
            for cat in COVERAGE_CATEGORIES
        )
    else:
        # Provider is at least sandbox_only — would attempt live fetch
        # but still not approved.  This path is theoretical given the
        # current built-in specs.
        caveats.append(
            f"provider {spec.provider_name} has status "
            f"{spec.approval_status.value} — dry-run only, no live fetch attempted"
        )
        checks = tuple(
            CoverageCheck(
                category=cat,
                covered=False,
                detail="dry-run — would attempt live fetch but not approved",
            )
            for cat in COVERAGE_CATEGORIES
        )
        gaps.append("dry_run_no_data")

    return CoverageReport(
        provider_name=provider_name,
        competition=competition,
        checks=checks,
        gaps=tuple(gaps),
        caveats=tuple(caveats),
        approved_recommendation=False,
        generated_at=_now_iso(),
        allow_live_used=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m oracle_core.live_coverage_validator",
        description="Opt-in live coverage validator for provider plugins.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        help="Provider name to validate, e.g. 'thesportsdb'.",
    )
    parser.add_argument(
        "--competition",
        default="",
        help="Optional competition name, e.g. 'World Cup 2026'.",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        default=False,
        help="Enable live-capable provider evaluation (default: dry-run).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for live coverage validation."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    report = run_coverage_check(
        args.provider,
        competition=args.competition,
        allow_live=args.allow_live,
    )

    print(report.to_text())


if __name__ == "__main__":
    main()
