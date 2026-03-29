# Storage Manager — Low-Level Design

## Component Name: Storage Manager

The Storage Manager handles all disk and filesystem operations: base image management, qcow2 overlay creation/deletion, cloud-init ISO generation, and shared folder directory provisioning. It manages the `/var/lib/agentvm/` directory tree.

**Source files:** `src/agentvm/storage/pool.py`, `src/agentvm/storage/images.py`, `src/agentvm/storage/disks.py`, `src/agentvm/storage/cloud_init.py`, `src/agentvm/storage/shared.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| ST-FR-01 | Manage base image storage under `/var/lib/agentvm/base/` — upload, list, delete, query by capability | 5.4, 5.4.2 |
| ST-FR-02 | Parse and validate image metadata JSON (name, version, arch, os, sha256, capabilities, needs_kvm, min resources) | 5.4.2 |
| ST-FR-03 | Create qcow2 COW overlay from a read-only base image backing file | 5.4.1 |
| ST-FR-04 | Delete qcow2 overlay and VM directory on destroy | 5.4.1 |
| ST-FR-05 | Generate cloud-init ISO containing SSH key injection, hostname, network config, proxy BASE_URL/dummy key, and shared folder mount config | 5.4.1, 5.5.3 |
| ST-FR-06 | Create per-session shared folder directory structure under `/var/lib/agentvm/shared/<session-id>/` | 5.4, 4.2 |
| ST-FR-07 | Remove shared folder directory on session destroy | 5.4.1 |
| ST-FR-08 | Generate proxy config directory under `/var/lib/agentvm/proxy/<session-id>/` | 5.4 |
| ST-FR-09 | Remove proxy config directory on session destroy | 5.4.1 |
| ST-FR-10 | Create and manage VM directory under `/var/lib/agentvm/vms/vm-<uuid>/` | 5.4 |
| ST-FR-11 | Ensure storage directory tree exists on daemon startup (create missing dirs) | 5.4 |
| ST-FR-12 | Support image capability queries — find images by capability (e.g., `nested_virt`, `docker`, `ssh`) | 5.4.2, 11.3 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| ST-NFR-01 | qcow2 overlay creation must complete within 2 seconds (COW is nearly instant) | 5.4.1 |
| ST-NFR-02 | Cloud-init ISO generation must complete within 1 second | Phase 1 |
| ST-NFR-03 | Base image SHA256 verification must complete within 30 seconds for a 5GB image | Reliability |
| ST-NFR-04 | All directory operations must be idempotent — safe to re-run | Reliability |
| ST-NFR-05 | Unit test coverage ≥80% for disk and cloud-init modules | 12.1 |
| ST-NFR-06 | Shared folder directory permissions must prevent cross-session access (mode 0700) | 4.2 |

---

## 3. Component API Contracts

### 3.1 Inputs (Methods Exposed)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ImageMetadata:
    name: str                          # e.g., "ubuntu-24.04-amd64"
    version: str                       # e.g., "20260328"
    arch: str                          # "x86_64"
    os: str                            # "ubuntu"
    os_version: str                    # "24.04"
    sha256: str
    created_at: str
    capabilities: list[str]            # ["docker", "ssh", "nested_virt"]
    needs_kvm: bool
    needs_gpu: bool
    min_cpu: int
    min_memory_mb: int
    min_disk_gb: int

@dataclass
class CloudInitConfig:
    ssh_public_key: str
    hostname: str
    proxy_base_url: str                # e.g., "http://10.0.0.1:23760/v1"
    proxy_dummy_key: str               # e.g., "sk-proxy-<session-id>"
    shared_folder_mount: str           # e.g., "/mnt/shared"
    network_gateway: str               # e.g., "10.0.0.1"
    dns_servers: list[str]             # e.g., ["8.8.8.8"]

class StorageManager:
    # Base image management
    def list_images(self) -> list[ImageMetadata]:
        """List all available base images with metadata."""

    def get_image(self, name: str) -> ImageMetadata:
        """Get metadata for a specific base image."""

    def get_images_by_capability(self, capability: str) -> list[ImageMetadata]:
        """Find images that have a specific capability."""

    def upload_image(self, name: str, disk_path: str, metadata: ImageMetadata) -> None:
        """Import a base image. Verifies SHA256, sets read-only permissions."""

    def delete_image(self, name: str) -> None:
        """Remove a base image. Fails if any VM references it."""

    def verify_image(self, name: str) -> bool:
        """Verify base image SHA256 matches metadata."""

    # Disk management
    def create_disk_overlay(self, base_image: str, vm_id: str, size_gb: int) -> str:
        """Create qcow2 COW overlay. Returns path to overlay."""

    def delete_disk_overlay(self, vm_id: str) -> None:
        """Delete qcow2 overlay and VM directory."""

    # Cloud-init
    def generate_cloud_init_iso(self, vm_id: str, config: CloudInitConfig) -> str:
        """Generate cloud-init ISO. Returns path to ISO."""

    def delete_cloud_init_iso(self, vm_id: str) -> None:
        """Delete cloud-init ISO."""

    # Shared folder
    def create_shared_folder(self, session_id: str, project_path: Optional[str] = None,
                             output_path: Optional[str] = None) -> str:
        """Create shared folder directory structure. Returns host path."""

    def delete_shared_folder(self, session_id: str) -> None:
        """Remove shared folder directory."""

    # Proxy config
    def create_proxy_config_dir(self, session_id: str) -> str:
        """Create proxy config directory. Returns path."""

    def delete_proxy_config_dir(self, session_id: str) -> None:
        """Remove proxy config directory."""

    # Pool management
    def ensure_storage_tree(self) -> None:
        """Create all required directories if they don't exist."""

    def get_available_disk_gb(self) -> int:
        """Return available disk space in GB for VM storage."""
```

