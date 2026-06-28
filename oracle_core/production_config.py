"""Production configuration — typed, immutable, fail-closed by default.

Runtime modes:
  * offline      — No network, no env reads, no live tests.  DEFAULT.
  * synthetic    — Local synthetic fixtures only (no real data).
  * live_opt_in  — Opt-in for network and env access.  Must be explicit.

Architecture principle: when in doubt, deny access.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


_VALID_RUNTIME_MODES = ("offline", "synthetic", "live_opt_in")
_ENV_PREFIX = "WORLD_CUP_ORACLE_"


@dataclass(frozen=True)
class ProductionConfig:
    """Immutable production configuration.

    Every field has a safe default that minimises access to external resources.
    Use ``validate_config()`` to enforce mode-specific invariants.
    """

    runtime_mode: str = "offline"
    """One of ``offline``, ``synthetic``, ``live_opt_in``."""

    provider_mode: str = "disabled"
    allowed_provider_names: tuple[str, ...] = ("thesportsdb",)
    scout_mode: str = "disabled"
    odds_mode: str = "disabled"
    output_path: str = ""
    log_path: str = ""
    snapshot_store_path: str = ""
    network_allowed: bool = False
    env_access_allowed: bool = False
    live_tests_allowed: bool = False
    deployment_environment: str = "local-dev"
    monitoring_enabled: bool = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_mode": self.runtime_mode,
            "provider_mode": self.provider_mode,
            "allowed_provider_names": list(self.allowed_provider_names),
            "scout_mode": self.scout_mode,
            "odds_mode": self.odds_mode,
            "output_path": self.output_path,
            "log_path": self.log_path,
            "snapshot_store_path": self.snapshot_store_path,
            "network_allowed": self.network_allowed,
            "env_access_allowed": self.env_access_allowed,
            "live_tests_allowed": self.live_tests_allowed,
            "deployment_environment": self.deployment_environment,
            "monitoring_enabled": self.monitoring_enabled,
        }


#: Fully locked-down offline config.  Use this wherever no explicit override
#: has been provided.
DEFAULT_OFFLINE_CONFIG: ProductionConfig = ProductionConfig()


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def validate_config(config: ProductionConfig) -> None:
    """Validate a ``ProductionConfig`` for invalid combinations.

    Raises ``ValueError`` on the first violation found.

    Validated invariants
    --------------------
    * ``runtime_mode`` must be one of ``("offline", "synthetic", "live_opt_in")``.
    * ``offline`` mode forbids ``network_allowed``, ``env_access_allowed``,
      and ``live_tests_allowed``.
    * ``synthetic`` mode forbids ``live_tests_allowed`` and
      ``env_access_allowed``.
    """
    if config.runtime_mode not in _VALID_RUNTIME_MODES:
        raise ValueError(
            f"Invalid runtime_mode: {config.runtime_mode!r}. "
            f"Must be one of {_VALID_RUNTIME_MODES}"
        )

    if config.runtime_mode == "offline":
        if config.network_allowed:
            raise ValueError(
                "network_allowed must be False when runtime_mode is 'offline'"
            )
        if config.env_access_allowed:
            raise ValueError(
                "env_access_allowed must be False when runtime_mode is 'offline'"
            )
        if config.live_tests_allowed:
            raise ValueError(
                "live_tests_allowed must be False when runtime_mode is 'offline'"
            )

    if config.runtime_mode == "synthetic":
        if config.live_tests_allowed:
            raise ValueError(
                "live_tests_allowed must be False when runtime_mode is 'synthetic'"
            )
        if config.env_access_allowed:
            raise ValueError(
                "env_access_allowed must be False when runtime_mode is 'synthetic'"
            )


# ------------------------------------------------------------------
# Env-driven loading (fail-closed by default)
# ------------------------------------------------------------------


def load_config_from_env() -> ProductionConfig:
    """Read configuration from environment variables.

    Behaviour
    ---------
    * If ``WORLD_CUP_ORACLE_RUNTIME_MODE`` is **not** set to
      ``"live_opt_in"``, returns ``DEFAULT_OFFLINE_CONFIG`` immediately
      (no env vars are read beyond the mode key itself).
    * If ``WORLD_CUP_ORACLE_RUNTIME_MODE`` is ``"live_opt_in"``, the
      remaining environment variables are read and a full
      ``ProductionConfig`` is constructed.

    Env-var mapping (prefix ``WORLD_CUP_ORACLE_``)
    ----------------------------------------------
    * ``RUNTIME_MODE``           → ``runtime_mode``
    * ``PROVIDER_MODE``         → ``provider_mode``
    * ``ALLOWED_PROVIDER_NAMES`` → ``allowed_provider_names`` (comma-separated)
    * ``SCOUT_MODE``            → ``scout_mode``
    * ``ODDS_MODE``            → ``odds_mode``
    * ``OUTPUT_PATH``          → ``output_path``
    * ``LOG_PATH``             → ``log_path``
    * ``SNAPSHOT_STORE_PATH``  → ``snapshot_store_path``
    * ``NETWORK_ALLOWED``      → ``network_allowed`` (``"true"`` / ``"false"``)
    * ``ENV_ACCESS_ALLOWED``   → ``env_access_allowed`` (always ``True`` in
      live_opt_in mode)
    * ``LIVE_TESTS_ALLOWED``   → ``live_tests_allowed``
    * ``DEPLOYMENT_ENVIRONMENT`` → ``deployment_environment``
    * ``MONITORING_ENABLED``   → ``monitoring_enabled``
    """
    mode = os.environ.get(f"{_ENV_PREFIX}RUNTIME_MODE", "offline")
    if mode != "live_opt_in":
        return DEFAULT_OFFLINE_CONFIG

    config = ProductionConfig(
        runtime_mode="live_opt_in",
        provider_mode=os.environ.get(f"{_ENV_PREFIX}PROVIDER_MODE", "enabled"),
        allowed_provider_names=tuple(
            name.strip()
            for name in os.environ.get(
                f"{_ENV_PREFIX}ALLOWED_PROVIDER_NAMES", "thesportsdb"
            ).split(",")
            if name.strip()
        ),
        scout_mode=os.environ.get(f"{_ENV_PREFIX}SCOUT_MODE", "enabled"),
        odds_mode=os.environ.get(f"{_ENV_PREFIX}ODDS_MODE", "enabled"),
        output_path=os.environ.get(f"{_ENV_PREFIX}OUTPUT_PATH", ""),
        log_path=os.environ.get(f"{_ENV_PREFIX}LOG_PATH", ""),
        snapshot_store_path=os.environ.get(f"{_ENV_PREFIX}SNAPSHOT_STORE_PATH", ""),
        network_allowed=os.environ.get(f"{_ENV_PREFIX}NETWORK_ALLOWED", "true").lower()
        == "true",
        env_access_allowed=True,
        live_tests_allowed=os.environ.get(f"{_ENV_PREFIX}LIVE_TESTS_ALLOWED", "false").lower()
        == "true",
        deployment_environment=os.environ.get(
            f"{_ENV_PREFIX}DEPLOYMENT_ENVIRONMENT", "production"
        ),
        monitoring_enabled=os.environ.get(f"{_ENV_PREFIX}MONITORING_ENABLED", "true").lower()
        == "true",
    )

    validate_config(config)
    return config
