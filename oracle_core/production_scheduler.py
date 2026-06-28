"""Scheduler runtime and schedule templates — Patch 38.

Runnable: ``python -m oracle_core.production_scheduler --list``

All schedules are disabled by default and run in dry-run mode.
No network calls, no env reads.  Templates only, not installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleSpec:
    """Definition of a single scheduled task.

    Every schedule is **disabled** and **dry-run** by default.
    Explicit opt-in is required to enable or remove the dry-run guard.
    """

    name: str
    """Unique schedule name (e.g. ``"healthcheck"``)."""

    command: str
    """Command label, one of ``healthcheck``, ``coverage_dry_run``,
    ``report_dry_run``, ``snapshot_cleanup``."""

    interval: str
    """Cron expression or shorthand (``@daily``, ``@hourly``, ``@weekly``,
    or a standard 5-field cron string)."""

    enabled: bool = False
    """``True`` only after explicit opt-in."""

    dry_run: bool = True
    """When ``True``, the schedule prints what it *would* do without
    actually executing."""


@dataclass(frozen=True)
class ScheduleResult:
    """Outcome of executing one schedule entry."""

    spec_name: str
    executed: bool
    output: str
    gaps: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    network_called: bool = False
    dry_run: bool = True

    def __post_init__(self) -> None:
        if self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")


# ------------------------------------------------------------------
# Predefined schedule catalogue
# ------------------------------------------------------------------


def list_schedules() -> tuple[ScheduleSpec, ...]:
    """Return the predefined schedule catalogue.

    All entries are **disabled** and **dry-run** by default.
    """
    return (
        ScheduleSpec(
            name="healthcheck",
            command="healthcheck",
            interval="@daily",
        ),
        ScheduleSpec(
            name="coverage_dry_run",
            command="coverage_dry_run",
            interval="@weekly",
        ),
        ScheduleSpec(
            name="report_dry_run",
            command="report_dry_run",
            interval="@daily",
        ),
        ScheduleSpec(
            name="snapshot_cleanup",
            command="snapshot_cleanup",
            interval="@weekly",
        ),
    )


# ------------------------------------------------------------------
# Execution
# ------------------------------------------------------------------


def execute_schedule(
    spec_name: str,
    *,
    allow_live: bool = False,
) -> ScheduleResult:
    """Execute one schedule entry by name.

    Parameters
    ----------
    spec_name:
        Must match the ``name`` field of a predefined ``ScheduleSpec``.
    allow_live:
        When ``False`` (the default), the method refuses to call any
        network-dependent logic and warns that live execution is disabled.

    Returns
    -------
    ScheduleResult
        Always returned (no exception for missing names — reported in gaps).
    """
    schedules = list_schedules()
    spec = None
    for s in schedules:
        if s.name == spec_name:
            spec = s
            break

    executed_at = datetime.now(timezone.utc)

    if spec is None:
        return ScheduleResult(
            spec_name=spec_name,
            executed=False,
            output="",
            gaps=(f"schedule '{spec_name}' not found",),
            caveats=(),
            executed_at=executed_at,
            network_called=False,
            dry_run=True,
        )

    if spec.dry_run:
        print(
            f"[DRY-RUN] Would execute '{spec.name}' "
            f"(command={spec.command}, interval={spec.interval})"
        )
        return ScheduleResult(
            spec_name=spec.name,
            executed=False,
            output=f"[DRY-RUN] Would execute '{spec.name}'",
            caveats=("dry_run",),
            executed_at=executed_at,
            network_called=False,
            dry_run=True,
        )

    if not spec.enabled:
        return ScheduleResult(
            spec_name=spec.name,
            executed=False,
            output="",
            caveats=("schedule disabled",),
            executed_at=executed_at,
            network_called=False,
            dry_run=False,
        )

    if not allow_live:
        return ScheduleResult(
            spec_name=spec.name,
            executed=False,
            output="",
            caveats=("live execution not allowed",),
            executed_at=executed_at,
            network_called=False,
            dry_run=False,
        )

    # Live execution path — currently a stub that never calls network.
    output = (
        f"[STUB] Executed '{spec.name}' (command={spec.command}) "
        f"— no network called."
    )
    return ScheduleResult(
        spec_name=spec.name,
        executed=True,
        output=output,
        executed_at=executed_at,
        network_called=False,
        dry_run=False,
    )


# ------------------------------------------------------------------
# Export templates
# ------------------------------------------------------------------


def export_cron_tab() -> str:
    """Return example cron entries as a string.

    All entries are commented out — templates only, not installed.
    """
    return """# ── World Cup Oracle — cron templates ──