### 3.2 Outputs (Return Types and Events)

**Events emitted (to Audit Logger):**
- `vm.disk_create` — qcow2 overlay created
- `vm.disk_delete` — qcow2 overlay deleted
- `shared_folder.mount` — shared folder directory created
- `shared_folder.unmount` — shared folder directory removed

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Config** | Storage paths (`storage.base_dir`, `storage.base_images_dir`, etc.), default image |
| **Metadata Store** | Image metadata if stored in DB (or filesystem `metadata.json` files) |
| **Observability** | Audit event emission |

| Components That Call This | Purpose |
|---|---|
| **Session Manager** | Shared folder creation/deletion, cloud-init generation, proxy config dir |
| **VM Manager** | Disk overlay creation/deletion |
| **Auth Proxy Manager** | Proxy config directory path, writes proxy config YAML |
| **REST API** | Image management endpoints (`/images/*`), shared folder status (`/sessions/{sid}/shared`) |
| **CLI** | `agentvm images` commands, `agentvm shared info/sync` |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Can create disk overlays and generate cloud-init ISOs.

**User Stories & Tasks:**

* **Story:** As a developer, the storage directory tree exists and is properly initialized.
  * **Task:** Implement `StorageManager.ensure_storage_tree()` — create `/var/lib/agentvm/` and subdirectories (`base/`, `vms/`, `shared/`, `proxy/`, `keys/`, `logs/`) if they don't exist. Set permissions: `base/` owned by root with 0444 on image files, `shared/` and `vms/` owned by agentvm user with 0700.
    * *Identified Blockers/Dependencies:* Config must provide `storage.base_dir`.

* **Story:** As a developer, I can create a qcow2 COW overlay from a base image.
  * **Task:** Implement `disks.py` — `create_disk_overlay(base_image, vm_id, size_gb)`:
    1. Look up base image path from `base/<image>/disk.qcow2`.
    2. Create VM directory: `vms/vm-<uuid>/`.
    3. Run `qemu-img create -f qcow2 -F qcow2 -b <base_path> <overlay_path> <size>`.
    4. Return overlay path.
    * *Identified Blockers/Dependencies:* Config paths, base image must exist in `base/`.

* **Story:** As a developer, I can generate a cloud-init ISO for VM first-boot configuration.
  * **Task:** Implement `cloud_init.py` — `generate_cloud_init_iso(vm_id, config)`:
    1. Create `user-data` file with cloud-init config: SSH key injection via `ssh_authorized_keys`, hostname, shared folder mount script, proxy environment variables (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) written to `/etc/environment.d/agentvm-proxy.conf`.
    2. Create `meta-data` file with instance-id and local-hostname.
    3. Generate ISO: `genisoimage -output <iso_path> -volid cidata -joliet -rock <user-data> <meta-data>`.
    4. Return ISO path.
    * *Identified Blockers/Dependencies:* None (pure file generation).

