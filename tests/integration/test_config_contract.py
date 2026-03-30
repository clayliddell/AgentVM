"""Integration contract tests for config shapes.

Ref: CONFIG-LLD Section 3.1
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentvm.config import APIKeyConfig, AgentVMConfig


@pytest.mark.integration
@pytest.mark.contract
def test_load_config_when_yaml_contains_supported_sections_returns_typed_contract(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "host:",
                "  max_vms: 5",
                "resources:",
                "  default_cpu_cores: 4",
                "api:",
                "  host: 0.0.0.0",
                "  api_keys:",
                "    - key: test-secret",
                "      name: ci",
                "      permissions: [read, write]",
            ]
        ),
        encoding="utf-8",
    )

    config = AgentVMConfig.load(str(config_path))

    assert isinstance(config.host.max_vms, int)
    assert isinstance(config.resources.default_cpu_cores, int)
    assert isinstance(config.api.host, str)
    assert isinstance(config.api.api_keys, list)
    assert config.api.api_keys
    assert isinstance(config.api.api_keys[0], APIKeyConfig)
    assert isinstance(config.api.api_keys[0].permissions, list)
