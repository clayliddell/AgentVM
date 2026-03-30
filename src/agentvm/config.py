"""Configuration loader and validation for AgentVM.

Ref: CONFIG-LLD Section 5
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import MISSING, Field, dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import yaml

DEFAULT_CONFIG_PATH = "/etc/agentvm/agentvm.yaml"


class ConfigError(ValueError):
    """Raised when AgentVM configuration cannot be loaded.

    Ref: CONFIG-LLD Section 5
    """


@dataclass(frozen=True)
class HostConfig:
    """Host-related configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    name: str = "agentvm-host-01"
    max_vms: int = 20


@dataclass(frozen=True)
class StorageConfig:
    """Storage-related configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    base_dir: str = "/var/lib/agentvm"
    base_images_dir: str = "/var/lib/agentvm/base"
    vm_data_dir: str = "/var/lib/agentvm/vms"
    shared_dir: str = "/var/lib/agentvm/shared"
    proxy_dir: str = "/var/lib/agentvm/proxy"
    default_image: str = "ubuntu-24.04-amd64"


@dataclass(frozen=True)
class NetworkConfig:
    """Network-related configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    bridge_name: str = "agentvm-br0"
    bridge_subnet: str = "10.0.0.0/24"
    bridge_gateway: str = "10.0.0.1"
    dhcp_range_start: str = "10.0.0.100"
    dhcp_range_end: str = "10.0.0.254"
    default_bandwidth_mbps: int = 100
    wan_interface: str = "eth0"
    default_policy: str = "strict"


@dataclass(frozen=True)
class ResourceConfig:
    """Resource default and limit configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    default_cpu_cores: int = 2
    default_memory_mb: int = 4096
    default_disk_gb: int = 20
    max_cpu_cores: int = 16
    max_memory_mb: int = 65536
    max_disk_gb: int = 200
    reserved_cores: list[int] = field(default_factory=lambda: [0, 1])
    reserved_memory_mb: int = 4096


@dataclass(frozen=True)
class AuthProxyConfig:
    """Auth proxy lifecycle configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    enabled: bool = True
    port_range_start: int = 23760
    binary_path: str = "/usr/local/bin/agentvm-auth-proxy"
    default_user: str = "agentvm-proxy"


@dataclass(frozen=True)
class SharedFolderConfig:
    """Shared-folder feature configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    enabled: bool = True
    driver: str = "virtiofs"
    guest_mount_point: str = "/mnt/shared"
    max_size_gb: int = 10
    allow_symlinks: bool = False


@dataclass(frozen=True)
class APIKeyConfig:
    """Single API key definition.

    Ref: CONFIG-LLD Section 3.1
    """

    key: str
    name: str
    permissions: list[str]

    def __repr__(self) -> str:
        """Return a redacted representation.

        Ref: CONFIG-LLD Section 3.1
        """

        return (
            "APIKeyConfig("  # pragma: no cover - deterministic string build
            "key='***REDACTED***', "
            f"name={self.name!r}, permissions={self.permissions!r})"
        )


@dataclass(frozen=True)
class APIConfig:
    """API listener and key configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    host: str = "127.0.0.1"
    port: int = 9090
    api_keys: list[APIKeyConfig] = field(default_factory=list)


