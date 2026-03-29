# Config — Low-Level Design

## Component Name: Config

The Config module loads, validates, and provides access to the agentvm daemon configuration. It supports YAML config files, environment variable overrides, and default values. Every other component depends on Config for its operational parameters.

**Source file:** `src/agentvm/config.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| CF-FR-01 | Load configuration from a YAML file (default `/etc/agentvm/agentvm.yaml`) | 14 |
| CF-FR-02 | Support environment variable overrides for all config values (prefix `AGENTVM_`) | 14 |
| CF-FR-03 | Provide sensible defaults for all config values if not specified | 14 |
| CF-FR-04 | Validate config on load — reject invalid values (e.g., negative CPU, invalid port) | 14 |
| CF-FR-05 | Provide typed access to all config sections: host, storage, network, resources, auth_proxy, shared_folder, api, security, observability | 14 |
| CF-FR-06 | Support config file path override via CLI flag `--config` | 7 |
| CF-FR-07 | Redact sensitive values (API keys) in string representations | Security |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| CF-NFR-01 | Config loading must complete within 100ms | Performance |
| CF-NFR-02 | Config must be immutable after load — no runtime mutation | Safety |
| CF-NFR-03 | Unit test coverage ≥80% for loading, validation, and defaults | 12.1 |

---

## 3. Component API Contracts

### 3.1 Config Schema

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class HostConfig:
    name: str = "agentvm-host-01"
    max_vms: int = 20

@dataclass
class StorageConfig:
    base_dir: str = "/var/lib/agentvm"
    base_images_dir: str = "/var/lib/agentvm/base"
    vm_data_dir: str = "/var/lib/agentvm/vms"
    shared_dir: str = "/var/lib/agentvm/shared"
    proxy_dir: str = "/var/lib/agentvm/proxy"
    default_image: str = "ubuntu-24.04-amd64"

@dataclass
class NetworkConfig:
    bridge_name: str = "agentvm-br0"
    bridge_subnet: str = "10.0.0.0/24"
    bridge_gateway: str = "10.0.0.1"
    dhcp_range_start: str = "10.0.0.100"
    dhcp_range_end: str = "10.0.0.254"
    default_bandwidth_mbps: int = 100
    wan_interface: str = "eth0"
    default_policy: str = "strict"

@dataclass
class ResourceConfig:
    default_cpu_cores: int = 2
    default_memory_mb: int = 4096
    default_disk_gb: int = 20
    max_cpu_cores: int = 16
    max_memory_mb: int = 65536
    max_disk_gb: int = 200
    reserved_cores: list[int] = None  # defaults to [0, 1]
    reserved_memory_mb: int = 4096

@dataclass
class AuthProxyConfig:
    enabled: bool = True
    port_range_start: int = 23760
    binary_path: str = "/usr/local/bin/agentvm-auth-proxy"
    default_user: str = "agentvm-proxy"

@dataclass
class SharedFolderConfig:
    enabled: bool = True
    driver: str = "virtiofs"           # "virtiofs" | "9p"
    guest_mount_point: str = "/mnt/shared"
    max_size_gb: int = 10
    allow_symlinks: bool = False

@dataclass
class APIKeyConfig:
    key: str
    name: str
    permissions: list[str]

@dataclass
class APIConfig:
    host: str = "127.0.0.1"
    port: int = 9090
    api_keys: list[APIKeyConfig] = None

@dataclass
class SecurityConfig:
    selinux_enforcing: bool = True
    enable_audit_log: bool = True
    vm_max_lifetime_hours: int = 24
    ssh_key_required: bool = True

@dataclass
class ObservabilityConfig:
    metrics_enabled: bool = True
    metrics_port: int = 9091
    log_level: str = "INFO"
    console_log_dir: str = "/var/lib/agentvm/logs"
    audit_log_path: str = "/var/lib/agentvm/logs/audit.log"

@dataclass
class AgentVMConfig:
    host: HostConfig
    storage: StorageConfig
    network: NetworkConfig
    resources: ResourceConfig
    auth_proxy: AuthProxyConfig
    shared_folder: SharedFolderConfig
    api: APIConfig
    security: SecurityConfig
    observability: ObservabilityConfig

    @staticmethod
    def load(config_path: Optional[str] = None) -> "AgentVMConfig":
        """Load config from YAML file with env var overrides."""

    def validate(self) -> list[str]:
        """Validate all config values. Returns list of errors (empty if valid)."""

    def database_path(self) -> str:
        """Return full path to metadata database."""
        return f"{self.storage.base_dir}/metadata.db"

    def audit_log_full_path(self) -> str:
        """Return full path to audit log."""
        return self.observability.audit_log_path
```

### 3.2 Dependencies

| Component This Depends On | Purpose |
|---|---|
| None — Config is a leaf dependency | |

| Components That Call This | Purpose |
|---|---|
| **All components** | Access config values for their operational parameters |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Configuration can be loaded from a YAML file with defaults.

**User Stories & Tasks:**

* **Story:** As a developer, I can load configuration from a YAML file.
  * **Task:** Implement `config.py` — `AgentVMConfig.load(config_path)`:
    1. Determine config path: CLI flag > env var `AGENTVM_CONFIG` > default `/etc/agentvm/agentvm.yaml`.
    2. If file exists, load YAML with `pyyaml`. If not, use all defaults.
    3. Apply environment variable overrides: for each config key, check `AGENTVM_<SECTION>_<KEY>` (e.g., `AGENTVM_API_PORT`).
    4. Construct `AgentVMConfig` dataclass with all nested sections.
    5. Call `validate()` — check: ports in valid range, CPU/memory/disk within bounds, required paths exist or can be created, network subnet is valid CIDR.
    6. Return config or raise `ConfigError` with validation errors.
    * *Identified Blockers/Dependencies:* None.

* **Story:** As a developer, I have unit tests for config loading and validation.
  * **Task:** Implement config tests — test: loading from YAML, env var overrides, defaults when file missing, validation errors for invalid values, sensitive value redaction.
    * *Identified Blockers/Dependencies:* None.

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** Config integrates with daemon startup.

**User Stories & Tasks:**

* **Story:** As a daemon, I load config on startup and pass it to all components.
  * **Task:** Integrate config loading into `daemon.py` startup — load config first, pass `AgentVMConfig` instance to all component constructors.
    * *Identified Blockers/Dependencies:* All components must accept config in constructor.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| Config file not found | Use defaults, log warning |
| YAML parse error | Raise `ConfigError` with line number and error |
| Invalid config value | Raise `ConfigError` with field name and valid range |
| Missing required directory | Attempt to create, raise `ConfigError` if creation fails |
| Environment variable type mismatch | Raise `ConfigError` (e.g., `AGENTVM_API_PORT=abc`) |