# All entries are DISABLED by default.  Remove the leading "# " and
# adjust paths before enabling.
#
# PATH must include the project virtual-env bin directory so that
# ``python`` resolves to the correct interpreter.

# PATH=/path/to/venv/bin:/usr/bin:/bin

# Healthcheck — every day at 06:00 UTC
# 0 6 * * * cd /path/to/world-cup-oracle && python -m oracle_core.production_health

# Coverage dry-run — every Monday at 07:00 UTC
# 0 7 * * 1 cd /path/to/world-cup-oracle && python -m oracle_core.production_scheduler --execute coverage_dry_run

# Report dry-run — every day at 07:30 UTC
# 30 7 * * * cd /path/to/world-cup-oracle && python -m oracle_core.production_scheduler --execute report_dry_run

# Snapshot cleanup — every Sunday at 05:00 UTC
# 0 5 * * 0 cd /path/to/world-cup-oracle && python -m oracle_core.production_scheduler --execute snapshot_cleanup
"""


def export_systemd_timers() -> tuple[str, ...]:
    """Return example systemd timer unit file contents.

    Returns a tuple of two strings: the ``.timer`` unit and the
    accompanying ``.service`` unit.  Templates only — not installed.
    """
    timer_unit = """# /etc/systemd/system/world-cup-oracle.timer  (template)
# DISABLED BY DEFAULT — remove the [Install] section comment and run
# ``systemctl enable --now world-cup-oracle.timer`` only after review.

[Unit]
Description=World Cup Oracle — daily healthcheck & reporting
After=network-online.target

[Timer]
# Runs daily at 06:00 UTC
OnCalendar=daily
Persistent=true

# [Install]
# WantedBy=timers.target
"""
    service_unit = """# /etc/systemd/system/world-cup-oracle.service  (template)
# DISABLED BY DEFAULT — review paths and environment before enabling.

[Unit]
Description=World Cup Oracle — schedule runner
After=network-online.target

[Service]
Type=oneshot
# User=oracle
# WorkingDirectory=/path/to/world-cup-oracle
# Environment=WORLD_CUP_ORACLE_RUNTIME_MODE=live_opt_in
# Environment=WORLD_CUP_ORACLE_NETWORK_ALLOWED=true
ExecStart=python -m oracle_core.production_scheduler --execute healthcheck

[Install]
# WantedBy=multi-user.target
"""
    return (timer_unit, service_unit)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="World Cup Oracle — Production Scheduler"
    )
    parser.add_argument("--list", action="store_true", help="List defined schedules")
    parser.add_argument(
        "--execute",
        type=str,
        default=None,
        metavar="NAME",
        help="Execute a schedule by name",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Permit live (network) execution (off by default)",
    )
    args = parser.parse_args()

    if args.list:
        schedules = list_schedules()
        if not schedules:
            print("No schedules defined.")
            sys.exit(0)
        print(f"{'Name':<25} {'Command':<25} {'Interval':<20} {'Enabled':<10} {'Dry-run':<10}")
        print("-" * 90)
        for spec in schedules:
            print(
                f"{spec.name:<25} {spec.command:<25} {spec.interval:<20} "
                f"{str(spec.enabled):<10} {str(spec.dry_run):<10}"
            )
        sys.exit(0)

    if args.execute:
        result = execute_schedule(args.execute, allow_live=args.allow_live)
        print(f"Schedule: {result.spec_name}")
        print(f"Executed: {result.executed}")
        print(f"Output:   {result.output}")
        if result.gaps:
            print(f"Gaps:     {'; '.join(result.gaps)}")
        if result.caveats:
            print(f"Caveats:  {'; '.join(result.caveats)}")
        sys.exit(0 if result.executed else 1)

    parser.print_help()
