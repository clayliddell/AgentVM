# Phase 5: Resource Enforcement + Shared Folder

> **Note:** Task tracking has moved to VibeKanban. Do not edit task status in this file.
> Refer to the Kanban board for current status and blocking relationships.
> This file is the source of truth for requirements, FRs, and E2E tests only.
> See `dev/todo/todo.md` for details.

**Goal:** VM resource limits enforced via cgroups; shared folder driver selection implemented.

**Weeks:** 5–6

---

## VM Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| VMManager.cgroup_placement | After VM creation, call Host Manager's `cgroups.py` to place QEMU PID into `/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/` with CPU, memory, I/O, and PID limits. Ref: VM-LLD §8.1 | High | Blocked |
| VMManager.cpu_pinning | Implement CPU pinning — read topology from Host Manager `cpu_map.py`, allocate cores excluding reserved cores, generate `<cputune>` XML, apply cpuset via cgroup. Ref: VM-LLD §8.1 | High | Blocked |
| VMManager.shared_folder_driver | VM Manager consumes driver type from `StorageManager.get_shared_folder_driver()` and applies it to VM XML generation. Ref: VM-LLD §8.2 | Medium | Blocked |

## Network Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| NetworkManager.test_resource_limits | Implement integration test `test_resource_limits.py` — run `iperf3` inside VM, verify throughput does not exceed configured `network_mbps`. Ref: NETWORK-LLD §8.1 | Medium | Blocked |

## Host Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| HostManager.cgroups_create_scope | Implement `cgroups.py` — `create_scope(vm_id, qemu_pid)`: create directory, write QEMU PID to `cgroup.procs`, return cgroup path. Ref: HOST-LLD §8.1 | High | Blocked |
| HostManager.cgroups_cpu_limits | Implement `set_cpu_limits()` — write to cpuset.cpus, cpuset.mems, cpu.max. Ref: HOST-LLD §8.1 | High | Blocked |
| HostManager.cgroups_memory_limits | Implement `set_memory_limits()` — write to memory.max, memory.high. Ref: HOST-LLD §8.1 | High | Blocked |
| HostManager.cgroups_io_limits | Implement `set_io_limits()` — write to io.max. Ref: HOST-LLD §8.1 | Medium | Blocked |
| HostManager.cgroups_pid_limit | Implement `set_pid_limit()` — write to pids.max. Ref: HOST-LLD §8.1 | Medium | Blocked |
| HostManager.cgroups_read_usage | Implement `read_usage()` — read cpu.stat, memory.current, io.stat. Ref: HOST-LLD §8.1 | Medium | Blocked |
| HostManager.cgroups_destroy_scope | Implement `destroy_scope()` — write "1" to cgroup.kill, rmdir scope directory. Ref: HOST-LLD §8.1 | High | Blocked |
| HostManager.cpu_core_allocation | Implement `CPUMapManager.allocate_cores(count, reserved, already_allocated)`: get topology, filter out reserved cores + HT siblings, prefer same NUMA node, return cpuset string and NUMA node. Ref: HOST-LLD §8.2 | High | Blocked |
| HostManager.test_resource_limits | Implement `test_resource_limits.py` — create VM with limits, run `stress-ng`, verify cgroup stats show limits enforced. Ref: HOST-LLD §8.3 | Medium | Blocked |

## Storage Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| StorageManager.get_shared_folder_driver | Implement `StorageManager.get_shared_folder_driver()` — query QEMU version. If QEMU >=6.0 and virtiofsd available, return `"virtiofs"`. Otherwise return `"9p"`. Ref: STORAGE-LLD §8.1 | Medium | Blocked |

---

## Phase 5 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P5-FR-01 | Each VM's QEMU process is placed in a cgroup scope (`/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/`) with correct limits | `cat /sys/fs/cgroup/agentvm.slice/vm-<uuid>.scope/cgroup.procs` shows QEMU PID |
| P5-FR-02 | CPU limits enforced — VM cannot exceed allocated vCPUs | `cpu.max` file shows correct `quota period`; `stress-ng` inside VM pegs at limit |
| P5-FR-03 | Memory limits enforced — VM cannot exceed allocated memory | `memory.max` shows correct limit; OOM killer triggers inside cgroup if exceeded |
| P5-FR-04 | I/O limits enforced — VM disk I/O does not exceed configured limits | `io.max` shows correct limits; `fio` inside VM shows throttled throughput |
| P5-FR-05 | PID limits enforced — VM process count does not exceed configured limit | `pids.max` shows correct limit; fork bomb inside VM triggers PID limit |
| P5-FR-06 | CPU cores pinned to VMs without overlap — no two VMs share the same physical core | `cpuset.cpus` for each VM scope shows non-overlapping core sets |
| P5-FR-07 | CPU pinning respects NUMA topology — cores preferentially allocated from same NUMA node | `cpuset.mems` shows correct NUMA node; VM memory allocated from pinned NUMA node |
| P5-FR-08 | Shared folder driver selection correct — virtiofs if QEMU >=6.0 and virtiofsd available, 9p otherwise | VM XML contains `<driver type='virtiofs'/>` or `<driver type='9p'/>` matching QEMU capabilities |
| P5-FR-09 | Network bandwidth enforcement verified — VM cannot exceed configured `network_mbps` | `iperf3` test inside VM shows throughput <= configured limit |

## Phase 5 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-5.1: Cgroup placement** — Create VM, verify QEMU PID is in correct cgroup scope, verify CPU/memory/io/pid limits are set
- [ ] **E2E-5.2: CPU limit enforcement** — Create VM with 2 vCPUs, run `stress-ng --cpu 4` inside VM, verify CPU usage caps at 200% (2 cores)
- [ ] **E2E-5.3: Memory limit enforcement** — Create VM with 2048MB, attempt to allocate 4096MB inside VM, verify OOM killer triggers within cgroup
- [ ] **E2E-5.4: I/O limit enforcement** — Create VM with disk I/O limit, run `fio` with sequential write, verify throughput does not exceed limit
- [ ] **E2E-5.5: CPU pinning** — Create 2 VMs, verify their cpuset.cpus do not overlap, verify each VM's performance is consistent (no cross-VM CPU contention)
- [ ] **E2E-5.6: Shared folder virtiofs** — On host with QEMU >=6.0, create VM, verify shared folder mounts with virtiofs driver inside VM
- [ ] **E2E-5.7: Shared folder 9p fallback** — On host with QEMU <6.0 (or virtiofsd unavailable), create VM, verify shared folder mounts with 9p driver inside VM
- [ ] **E2E-5.8: Resource cleanup** — Destroy VM, verify cgroup scope directory is deleted, no orphaned cgroup entries
