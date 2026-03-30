# Phase 1: Foundation

> **Note:** Task tracking has moved to VibeKanban. Do not edit task status in this file.
> Refer to the Kanban board for current status and blocking relationships.
> This file is the source of truth for requirements, FRs, and E2E tests only.
> See `dev/todo/todo.md` for details.

**Goal:** Bridge exists, VMs can be created/destroyed, metadata persists, host capacity works, storage initialized, config loads, daemon starts.

**Weeks:** 1–2

---

## Network Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| NetworkManager.ensure_bridge | Implement `BridgeManager.ensure_bridge()` — check if `agentvm-br0` exists via `ip link show`. If not, create bridge with IP `10.0.0.1/24`, bring up, add NAT masquerade rule. Ref: NETWORK-LLD §5.1 | High | Ready for Work |
| NetworkManager.allocate_vm_interface | Implement `BridgeManager.allocate_vm_interface()` — generate unique vnet name (`vnet<N>`) and random MAC address. Ref: NETWORK-LLD §5.1 | High | Ready for Work |

## VM Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| VMManager.libvirt_connection | Implement `libvirt_connection.py` — manage libvirt URI connection (`qemu:///system`) with retry and error handling. Ref: VM-LLD §5.1 | High | Ready for Work |
| VMManager.detect_nested_virt | Implement `detect_nested_virt_support()` — read nested virt from `/sys/module/kvm_intel/parameters/nested` or `/sys/module/kvm_amd/parameters/nested`. Ref: VM-LLD §5.1 | High | Ready for Work |
| VMManager.host_prereq_checks | Implement host prerequisite checks — verify `/dev/kvm` exists, libvirtd is running, nested virt module is loaded. Ref: VM-LLD §5.1 | High | Ready for Work |
| VMManager.xml_builder | Implement `xml_builder.py` — template engine that takes `VMSpec` and produces libvirt XML from HLD §9 template. Ref: VM-LLD §5.2 | High | Ready for Work |
| VMManager.disk_overlay_delegate | Delegate disk overlay creation to Storage Manager — VM Manager calls `StorageManager.create_disk_overlay()` during `create_vm()`. Ref: VM-LLD §5.3 | High | Ready for Work |
| VMManager.create_vm | Implement `VMManager.create_vm()` — validate spec, check capacity, create disk overlay, generate XML, call `conn.createXML()`, wait for boot, record metadata, return `VMConnectionInfo`. Ref: VM-LLD §5.4 | High | Ready for Work |
| VMManager.destroy_vm | Implement `VMManager.destroy_vm()` — `domain.destroy()`, `domain.undefine()`, delete disk overlay, purge metadata. Ref: VM-LLD §5.4 | High | Ready for Work |
| VMManager.get_vm_status | Implement `VMManager.get_vm_status()` — read domain state from libvirt, read cgroup usage, return `VMStatus`. Ref: VM-LLD §5.4 | Medium | Ready for Work |
| VMManager.test_vm_manager | Implement `test_vm_manager.py` and `test_xml_builder.py` with mocked libvirt. Ref: VM-LLD §5.5 | Medium | Ready for Work |

## Metadata Store

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| MetadataStore.init_schema | Implement `store.py` — `MetadataStore` class with `initialize()` that opens SQLite, enables WAL mode, creates all tables from HLD §5.6 DDL, creates all indexes. Ref: METADATA-LLD §5.1 | High | Ready for Work |
| MetadataStore.session_crud | Implement session CRUD: `create_session()`, `get_session()`, `update_session()`, `list_sessions()`, `delete_session()`. Ref: METADATA-LLD §5.2 | High | Ready for Work |
| MetadataStore.vm_crud | Implement VM CRUD: `create_vm()`, `get_vm()`, `get_vm_by_session()`, `update_vm()`, `delete_vm()`. Ref: METADATA-LLD §5.2 | High | Ready for Work |
| MetadataStore.test_metadata | Implement `test_metadata_store.py` — test all CRUD operations against in-memory SQLite. Ref: METADATA-LLD §5.3 | Medium | Ready for Work |

## Host Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| HostManager.cpu_map | Implement `cpu_map.py` — read `/sys/devices/system/cpu/cpu*/topology/` for core relationships, NUMA layout, nested virt detection. Ref: HOST-LLD §5.1 | Medium | Ready for Work |
| HostManager.capacity | Implement `capacity.py` — `get_capacity()` reads `/proc/cpuinfo`, `/proc/meminfo`, `os.statvfs()`. `check_spec()` compares requested against available. Track allocations in-memory. Ref: HOST-LLD §5.2 | High | Ready for Work |
| HostManager.reconcile_allocations | Implement `reconcile_allocations()` — called on daemon startup. Queries metadata store for all active VMs, rebuilds in-memory allocation state. Ref: HOST-LLD §5.2 | High | Ready for Work |