* **Story:** As a developer, I can clean up VM storage on destroy.
  * **Task:** Implement `delete_disk_overlay(vm_id)` — `rm -rf vms/vm-<uuid>/`.
  * **Task:** Implement `delete_cloud_init_iso(vm_id)` — remove ISO from VM directory (covered by disk overlay delete if ISO is in the same dir).
    * *Identified Blockers/Dependencies:* Directory structure must exist.

* **Story:** As a developer, I have unit tests for disk and cloud-init operations.
  * **Task:** Implement `test_storage.py` — test overlay creation (mock `qemu-img` subprocess), cloud-init ISO content validation, directory creation/deletion.
  * **Task:** Implement `test_cloud_init.py` — test that generated `user-data` contains correct SSH key, proxy env vars, and shared folder config.
    * *Identified Blockers/Dependencies:* None.

---

### Phase 2: Session Model + Auth Proxy (Week 2-3)

**Phase Goal:** Shared folder and proxy config directory management.

**User Stories & Tasks:**

* **Story:** As a Session Manager, I can create and destroy per-session shared folders.
  * **Task:** Implement `create_shared_folder(session_id)` — create `/var/lib/agentvm/shared/<session-id>/` with subdirs `project/` and `output/`, set permissions 0700. If `project_path` is provided, symlink or copy files into `project/`. Create `.mount_metadata` file with mount options.
    * *Identified Blockers/Dependencies:* None.
  * **Task:** Implement `delete_shared_folder(session_id)` — `rm -rf /var/lib/agentvm/shared/<session-id>/`.
    * *Identified Blockers/Dependencies:* None.

* **Story:** As an Auth Proxy Manager, I have a config directory for each session.
  * **Task:** Implement `create_proxy_config_dir(session_id)` — create `/var/lib/agentvm/proxy/<session-id>/`.
  * **Task:** Implement `delete_proxy_config_dir(session_id)` — remove directory.
    * *Identified Blockers/Dependencies:* None.

---

### Phase 5: Resource Enforcement + Shared Folder (Week 5-6)

**Phase Goal:** Shared folder driver selection (virtiofs vs 9p) is implemented.

**User Stories & Tasks:**

* **Story:** As a platform operator, the correct shared folder driver is selected based on QEMU capabilities.
  * **Task:** Implement `StorageManager.get_shared_folder_driver()` — query QEMU version via subprocess `qemu-system-x86_64 --version` or parse libvirt capabilities XML. If QEMU ≥6.0 and virtiofsd is available, return `"virtiofs"`. Otherwise, return `"9p"`. This is the single source of truth for driver selection — VM Manager consumes this value for XML generation.
    * *Identified Blockers/Dependencies:* QEMU must be installed for version detection.

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** Image management API and base image lifecycle.

**User Stories & Tasks:**

* **Story:** As a platform operator, I can upload, list, and delete base images with metadata.
  * **Task:** Implement `upload_image(name, disk_path, metadata)` — copy disk to `base/<name>/disk.qcow2`, write `metadata.json`, set read-only permissions (0444, root:root), verify SHA256.
  * **Task:** Implement `delete_image(name)` — check no active VM references this image, remove `base/<name>/` directory.
  * **Task:** Implement `list_images()` and `get_image(name)` — read `metadata.json` from each `base/<name>/` directory.
  * **Task:** Implement `get_images_by_capability(capability)` — filter images where `capability` is in `metadata.capabilities` list.
    * *Identified Blockers/Dependencies:* None.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| Base image not found | Raise `ImageNotFoundError` with image name |
| SHA256 mismatch on upload | Reject upload, raise `ImageIntegrityError` |
| `qemu-img create` failure | Clean up partial overlay, raise `DiskError` |
| `genisoimage` not installed | Raise `DependencyError` with installation instructions |
| Shared folder directory already exists | Idempotent — verify structure matches expected, return existing path |
| Disk space exhausted | Pre-check via `os.statvfs()`, raise `CapacityError` before attempting creation |
| Image in use by active VM | Reject deletion, raise `ImageInUseError` |
