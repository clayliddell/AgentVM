"""Unit tests for AgentVM config loading.

Ref: CONFIG-LLD Section 5.2
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentvm.config import AgentVMConfig, ConfigError


def test_load_uses_defaults_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.delenv("AGENTVM_CONFIG", raising=False)

    config = AgentVMConfig.load(str(missing))

    assert config.network.bridge_name == "agentvm-br0"
    assert config.api.port == 9090
    assert config.resources.default_cpu_cores == 2


def test_load_reads_yaml_file_values(tmp_path: Path) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "host:",
                "  name: ci-host",
                "api:",
                "  host: 0.0.0.0",
                "  port: 9191",
                "network:",
                "  bridge_subnet: 10.44.0.0/24",
                "  bridge_gateway: 10.44.0.1",
                "  dhcp_range_start: 10.44.0.10",
                "  dhcp_range_end: 10.44.0.50",
            ]
        ),
        encoding="utf-8",
    )

    config = AgentVMConfig.load(str(config_path))

    assert config.host.name == "ci-host"
    assert config.api.host == "0.0.0.0"
    assert config.api.port == 9191


def test_load_applies_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text("api:\n  port: 9090\n", encoding="utf-8")
    monkeypatch.setenv("AGENTVM_API_PORT", "9443")
    monkeypatch.setenv("AGENTVM_SHARED_FOLDER_ENABLED", "false")

    config = AgentVMConfig.load(str(config_path))

    assert config.api.port == 9443
    assert config.shared_folder.enabled is False


def test_load_uses_agentvm_config_env_when_path_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text("api:\n  port: 9555\n", encoding="utf-8")
    monkeypatch.setenv("AGENTVM_CONFIG", str(config_path))

    config = AgentVMConfig.load()

    assert config.api.port == 9555


def test_load_raises_config_error_for_invalid_values(tmp_path: Path) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "api:",
                "  port: 70000",
                "network:",
                "  bridge_subnet: not-a-cidr",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        AgentVMConfig.load(str(config_path))


def test_repr_redacts_api_key_secret(tmp_path: Path) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "api:",
                "  api_keys:",
                "    - key: super-secret",
                "      name: test-key",
                "      permissions: [sessions:read]",
            ]
        ),
        encoding="utf-8",
    )

    config = AgentVMConfig.load(str(config_path))

    rendered = repr(config.api.api_keys[0])
    assert "super-secret" not in rendered
    assert "***REDACTED***" in rendered
