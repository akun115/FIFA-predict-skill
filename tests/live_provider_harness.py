"""Live provider test harness — Data Service v1 (Patch 23).

Offline-safe functions for opt-in live mode gating.  All functions accept
an explicit ``env: Mapping[str, str]`` — they do NOT read ``os.environ``
directly.  This keeps tests deterministic and offline by default.

Usage in a live test file::

    import os
    from tests.live_provider_harness import (
        require_live_provider_enabled,
        require_api_key,
        build_live_provider_config_from_env,
    )
    env = os.environ
    require_live_provider_enabled(env)
    key = require_api_key(env, "FOOTBALL_DATA_ORG_API_KEY")
    config = build_live_provider_config_from_env(env, "football-data.org")

No network.  No real API calls.  No skipped tests (fail-closed).
"""

from __future__ import annotations

from typing import Mapping

from oracle_core.data_service_providers import ProviderConfigurationError
from oracle_core.free_provider_adapters import FreeProviderConfig


# ── Environment variable names (Patch 23) ──

ENV_LIVE_TESTS = "WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS"
ENV_FOOTBALL_DATA_ORG_KEY = "FOOTBALL_DATA_ORG_API_KEY"
ENV_API_FOOTBALL_KEY = "API_FOOTBALL_API_KEY"
ENV_THESPORTSDB_PUBLIC_KEY = "THESPORTSDB_PUBLIC_API_KEY"


# ── Configuration defaults ──

_PROVIDER_CONFIG_DEFAULTS: Mapping[str, dict] = {
    "football-data.org": {
        "api_key_env_var": ENV_FOOTBALL_DATA_ORG_KEY,
        "base_url": "<needs_human_review>",
        "attribution": "<needs_human_review — football-data.org attribution>",
    },
    "api-football": {
        "api_key_env_var": ENV_API_FOOTBALL_KEY,
        "base_url": "<needs_human_review>",
        "attribution": "<needs_human_review — API-Football attribution>",
    },
    "thesportsdb": {
        "api_key_env_var": ENV_THESPORTSDB_PUBLIC_KEY,
        "base_url": "",
        "attribution": "<needs_human_review — TheSportsDB attribution>",
        "public_free_mode": True,
    },
}


# ── Public API ──


def should_run_live_provider_tests(env: Mapping[str, str]) -> bool:
    """Check if live provider tests are enabled.

    Returns ``True`` only if ``WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS``
    is set to ``"1"`` in *env*.
    """
    return env.get(ENV_LIVE_TESTS, "") == "1"


def require_live_provider_enabled(env: Mapping[str, str]) -> None:
    """Enforce that live provider tests are enabled.

    Raises ``ProviderConfigurationError`` if the env flag is not set.
    Does NOT skip — always fails closed.
    """
    if not should_run_live_provider_tests(env):
        raise ProviderConfigurationError(
            f"Live provider tests are disabled.  "
            f"Set {ENV_LIVE_TESTS}=1 to enable."
        )


def require_api_key(env: Mapping[str, str], key_name: str) -> str:
    """Fetch an API key from *env*, or raise.

    Raises ``ProviderConfigurationError`` if the key is missing or empty.
    Never logs or prints the key value.
    """
    value = env.get(key_name, "")
    if not value.strip():
        raise ProviderConfigurationError(
            f"API key '{key_name}' is not set or is empty.  "
            f"Provider is fail-closed."
        )
    return value


def build_live_provider_config_from_env(
    env: Mapping[str, str],
    provider_name: str,
) -> FreeProviderConfig:
    """Build a ``FreeProviderConfig`` for live mode from environment.

    Requires ``WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1`` and the
    provider-specific API key to be present in *env*.

    Returns a ``FreeProviderConfig`` with ``live_mode=True`` and
    ``enabled=True``.  The API key is validated but NOT stored in
    the config — callers must pass it separately to the adapter.
    """
    require_live_provider_enabled(env)

    defaults = _PROVIDER_CONFIG_DEFAULTS.get(provider_name)
    if defaults is None:
        raise ProviderConfigurationError(
            f"Unknown provider: {provider_name!r}.  "
            f"Known: {sorted(_PROVIDER_CONFIG_DEFAULTS.keys())}"
        )

    key_env_var = defaults["api_key_env_var"]
    is_public_free = defaults.get("public_free_mode", False)

    if is_public_free:
        # Public-free: key is optional (use documented public test key 123)
        public_key = env.get(key_env_var, "123")
    else:
        public_key = None
        require_api_key(env, key_env_var)

    return FreeProviderConfig(
        api_key_env_var=key_env_var,
        base_url=defaults["base_url"],
        enabled=True,
        live_mode=True,
        public_free_mode=is_public_free,
        public_api_key=public_key,
        attribution=defaults["attribution"],
    )