@dataclass(frozen=True)
class SecurityConfig:
    """Security and policy configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    selinux_enforcing: bool = True
    enable_audit_log: bool = True
    vm_max_lifetime_hours: int = 24
    ssh_key_required: bool = True


@dataclass(frozen=True)
class ObservabilityConfig:
    """Logging and metrics configuration.

    Ref: CONFIG-LLD Section 3.1
    """

    metrics_enabled: bool = True
    metrics_port: int = 9091
    log_level: str = "INFO"
    console_log_dir: str = "/var/lib/agentvm/logs"
    audit_log_path: str = "/var/lib/agentvm/logs/audit.log"


@dataclass(frozen=True)
class AgentVMConfig:
    """Top-level typed configuration for all AgentVM components.

    Ref: CONFIG-LLD Section 3.1
    """

    host: HostConfig = field(default_factory=HostConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    auth_proxy: AuthProxyConfig = field(default_factory=AuthProxyConfig)
    shared_folder: SharedFolderConfig = field(default_factory=SharedFolderConfig)
    api: APIConfig = field(default_factory=APIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    @staticmethod
    def load(config_path: str | None = None) -> AgentVMConfig:
        """Load config from YAML and apply environment variable overrides.

        Args:
            config_path: Optional explicit path to the YAML config file.

        Returns:
            AgentVMConfig: Parsed and validated typed configuration.

        Raises:
            ConfigError: If the config content is invalid.

        Ref: CONFIG-LLD Section 5.1
        """

        selected_path = config_path or os.environ.get(
            "AGENTVM_CONFIG", DEFAULT_CONFIG_PATH
        )
        loaded_yaml = _load_yaml(Path(selected_path))

        config = AgentVMConfig(
            host=_load_section(HostConfig, loaded_yaml, "host"),
            storage=_load_section(StorageConfig, loaded_yaml, "storage"),
            network=_load_section(NetworkConfig, loaded_yaml, "network"),
            resources=_load_section(ResourceConfig, loaded_yaml, "resources"),
            auth_proxy=_load_section(AuthProxyConfig, loaded_yaml, "auth_proxy"),
            shared_folder=_load_section(
                SharedFolderConfig, loaded_yaml, "shared_folder"
            ),
            api=_load_section(APIConfig, loaded_yaml, "api"),
            security=_load_section(SecurityConfig, loaded_yaml, "security"),
            observability=_load_section(
                ObservabilityConfig, loaded_yaml, "observability"
            ),
        )

        errors = config.validate()
        if errors:
            raise ConfigError("; ".join(errors))

        return config

    def validate(self) -> list[str]:
        """Validate all config values and prepare filesystem paths.

        Returns:
            list[str]: Validation errors. Empty list means config is valid.

        Ref: CONFIG-LLD Section 5
        """

        errors: list[str] = []
        self._validate_ports(errors)
        self._validate_resources(errors)
        self._validate_network(errors)
        self._ensure_directories(errors)
        return errors

    def database_path(self) -> str:
        """Return full path to metadata database.

        Returns:
            str: Absolute path to the metadata SQLite database file.

        Ref: CONFIG-LLD Section 3.1
        """

        return f"{self.storage.base_dir}/metadata.db"

    def audit_log_full_path(self) -> str:
        """Return full path to audit log.

        Returns:
            str: Absolute path to the audit log file.

        Ref: CONFIG-LLD Section 3.1
        """

        return self.observability.audit_log_path

    def _validate_ports(self, errors: list[str]) -> None:
        """Validate configured network ports.

        Ref: CONFIG-LLD Section 5
        """

        for name, value in (
            ("api.port", self.api.port),
            ("observability.metrics_port", self.observability.metrics_port),
            ("auth_proxy.port_range_start", self.auth_proxy.port_range_start),
        ):
            if not 1 <= value <= 65535:
                errors.append(f"{name} must be in range 1..65535")

    def _validate_resources(self, errors: list[str]) -> None:
        """Validate resource bounds and defaults.

        Ref: CONFIG-LLD Section 5
        """

        resources = self.resources
        if (
            resources.default_cpu_cores <= 0
            or resources.default_cpu_cores > resources.max_cpu_cores
        ):
            errors.append(
                "resources.default_cpu_cores must be >0 and <= resources.max_cpu_cores"
            )
        if (
            resources.default_memory_mb <= 0
            or resources.default_memory_mb > resources.max_memory_mb
        ):
            errors.append(
                "resources.default_memory_mb must be >0 and <= resources.max_memory_mb"
            )
        if (
            resources.default_disk_gb <= 0
            or resources.default_disk_gb > resources.max_disk_gb
        ):
            errors.append(
                "resources.default_disk_gb must be >0 and <= resources.max_disk_gb"
            )

    def _validate_network(self, errors: list[str]) -> None:
        """Validate network CIDR and related addresses.

        Ref: CONFIG-LLD Section 5
        """

        try:
            subnet = ipaddress.ip_network(self.network.bridge_subnet, strict=False)
        except ValueError as exc:
            errors.append(f"network.bridge_subnet invalid CIDR: {exc}")
            return

        for name, ip_value in (
            ("network.bridge_gateway", self.network.bridge_gateway),
            ("network.dhcp_range_start", self.network.dhcp_range_start),
            ("network.dhcp_range_end", self.network.dhcp_range_end),
        ):
            try:
                candidate = ipaddress.ip_address(ip_value)
            except ValueError as exc:
                errors.append(f"{name} invalid IP: {exc}")
                continue
            if candidate not in subnet:
                errors.append(
                    f"{name} ({ip_value}) must be inside {self.network.bridge_subnet}"
                )

    def _ensure_directories(self, errors: list[str]) -> None:
        """Ensure required directories exist.

        Ref: CONFIG-LLD Section 5
        """

        required_dirs = [
            self.storage.base_dir,
            self.storage.base_images_dir,
            self.storage.vm_data_dir,
            self.storage.shared_dir,
            self.storage.proxy_dir,
            self.observability.console_log_dir,
            str(Path(self.observability.audit_log_path).parent),
        ]
        for entry in required_dirs:
            try:
                Path(entry).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"cannot create directory {entry}: {exc}")


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file content if the file exists.

    Ref: CONFIG-LLD Section 5
    """

    if not path.exists():
        return {}

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"failed loading YAML at {path}: {exc}") from exc

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ConfigError("config root must be a mapping")
    return payload


