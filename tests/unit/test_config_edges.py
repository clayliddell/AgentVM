from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from agentvm.config import (
    APIConfig,
    APIKeyConfig,
    AgentVMConfig,
    ConfigError,
    _coerce_value,
    _field_default,
    _load_section,
    _load_yaml,
)


def test_config_path_helpers_return_expected_values(tmp_path: Path) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "storage:",
                f"  base_dir: {tmp_path / 'agentvm'}",
                "observability:",
                f"  audit_log_path: {tmp_path / 'logs' / 'audit.log'}",
            ]
        ),
        encoding="utf-8",
    )

    config = AgentVMConfig.load(str(config_path))
    assert config.database_path().endswith("/metadata.db")
    assert config.audit_log_full_path().endswith("/logs/audit.log")


def test_resource_and_network_validation_errors_raise_config_error(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "resources:",
                "  default_cpu_cores: 8",
                "  max_cpu_cores: 4",
                "  default_memory_mb: 8192",
                "  max_memory_mb: 1024",
                "  default_disk_gb: 200",
                "  max_disk_gb: 10",
                "network:",
                "  bridge_subnet: 10.0.0.0/24",
                "  bridge_gateway: not-an-ip",
                "  dhcp_range_start: 192.168.1.10",
                "  dhcp_range_end: 10.0.0.250",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc:
        AgentVMConfig.load(str(config_path))

    message = str(exc.value)
    assert "resources.default_cpu_cores" in message
    assert "resources.default_memory_mb" in message
    assert "resources.default_disk_gb" in message
    assert "network.bridge_gateway invalid IP" in message
    assert "network.dhcp_range_start" in message


def test_directory_creation_failures_are_reported(tmp_path: Path) -> None:
    blocking_path = tmp_path / "blocked"
    blocking_path.write_text("file", encoding="utf-8")
    config_path = tmp_path / "agentvm.yaml"
    config_path.write_text(
        "\n".join(
            [
                "storage:",
                f"  base_dir: {blocking_path}",
                f"  base_images_dir: {blocking_path / 'base'}",
                f"  vm_data_dir: {blocking_path / 'vms'}",
                f"  shared_dir: {blocking_path / 'shared'}",
                f"  proxy_dir: {blocking_path / 'proxy'}",
                "observability:",
                f"  console_log_dir: {blocking_path / 'logs'}",
                f"  audit_log_path: {blocking_path / 'logs' / 'audit.log'}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc:
        AgentVMConfig.load(str(config_path))
    assert "cannot create directory" in str(exc.value)


def test_load_yaml_handles_invalid_yaml_and_non_mapping_root(tmp_path: Path) -> None:
    invalid_yaml_path = tmp_path / "invalid.yaml"
    invalid_yaml_path.write_text("api: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        _load_yaml(invalid_yaml_path)

    list_root = tmp_path / "list-root.yaml"
    list_root.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        _load_yaml(list_root)


def test_load_yaml_returns_empty_dict_for_empty_file(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")
    assert _load_yaml(empty_file) == {}


def test_load_section_handles_none_and_rejects_invalid_mappings() -> None:
    loaded = _load_section(
        section_type=APIConfig, source={"api": None}, section_name="api"
    )
    assert loaded.port == 9090

    with pytest.raises(ConfigError):
        _load_section(section_type=APIConfig, source={"api": "bad"}, section_name="api")


def test_load_section_raises_when_field_coercion_fails() -> None:
    with pytest.raises(ConfigError):
        _load_section(
            section_type=APIConfig, source={"api": {"port": "abc"}}, section_name="api"
        )


def test_field_default_raises_for_missing_required_fields() -> None:
    @dataclass
    class RequiredField:
        value: int

    with pytest.raises(ConfigError):
        _field_default(fields(RequiredField)[0])


def test_coerce_value_covers_bool_list_and_api_key_errors() -> None:
    assert _coerce_value("true", bool) is True
    assert _coerce_value("[1,2,3]", list[int]) == [1, 2, 3]

    with pytest.raises(ValueError):
        _coerce_value("maybe", bool)

    with pytest.raises(TypeError):
        _coerce_value("{}", list[int])

    with pytest.raises(TypeError):
        _coerce_value("not-a-dict", APIKeyConfig)


def test_coerce_value_handles_api_key_validation_and_raw_fallback() -> None:
    with pytest.raises(TypeError):
        _coerce_value("not-a-dict", APIKeyConfig)

    with pytest.raises(ValueError):
        _coerce_value({"name": "only-name"}, APIKeyConfig)

    marker = object()
    assert _coerce_value(marker, object) is marker