## Storage Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| StorageManager.ensure_storage_tree | Implement `StorageManager.ensure_storage_tree()` — create `/var/lib/agentvm/` and subdirectories (`base/`, `vms/`, `shared/`, `proxy/`, `keys/`, `logs/`). Ref: STORAGE-LLD §5.1 | High | Ready for Work |
| StorageManager.create_disk_overlay | Implement `disks.py` — `create_disk_overlay(base_image, vm_id, size_gb)`. Ref: STORAGE-LLD §5.2 | High | Ready for Work |
| StorageManager.cloud_init_iso | Implement `cloud_init.py` — `generate_cloud_init_iso(vm_id, config)`. Ref: STORAGE-LLD §5.3 | High | Ready for Work |
| StorageManager.delete_disk_overlay | Implement `delete_disk_overlay(vm_id)`. Ref: STORAGE-LLD §5.4 | Medium | Ready for Work |
| StorageManager.delete_cloud_init | Implement `delete_cloud_init_iso(vm_id)`. Ref: STORAGE-LLD §5.4 | Medium | Ready for Work |
| StorageManager.test_storage | Implement `test_storage.py` and `test_cloud_init.py`. Ref: STORAGE-LLD §5.5 | Medium | Ready for Work |

## Config

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Config.load_config | Implement `config.py` — `AgentVMConfig.load(config_path)`: determine config path, load YAML with `pyyaml`, apply env var overrides, construct dataclass, call `validate()`. Ref: CONFIG-LLD §5.1 | High | Ready for Work |
| Config.test_config | Implement config tests — test loading, validation, env var overrides. Ref: CONFIG-LLD §5.2 | Medium | Ready for Work |

## Daemon Entrypoint

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Daemon.startup_minimal | Implement `daemon.py` — config loading, metadata store init, storage tree ensure, bridge ensure, component wiring, uvicorn startup. Ref: DAEMON-LLD §5.1 | High | Ready for Work |
| Daemon.graceful_shutdown | Implement signal handlers, session drain loop, store close. Ref: DAEMON-LLD §5.2 | Medium | Ready for Work |

---

## Phase 1 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P1-FR-01 | The agentvm bridge (`agentvm-br0`) is created with IP `10.0.0.1/24` and NAT masquerade is functional | `ip addr show agentvm-br0` shows correct IP; `iptables -t nat -L` shows MASQUERADE rule |
| P1-FR-02 | A VM can be created from a base qcow2 image, booted, and destroyed through Python code | `VMManager.create_vm()` returns `VMConnectionInfo`; `VMManager.destroy_vm()` returns without error |
| P1-FR-03 | libvirt domain XML matches the HLD §9 template (CPU, memory, disk, network, cloud-init) | Generated XML passes `virt-xml-validate` and contains all required elements |
| P1-FR-04 | SQLite metadata store persists sessions and VMs with correct schema and WAL mode | `sqlite3` CLI can query tables; `PRAGMA journal_mode` returns `wal` |
| P1-FR-05 | Host capacity check correctly reports available CPU, memory, and disk | `HostManager.get_capacity()` returns accurate values matching `/proc/cpuinfo`, `/proc/meminfo`, `os.statvfs()` |
| P1-FR-06 | `reconcile_allocations()` restores in-memory capacity state from metadata after daemon restart | Kill daemon mid-operation, restart, verify capacity counts match active VMs |
| P1-FR-07 | Storage directory tree (`/var/lib/agentvm/`) is created with correct subdirectories and permissions | `ls -la /var/lib/agentvm/` shows `base/`, `vms/`, `shared/`, `proxy/`, `keys/`, `logs/` with 0755 |
| P1-FR-08 | Cloud-init ISO is generated with user-data, meta-data, and vendor-data | `isoinfo -l -i <iso>` shows expected files |
| P1-FR-09 | Config loads from YAML file with environment variable overrides | `AgentVMConfig.load()` returns correct values; env vars override YAML |
| P1-FR-10 | Daemon starts, serves API requests on configured listen address, and shuts down on SIGTERM | `curl http://localhost:<port>/health` returns 200; `kill -TERM <pid>` exits cleanly |

## Phase 1 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-1.1: VM lifecycle** — Create a VM from a base image, verify it boots (SSH or serial console output), destroy it, verify resources cleaned up (disk overlay deleted, libvirt domain undefined)
- [ ] **E2E-1.2: Bridge networking** — Create a VM, verify it obtains an IP on the `10.0.0.0/24` subnet, ping the VM from the host, destroy the VM
- [ ] **E2E-1.3: Metadata persistence** — Create a VM, stop the daemon, restart the daemon, verify metadata still queries correctly (session and VM records intact)
- [ ] **E2E-1.4: Capacity enforcement** — Attempt to create a VM exceeding available host resources, verify `CapacityError` is raised
- [ ] **E2E-1.5: Config loading** — Start daemon with `AGENTVM_CONFIG` pointing to a custom YAML file, verify it loads the correct config values
- [ ] **E2E-1.6: Daemon startup/shutdown** — Start daemon, verify `/health` returns 200, send SIGTERM, verify graceful shutdown (no orphan processes, no leaked resources)