def _load_section(
    section_type: type[Any], source: dict[str, Any], section_name: str
) -> Any:
    """Create one config section from YAML and env overrides.

    Ref: CONFIG-LLD Section 5.1
    """

    section_source = source.get(section_name, {})
    if section_source is None:
        section_source = {}
    if not isinstance(section_source, dict):
        raise ConfigError(f"config section '{section_name}' must be a mapping")

    values: dict[str, Any] = {}
    type_hints = get_type_hints(section_type)
    for section_field in fields(section_type):
        raw_value = section_source.get(
            section_field.name, _field_default(section_field)
        )
        env_key = f"AGENTVM_{section_name.upper()}_{section_field.name.upper()}"
        if env_key in os.environ:
            raw_value = os.environ[env_key]

        try:
            target_type = type_hints.get(section_field.name, section_field.type)
            values[section_field.name] = _coerce_value(raw_value, target_type)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"invalid value for {section_name}.{section_field.name}: {exc}"
            ) from exc

    return section_type(**values)


def _field_default(section_field: Field[Any]) -> Any:
    """Return declared default value for a dataclass field.

    Ref: CONFIG-LLD Section 5.1
    """

    if section_field.default is not MISSING:
        return section_field.default
    if section_field.default_factory is not MISSING:
        return section_field.default_factory()
    raise ConfigError(f"missing required field: {section_field.name}")


def _coerce_value(raw_value: Any, target_type: Any) -> Any:
    """Coerce values to configured target type.

    Ref: CONFIG-LLD Section 5
    """

    origin = get_origin(target_type)
    if target_type is bool:
        if isinstance(raw_value, bool):
            return raw_value
        normalized = str(raw_value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("expected boolean")

    if target_type is int:
        return int(raw_value)

    if target_type is str:
        return str(raw_value)

    if origin is list:
        item_type = get_args(target_type)[0]
        value_list = raw_value
        if isinstance(raw_value, str):
            parsed = yaml.safe_load(raw_value)
            value_list = [] if parsed is None else parsed
        if not isinstance(value_list, list):
            raise TypeError("expected a list")
        return [_coerce_value(item, item_type) for item in value_list]

    if target_type is APIKeyConfig:
        if not isinstance(raw_value, dict):
            raise TypeError("expected mapping for API key")
        if "key" not in raw_value or "name" not in raw_value:
            raise ValueError("api key entries require key and name")
        return APIKeyConfig(
            key=_coerce_value(raw_value["key"], str),
            name=_coerce_value(raw_value["name"], str),
            permissions=_coerce_value(raw_value.get("permissions", []), list[str]),
        )

    return raw_value
