# AgentVMs Platform — Complete Design Document

## 1. Vision (The 5-Year-Old Version)

Imagine you have a big house (the **host computer**). You want to let robot helpers (**AI agents**) come work in your house. But you don't trust the robots — they might break things or snoop around.

So you give each robot its own **locked room** (a **VM**). Inside the room, the robot can do whatever it wants — build things, run machines, even set up smaller rooms inside its room (**nested VMs**). But the robot can **never** open its door from the inside, break through the walls, or see what other robots are doing.

The house stays safe. The robots stay happy. Everyone wins.

---

## 2. Hypervisor Selection — Why KVM/QEMU

The **nested virtualization** requirement is the single biggest architectural constraint. It eliminates most microVM solutions.

| Hypervisor | Nested Virt | Security | Maturity | Density | Verdict |
|---|---|---|---|---|---|
| **KVM/QEMU + libvirt** | Full support | Strong (sVirt, cgroups) | 15+ years | Medium | **CHOSEN** |
| Firecracker | Not supported | Excellent (minimal VMM) | 7 years | Very high | Rejected — no nested virt |
| Cloud Hypervisor | Experimental/broken | Good | 5 years | High | Rejected — nested virt unreliable |
| Kata Containers | Yes (via KVM) | Good | 7 years | Medium | Adds unnecessary abstraction layer |
| CrosVM | Limited | Good | 6 years | High | ChromeOS-focused, poor tooling |

**Decision: KVM/QEMU managed through libvirt (Python bindings)**

Rationale:
- AWS, GCP, Azure all use KVM variants at scale
- `kvm_intel_nested=1` / `kvm_amd_nested=1` provides production-grade nested virt
- libvirt provides battle-tested VM lifecycle management, sVirt integration, cgroup enforcement
- The Python `libvirt` binding is mature and well-documented
- QEMU's full device model gives agents maximum compatibility (they can run any OS)

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      HOST MACHINE                            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  agentvm daemon                       │   │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │ REST API│  │VM Manager│  │ Scheduler│            │   │
│  │  │ (FastAPI│  │(libvirt) │  │(placement│            │   │
│  │  │  Uvicorn)│  │          │  │  & quotas)│           │   │
│  │  └────┬────┘  └────┬─────┘  └────┬─────┘            │   │
│  │       │            │              │                   │   │
│  │  ┌────┴────────────┴──────────────┴────────┐         │   │
│  │  │            Core Engine                   │         │   │
│  │  │  ┌──────────┐ ┌───────────┐ ┌─────────┐│         │   │
│  │  │  │ Network  │ │  Storage  │ │  State  ││         │   │
│  │  │  │ Manager  │ │  Manager  │ │  Store  ││         │   │
│  │  │  └──────────┘ └───────────┘ └─────────┘│         │   │
│  │  └─────────────────────────────────────────┘         │   │
│  │       │            │              │                   │   │
│  │  ┌────┴────┐  ┌────┴─────┐  ┌────┴─────┐            │   │
│  │  │Metrics  │  │  Host    │  │   Audit  │            │   │
│  │  │Collector│  │ Hardener │  │   Logger │            │   │
│  │  └─────────┘  └──────────┘  └──────────┘            │   │
│  └──────────────────────────────────────────────────────┘   │
│         │                    │                               │
│  ┌──────┴────────────────────┴──────────────────────────┐   │
│  │                    libvirtd                            │   │
│  │         (system daemon, socket-activated)              │   │
│  └───┬──────────┬──────────┬──────────┬─────────────────┘   │
│      │          │          │          │                      │
│  ┌───┴───┐ ┌───┴───┐ ┌───┴───┐ ┌───┴───┐                  │
│  │ QEMU  │ │ QEMU  │ │ QEMU  │ │ QEMU  │  ← one per VM   │
│  │ VM-01 │ │ VM-02 │ │ VM-03 │ │ VM-N  │                  │
│  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘                  │
│      │         │         │         │                        │
│  ┌───┴───┐ ┌───┴───┐ ┌───┴───┐ ┌───┴───┐                  │
│  │cgroup │ │cgroup │ │cgroup │ │cgroup │  ← resource       │
│  │slice  │ │slice  │ │slice  │ │slice  │    enforcement    │
│  └───────┘ └───────┘ └───────┘ └───────┘                  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Networking                                          │   │
│  │  ┌──────────┐    ┌──────────────────────────────┐    │   │
│  │  │  virbrN  │───→│  iptables NAT (masquerade)   │───→│──→ INTERNET
│  │  │ (bridge) │    │  per-VM isolation rules       │    │   │
│  │  └──────────┘    └──────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Storage                                             │   │
│  │  /var/lib/agentvm/                                   │   │
│  │  ├── base/          (read-only golden images)        │   │
│  │  ├── vms/<id>/      (per-VM qcow2 overlays)          │   │
│  │  ├── metadata.db    (SQLite state)                   │   │
│  │  └── logs/          (audit & VM logs)                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Security Model — Defense in Depth

The threat model assumes the agent is **actively adversarial**. Every layer must be independently sufficient to contain a breach.

```
  AGENT VM (adversarial)
  ┌─────────────────────────────────────────────────────────┐
  │  Layer 6: Guest Hardening                               │
  │  - Minimal base image (no extra packages)               │
  │  - Read-only root filesystem (optional)                 │
  │  - No shared folders with host                          │
  │  ┌───────────────────────────────────────────────────┐  │
  │  │  Layer 5: QEMU Device Model                       │  │
  │  │  - Minimal device set (virtio only)               │  │
  │  │  - No USB, no audio, no graphics if headless      │  │
  │  │  - Disabled: spice, tablet, ballooning            │  │
  │  │  ┌─────────────────────────────────────────────┐  │  │
  │  │  │  Layer 4: MAC (SELinux sVirt)                │  │  │
  │  │  │  - Each VM gets unique SELinux label          │  │  │
  │  │  │  - QEMU process confined to its own domain   │  │  │
  │  │  │  - Prevents cross-VM file access              │  │  │
  │  │  │  ┌─────────────────────────────────────────┐ │  │  │
  │  │  │  │  Layer 3: Resource Isolation             │ │  │  │
  │  │  │  │  - cgroups v2 (CPU, memory, I/O)         │ │  │  │
  │  │  │  │  - CPU pinning to dedicated cores        │ │  │  │
  │  │  │  │  - Memory hard limits (no swap sharing)  │ │  │  │
  │  │  │  │  ┌─────────────────────────────────────┐ │ │  │  │
  │  │  │  │  │  Layer 2: Network Isolation          │ │ │  │  │
  │  │  │  │  │  - Dedicated bridge per VM or VLAN   │ │ │  │  │
  │  │  │  │  │  - iptables: no VM→host traffic      │ │ │  │  │
  │  │  │  │  │  - iptables: no VM→VM traffic        │ │ │  │  │
  │  │  │  │  │  - NAT only for outbound internet    │ │ │  │  │
  │  │  │  │  │  - Rate limiting via tc              │ │ │  │  │
  │  │  │  │  │  ┌─────────────────────────────────┐ │ │ │  │  │
  │  │  │  │  │  │  Layer 1: Hardware Isolation     │ │ │ │  │  │
  │  │  │  │  │  │  - KVM (Intel VT-x / AMD-V)     │ │ │ │  │  │
  │  │  │  │  │  │  - EPT/NPT for memory isolation  │ │ │ │  │  │
  │  │  │  │  │  │  - Separate address spaces       │ │ │ │  │  │
  │  │  │  │  │  └─────────────────────────────────┘ │ │ │  │  │
  │  │  │  │  └─────────────────────────────────────┘ │ │  │  │
  │  │  │  └─────────────────────────────────────────┘ │  │  │
  │  │  └─────────────────────────────────────────────┘  │  │
  │  └───────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────┘
                        HOST KERNEL
```

### 4.1 Security Invariant

> **If any single layer fails, every remaining layer must independently prevent VM escape.**

| Layer | What It Protects | Mechanism | Failure Mode |
|---|---|---|---|
| L1 Hardware | CPU, memory separation | KVM VT-x/AMD-V + EPT | CPU microcode bug (rare, mitigated by patches) |
| L2 Network | Host and peer access | iptables + bridge isolation | Misconfigured rules (prevented by automation) |
| L3 Resources | Host resource starvation | cgroups v2 | Cgroup escape (kernel bug, very rare) |
| L4 MAC | Cross-VM file access | SELinux sVirt | SELinux disabled (enforced by policy) |
| L5 Device Model | Host device access | Minimal QEMU virtio devices | QEMU vulnerability (reduced by minimal devices) |
| L6 Guest | Lateral movement | Hardened base image | Agent installs malware (contained in VM) |

### 4.2 Host Hardening Checklist

```
Kernel Parameters (sysctl):
  kernel.kptr_restrict = 2          # hide kernel pointers
  kernel.dmesg_restrict = 1         # restrict dmesg access
  kernel.yama.ptrace_scope = 2      # restrict ptrace
  kernel.unprivileged_userns_clone = 0  # no user namespaces
  kernel.unprivileged_bpf_disabled = 1
  net.ipv4.conf.all.rp_filter = 1   # reverse path filtering
  net.ipv4.conf.all.accept_redirects = 0
  net.ipv6.conf.all.accept_redirects = 0

SELinux:
  enforcing = 1                     # mandatory
  sVirt enabled (automatic with libvirt)

Services:
  Disable: cups, avahi, bluetooth, nfs, rpcbind
  Enable:  libvirtd, firewalld, auditd

Firewall:
  Default deny inbound
  Allow: SSH (from admin network only), agentvm API (from admin network only)
  Block: All VM subnet → host subnet traffic

SSH:
  PermitRootLogin no
  PasswordAuthentication no
  AllowUsers agentvm-admin

Filesystem:
  /var/lib/agentvm on separate partition with noexec,nosuid,nodev
  VM images on dedicated LVM volume (optional)
```

---

## 5. Component Design

### 5.1 VM Manager (Core)

The VM Manager is the heart of the platform. It wraps libvirt operations with security-enforcing logic.

```
┌─────────────────────────────────────────────────────────┐
│                    VM Manager                            │
│                                                         │
│  create_vm(spec) ──→ validate_spec()                    │
│                    ──→ check_capacity()                  │
│                    ──→ allocate_resources()              │
│                    ──→ create_disk_overlay()             │
│                    ──→ generate_libvirt_xml()            │
│                    ──→ conn.createXML(xml)               │
│                    ──→ setup_cgroup_limits()             │
│                    ──→ setup_network_rules()             │
│                    ──→ wait_for_boot()                   │
│                    ──→ record_metadata()                 │
│                    ──→ return VMConnectionInfo           │
│                                                         │
│  destroy_vm(id) ──→ conn.lookupByUUID()                 │
│                   ──→ domain.destroy()  (hard kill)      │
│                   ──→ domain.undefine() (remove config)  │
│                   ──→ delete_disk_overlay()              │
│                   ──→ cleanup_network_rules()            │
│                   ──→ release_resources()                │
│                   ──→ purge_metadata()                   │
│                                                         │
│  get_vm_status(id) ──→ domain.state()                   │
│                    ──→ cgroup.read_usage()               │
│                    ──→ return VMStatus                   │
│                                                         │
│  list_vms() ──→ conn.listAllDomains()                   │
│             ──→ filter_by_owner()                       │
│             ──→ enrich_with_metrics()                   │
│             ──→ return List[VMStatus]                    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 VM Lifecycle State Machine

```
                    ┌──────────┐
                    │ REQUESTED│  API call received
                    └────┬─────┘
                         │ validate + allocate
                         ▼
                    ┌──────────┐
                    │CREATING  │  building disk, XML, network
                    └────┬─────┘
                         │ domain.createXML()
                         ▼
          ┌──────────────────────────────┐
          │          RUNNING             │←──── resume
          └──┬───────────┬───────────┬───┘
             │           │           │
        shutdown()   destroy()   error
             │           │           │
             ▼           │           ▼
        ┌──────────┐     │     ┌──────────┐
        │ SHUTDOWN │     │     │  ERROR   │
        └────┬─────┘     │     └──────────┘
             │           │
        delete           ▼
             │     ┌──────────┐
             ▼     │DESTROYED │  (cleanup complete)
        ┌──────────┐│          │
        │ DELETED  │└──────────┘
        └──────────┘
```

### 5.3 Network Manager

Each VM gets a dedicated virtual network interface on an isolated bridge.

```
┌──────────────────────────────────────────────────────────────┐
│                     HOST NETWORKING                           │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    agentvm-br0                          │  │
│  │                  (NAT mode bridge)                      │  │
│  │                                                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │  │
│  │  │ vnet0    │  │ vnet1    │  │ vnet2    │             │  │
│  │  │ VM-01    │  │ VM-02    │  │ VM-03    │             │  │
│  │  │10.0.0.2  │  │10.0.0.3  │  │10.0.0.4  │             │  │
│  │  └──────────┘  └──────────┘  └──────────┘             │  │
│  │                                                        │  │
│  │  Bridge IP: 10.0.0.1/24                               │  │
│  │  DHCP: dnsmasq (isolated, per-VM lease tracking)      │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │                                      │
│  ┌────────────────────┴───────────────────────────────────┐  │
│  │              iptables FORWARD chain                     │  │
│  │                                                        │  │
│  │  # Block VM → host                                     │  │
│  │  -A FORWARD -i agentvm-br0 -d <host_ip> -j DROP        │  │
│  │                                                        │  │
│  │  # Block VM → VM                                       │  │
│  │  -A FORWARD -i agentvm-br0 -o agentvm-br0 -j DROP      │  │
│  │                                                        │  │
│  │  # Allow VM → internet (NAT)                           │  │
│  │  -A FORWARD -i agentvm-br0 -o <wan> -j ACCEPT          │  │
│  │  -A FORWARD -i <wan> -o agentvm-br0 \                  │  │
│  │    -m state --state ESTABLISHED,RELATED -j ACCEPT       │  │
│  │                                                        │  │
│  │  # Rate limit per VM (tc on vnetN)                     │  │
│  │  tc qdisc add dev vnetN root tbf rate 100mbit \        │  │
│  │    burst 32kbit latency 400ms                          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              DNAMESERVER (dnsmasq)                      │  │
│  │  - Listens only on agentvm-br0                         │  │
│  │  - DHCP range: 10.0.0.100-10.0.0.254                  │  │
│  │  - DNS forwarding to host resolver                     │  │
│  │  - No access from host network                         │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Traffic isolation rules** (automated, not manual):

```
For each VM with IP 10.0.0.X:
  1. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d 10.0.0.0/24 -j DROP
  2. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d <host_mgmt_ip> -j DROP
  3. tc qdisc add dev vnet<id> root tbf rate <limit>mbit burst 32kbit latency 400ms
```

### 5.4 Storage Manager

```
/var/lib/agentvm/
├── base/                              # Golden images (read-only, root:root, 0444)
│   ├── ubuntu-24.04-amd64.qcow2      # Pre-built base image
│   ├── debian-12-amd64.qcow2
│   └── fedora-40-amd64.qcow2
│
├── vms/                               # Per-VM runtime data
│   ├── vm-<uuid>/
│   │   ├── disk.qcow2                 # COW overlay (backing: base/ubuntu-24.04.qcow2)
│   │   ├── cloud-init.iso             # Instance metadata (SSH keys, hostname)
│   │   ├── console.log                # Serial console output
│   │   └── metadata.json              # VM spec, timestamps, owner
│   └── vm-<uuid>/
│       └── ...
│
├── metadata.db                        # SQLite: VM registry, resource allocations
│
├── keys/                              # SSH key management
│   ├── vm-<uuid>_ed25519              # Auto-generated per-VM keypair
│   └── vm-<uuid>_ed25519.pub
│
├── logs/                              # Centralized logging
│   ├── audit.log                      # All API calls + VM lifecycle events
│   └── vm-<uuid>/
│       ├── serial.log                 # QEMU serial console capture
│       └── network.log                # Netflow data
│
└── images/                            # Downloaded/uploaded ISO images
```

**Disk creation flow:**

```
1. Read base image:  base/ubuntu-24.04-amd64.qcow2
2. Create overlay:   qemu-img create -f qcow2 -F qcow2 \
                       -b base/ubuntu-24.04-amd64.qcow2 \
                       vms/vm-<uuid>/disk.qcow2 <size>
3. The overlay starts empty (0 bytes actual). It only stores
   writes/changes. Reads fall through to the base image.
4. On destroy: rm vms/vm-<uuid>/  (instant cleanup)
```

### 5.5 Metadata Store (SQLite Schema)

```sql
CREATE TABLE vms (
    id            TEXT PRIMARY KEY,          -- UUID
    name          TEXT UNIQUE NOT NULL,
    owner         TEXT NOT NULL,             -- API key or user ID
    status        TEXT NOT NULL,             -- requested|creating|running|shutdown|destroyed|error
    base_image    TEXT NOT NULL,
    cpu_cores     INTEGER NOT NULL,
    memory_mb     INTEGER NOT NULL,
    disk_gb       INTEGER NOT NULL,
    network_mbps  INTEGER NOT NULL DEFAULT 100,
    ssh_host      TEXT,                      -- IP assigned by DHCP
    ssh_port      INTEGER,                  -- forwarded port or direct
    ssh_key_path  TEXT,
    created_at    TEXT NOT NULL,             -- ISO8601
    destroyed_at  TEXT,
    error_message TEXT,
    metadata_json TEXT                       -- arbitrary user metadata
);

CREATE TABLE resource_allocations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vm_id         TEXT NOT NULL REFERENCES vms(id),
    cpu_pinning   TEXT NOT NULL,             -- JSON: [0,1,2,3]
    numa_node     INTEGER,
    cgroup_path   TEXT,
    bridge_name   TEXT,
    vnet_name     TEXT,
    disk_path     TEXT NOT NULL,
    allocated_at  TEXT NOT NULL
);

CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    action        TEXT NOT NULL,             -- create|destroy|status|list
    actor         TEXT NOT NULL,             -- API key or system
    vm_id         TEXT,
    detail        TEXT,                      -- JSON
    ip_address    TEXT
);

CREATE INDEX idx_vms_owner ON vms(owner);
CREATE INDEX idx_vms_status ON vms(status);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
```

### 5.6 Observability Stack

```
┌──────────────────────────────────────────────────────────┐
│                    Observability                          │
│                                                          │
│  ┌─────────────────┐   ┌──────────────────────────────┐  │
│  │  Metrics        │   │  Logging                     │  │
│  │                 │   │                              │  │
│  │  Per VM:        │   │  Per VM:                     │  │
│  │  - CPU usage %  │   │  - Serial console capture    │  │
│  │  - Memory used  │   │  - QEMU log output           │  │
│  │  - Disk reads   │   │  - Network connections       │  │
│  │  - Disk writes  │   │                              │  │
│  │  - Net RX bytes │   │  Host:                       │  │
│  │  - Net TX bytes │   │  - API access log            │  │
│  │  - VM state     │   │  - Lifecycle audit log       │  │
│  │                 │   │  - libvirtd log              │  │
│  │  Host:          │   │  - Security alerts           │  │
│  │  - Total CPU %  │   │                              │  │
│  │  - Total RAM %  │   └──────────────────────────────┘  │
│  │  - Disk usage % │                                      │
│  │  - VM count     │   ┌──────────────────────────────┐  │
│  │  - Network flow │   │  Health                      │  │
│  │                 │   │                              │  │
│  │  Source:        │   │  - VM boot detection         │  │
│  │  - cgroups v2   │   │    (SSH reachability or      │  │
│  │  - libvirt API  │   │     QEMU guest agent ping)   │  │
│  │  - /proc/net    │   │  - Host health dashboard     │  │
│  │  - Prometheus   │   │  - Resource exhaustion        │  │
│  │    exporter     │   │    alerts                    │  │
│  └─────────────────┘   └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**Metrics collection approach:**

```
# Python-based metrics collector (runs in daemon process)
# Scrapes cgroups v2 and libvirt stats every 15 seconds

Per-VM metrics (from cgroups v2):
  /sys/fs/cgroup/agentvm.slice/vm-<uuid>.scope/
  ├── cpu.stat          → cpu usage (user + system)
  ├── memory.current    → current memory usage
  ├── memory.max        → memory limit
  ├── io.stat           → disk I/O per device
  └── pids.current      → process count

Per-VM metrics (from libvirt):
  domain.info()         → state, max mem, memory, nr vcpus, cpu time
  domain.interfaceStats("vnet0") → rx/tx bytes, packets, errors
  domain.blockStats("vda")      → rd/wr bytes, operations

Host metrics:
  /proc/stat, /proc/meminfo, /proc/net/dev
  df output for disk usage
```

---

## 6. API Specification

### 6.1 Endpoints

```
Base URL: http://localhost:9090/api/v1
Auth:     Bearer token (API key passed in Authorization header)

POST   /vms                    Create a new agent VM
GET    /vms                    List all VMs (filtered by auth token)
GET    /vms/{vm_id}            Get VM details and status
DELETE /vms/{vm_id}            Destroy a VM and clean up
GET    /vms/{vm_id}/ssh        Get SSH connection info
GET    /vms/{vm_id}/metrics    Get VM resource metrics (last N data points)
GET    /vms/{vm_id}/logs       Stream or fetch VM console logs

GET    /health                 Host health check
GET    /capacity               Available resources on host
GET    /metrics                Prometheus-format metrics endpoint

POST   /images                 Upload a new base image
GET    /images                 List available base images
DELETE /images/{name}          Remove a base image
```

### 6.2 VM Creation Request/Response

**Request:**
```json
POST /api/v1/vms
{
  "name": "agent-research-bot",
  "base_image": "ubuntu-24.04-amd64",
  "cpu_cores": 4,
  "memory_mb": 8192,
  "disk_gb": 50,
  "network_mbps": 100,
  "ssh_public_key": "ssh-ed25519 AAAA...",
  "metadata": {
    "agent_id": "agent-12345",
    "task": "code-review"
  }
}
```

**Response:**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "agent-research-bot",
  "status": "creating",
  "base_image": "ubuntu-24.04-amd64",
  "cpu_cores": 4,
  "memory_mb": 8192,
  "disk_gb": 50,
  "ssh": {
    "host": "10.0.0.2",
    "port": 22,
    "username": "root",
    "private_key_ref": "/api/v1/vms/a1b2c3d4/ssh"
  },
  "created_at": "2026-03-28T14:30:00Z",
  "metadata": {
    "agent_id": "agent-12345",
    "task": "code-review"
  }
}
```

### 6.3 Error Responses

```json
// 400 - Bad request
{ "error": "invalid_spec", "detail": "cpu_cores must be between 1 and 32" }

// 409 - Conflict (name taken)
{ "error": "name_conflict", "detail": "VM name 'agent-research-bot' already exists" }

// 507 - Insufficient resources
{ "error": "capacity_exceeded", "detail": "Not enough memory: requested 8192MB, available 4096MB" }

// 404 - Not found
{ "error": "not_found", "detail": "VM a1b2c3d4 not found" }
```

---

## 7. CLI Specification

```
agentvm — manage isolated VMs for AI agents

COMMANDS:
  create    Create a new VM
  destroy   Destroy a VM and release resources
  list      List all VMs
  status    Show VM details and resource usage
  ssh       Get SSH command or open SSH session
  logs      Tail VM console logs
  images    Manage base images
  host      Show host health and capacity

EXAMPLES:
  agentvm create \
    --name my-agent \
    --image ubuntu-24.04-amd64 \
    --cpu 4 --memory 8G --disk 50G \
    --ssh-key ~/.ssh/id_ed25519.pub

  agentvm destroy my-agent
  agentvm list
  agentvm status my-agent
  agentvm ssh my-agent
  agentvm logs my-agent --follow

GLOBAL OPTIONS:
  --api-url    API endpoint (default: http://localhost:9090)
  --api-key    Authentication key
  --format     Output format: table, json, yaml
  --verbose    Verbose output
```

---

## 8. Nested Virtualization Configuration

This is what allows agents to run Docker/Podman and KVM inside their VMs.

```
Host requirements:
  1. CPU with VT-x/AMD-V and EPT/NPT
  2. Module loaded: kvm_intel or kvm_amd
  3. Nested virt enabled:
     # Intel
     echo 1 > /sys/module/kvm_intel/parameters/nested
     # AMD
     echo 1 > /sys/module/kvm_amd/parameters/nested
  4. Verify: cat /sys/module/kvm_intel/parameters/nested → Y

Libvirt VM configuration (applied to every agent VM):
  <cpu mode='host-passthrough' check='none'>
    <feature policy='require' name='vmx'/>   <!-- Intel -->
    <!-- OR -->
    <feature policy='require' name='svm'/>   <!-- AMD -->
  </cpu>

  <!-- Nested virt requires full TCG fallback disabled -->
  <features>
    <kvm>
      <hidden state='on'/>   <!-- hide KVM from guest (prevents detection) -->
    </kvm>
  </features>

What the agent can do inside the VM:
  ✓ Run docker (needs overlayfs + cgroups, works out of box)
  ✓ Run podman (rootless, works out of box)
  ✓ Run KVM nested VMs (needs vmx/svm exposed)
  ✓ Install any software (full root, full Linux)
  ✗ See outside the VM (no shared memory, no host filesystem)
  ✗ Access other VMs (blocked at network layer)
  ✗ Exhaust host resources (cgroup limits)
```

---

## 9. VM XML Template (libvirt domain definition)

```xml
<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>
  <name>vm-{uuid}</name>
  <uuid>{uuid}</uuid>
  <memory unit='MiB'>{memory_mb}</memory>
  <vcpu placement='static'>{cpu_cores}</vcpu>

  <!-- CPU pinning: bind vCPUs to specific physical cores -->
  <cputune>
    {cpu_pins}
    <!-- Example: <vcpupin vcpu='0' cpuset='4'/> -->
  </cputune>

  <!-- NUMA awareness for memory locality -->
  <numatune>
    <memory mode='strict' nodeset='{numa_node}'/>
  </numatune>

  <!-- Nested virtualization: expose hardware virt to guest -->
  <cpu mode='host-passthrough' check='none'>
    <feature policy='require' name='vmx'/>
    <feature policy='disable' name='hypervisor'/>
  </cpu>

  <!-- Memory: lock pages, prevent host swap -->
  <memoryBacking>
    <locked/>
  </memoryBacking>

  <os>
    <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
    <boot dev='hd'/>
  </os>

  <features>
    <acpi/>
    <apic/>
    <!-- Hide hypervisor from guest (prevents "am I in a VM?" detection) -->
    <kvm>
      <hidden state='on'/>
    </kvm>
    <!-- Restrict MSRs to prevent side-channel attacks -->
    <msrs state='on' unknown='ignore'/>
  </features>

  <!-- Clock: use host-independent source -->
  <clock offset='utc'>
    <timer name='rtc' tickpolicy='catchup'/>
    <timer name='pit' tickpolicy='delay'/>
    <timer name='hpet' present='no'/>
  </clock>

  <devices>
    <!-- Disk: virtio-blk for performance -->
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='none' io='native'/>
      <source file='{disk_path}'/>
      <target dev='vda' bus='virtio'/>
      <address type='pci' domain='0x0000' bus='0x04' slot='0x00' function='0x0'/>
    </disk>

    <!-- Cloud-init ISO for first-boot configuration -->
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      <source file='{cloud_init_iso}'/>
      <target dev='sda' bus='sata'/>
      <readonly/>
    </disk>

    <!-- Network: virtio-net on isolated bridge -->
    <interface type='bridge'>
      <source bridge='{bridge_name}'/>
      <model type='virtio'/>
      <target dev='{vnet_name}'/>
      <address type='pci' domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>
    </interface>

    <!-- Serial console for headless access -->
    <serial type='file'>
      <source path='{console_log}'/>
    </serial>
    <console type='file'>
      <source path='{console_log}'/>
    </console>

    <!-- QEMU Guest Agent (for in-VM operations) -->
    <channel type='unix'>
      <source mode='bind' path='{ga_socket}'/>
      <target type='virtio' name='org.qemu.guest_agent.0'/>
    </channel>

    <!-- RNG: virtio-rng for entropy -->
    <rng model='virtio'>
      <backend model='random'>/dev/urandom</backend>
    </rng>

    <!-- DISABLED: everything unnecessary -->
    <!-- No USB controller -->
    <!-- No sound card -->
    <!-- No video/graphics (headless) -->
    <!-- No smartcard -->
    <!-- No tablet -->
    <!-- No watchdog -->
    <!-- No memballoon (prevents guest from manipulating memory reporting) -->
  </devices>

  <!-- Resource limits: prevent QEMU process from consuming host resources -->
  <resource>
    <partition>/machine</partition>
  </resource>

  <!-- seccomp sandbox for QEMU process itself -->
  <seccomp/>
</domain>
```

---

## 10. cgroups v2 Resource Enforcement

```
After VM starts, agentvm daemon places QEMU process in constrained cgroup:

/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/

# CPU: pin to specific cores + set quota
echo "0-3" > cpuset.cpus           # only run on cores 0-3
echo "0" > cpuset.mems             # only use NUMA node 0
echo "400000 100000" > cpu.max     # 400ms per 100ms period = 4 cores max

# Memory: hard limit
echo "8589934592" > memory.max     # 8GB hard limit
echo "8589934592" > memory.high    # 8GB soft limit (triggers reclaim)

# I/O: throttle disk
echo "8:0 rbps=1073741824 wbps=1073741824" > io.max
  # 1GB/s read, 1GB/s write on device 8:0

# PIDs: prevent fork bombs
echo "1000" > pids.max             # max 1000 processes
```

---

## 11. Project Directory Structure

```
agentvm/
├── pyproject.toml              # Python project config
├── README.md
├── AGENTS.md                   # Development guidance
├── docs/
│   └── design.md               # This document
│
├── src/
│   └── agentvm/
│       ├── __init__.py
│       ├── config.py            # Configuration loading (YAML/env/CLI)
│       ├── daemon.py            # FastAPI application + startup/shutdown
│       │
│       ├── vm/
│       │   ├── __init__.py
│       │   ├── manager.py       # Core VM lifecycle (create/destroy/status)
│       │   ├── spec.py          # VM specification dataclasses
│       │   ├── xml_builder.py   # libvirt XML template engine
│       │   └── state.py         # VM state machine
│       │
│       ├── net/
│       │   ├── __init__.py
│       │   ├── bridge.py        # Bridge creation and management
│       │   ├── firewall.py      # iptables rule management
│       │   ├── dhcp.py          # dnsmasq integration
│       │   └── rate_limit.py    # tc (traffic control) integration
│       │
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── pool.py          # Storage pool management
│       │   ├── images.py        # Base image management
│       │   ├── disks.py         # qcow2 overlay creation/deletion
│       │   └── cloud_init.py    # cloud-init ISO generation
│       │
│       ├── host/
│       │   ├── __init__.py
│       │   ├── capacity.py      # Resource availability checks
│       │   ├── cgroups.py       # cgroups v2 enforcement
│       │   ├── hardening.py     # Host security verification
│       │   └── cpu_map.py       # CPU topology and pinning logic
│       │
│       ├── observe/
│       │   ├── __init__.py
│       │   ├── metrics.py       # Prometheus metrics collection
│       │   ├── logging_cfg.py   # Structured logging setup
│       │   ├── audit.py         # Audit trail
│       │   └── health.py        # VM and host health checks
│       │
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py           # FastAPI router definitions
│       │   ├── routes/
│       │   │   ├── vms.py       # VM CRUD endpoints
│       │   │   ├── images.py    # Image management endpoints
│       │   │   └── health.py    # Health/capacity endpoints
│       │   ├── schemas.py       # Pydantic request/response models
│       │   ├── auth.py          # API key authentication
│       │   └── errors.py        # Error handling middleware
│       │
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py          # Click CLI commands
│       │
│       └── db/
│           ├── __init__.py
│           └── store.py         # SQLite operations (aiosqlite)
│
├── config/
│   ├── agentvm.yaml             # Default configuration
│   └── host-hardening.sh        # Host setup script
│
├── images/
│   ├── build-base-image.sh      # Packer/custom script to build golden images
│   └── cloud-init/
│       ├── meta-data.yaml
│       └── user-data.yaml       # Default cloud-init config
│
├── tests/
│   ├── unit/
│   │   ├── test_vm_manager.py
│   │   ├── test_xml_builder.py
│   │   ├── test_network.py
│   │   ├── test_storage.py
│   │   └── test_capacity.py
│   ├── integration/
│   │   ├── test_vm_lifecycle.py  # Creates/destroys real VMs (needs KVM)
│   │   ├── test_nested_virt.py   # Verifies nested KVM works inside VM
│   │   ├── test_isolation.py     # Verifies VMs can't reach each other/host
│   │   └── test_resource_limits.py
│   └── security/
│       ├── test_escape_attempts.py
│       └── test_network_isolation.py
│
└── scripts/
    ├── setup-host.sh            # One-time host setup
    ├── build-image.sh           # Build base VM image
    └── dev-environment.sh       # Local dev setup
```

---

## 12. Implementation Phases

### Phase 1: Foundation (Week 1-2)

```
Goal: Can create and destroy a single KVM VM via Python code

Tasks:
  [ ] Host prerequisite checks (KVM, libvirt, nested virt)
  [ ] libvirt connection management
  [ ] VM XML builder (from template above)
  [ ] Basic VM create/destroy via libvirt Python bindings
  [ ] qcow2 overlay disk creation
  [ ] Cloud-init ISO generation (SSH key injection)
  [ ] SQLite metadata store
  [ ] Basic unit tests

Deliverable: Python script that creates a VM, SSHs in, then destroys it
```

### Phase 2: API + CLI (Week 2-3)

```
Goal: REST API for VM lifecycle, basic CLI

Tasks:
  [ ] FastAPI application structure
  [ ] POST/GET/DELETE /vms endpoints
  [ ] Pydantic request/response schemas
  [ ] API key authentication
  [ ] Click CLI: create, destroy, list, status, ssh
  [ ] Error handling and validation
  [ ] OpenAPI docs (auto-generated by FastAPI)

Deliverable: `agentvm create --name test --image ubuntu-24.04 --cpu 2 --memory 4G`
```

### Phase 3: Networking + Isolation (Week 3-4)

```
Goal: VMs are fully isolated from each other and host

Tasks:
  [ ] Bridge creation and management
  [ ] dnsmasq DHCP per bridge
  [ ] iptables rule automation (VM→VM block, VM→host block, NAT for outbound)
  [ ] Traffic control (tc) rate limiting per VM
  [ ] Network cleanup on VM destroy
  [ ] Integration tests: verify isolation (VM can't ping host, can't ping other VM)

Deliverable: Two VMs running simultaneously, neither can see the other
```

### Phase 4: Resource Enforcement (Week 4-5)

```
Goal: Guaranteed resource limits, no resource starvation

Tasks:
  [ ] CPU pinning logic (topology-aware allocation)
  [ ] cgroups v2 setup for each VM's QEMU process
  [ ] Memory hard limits
  [ ] Disk I/O throttling
  [ ] Capacity checking before VM creation
  [ ] Resource exhaustion handling and alerts
  [ ] Integration tests: verify limits hold under stress

Deliverable: VM running `stress-ng` cannot exceed its allocated resources
```

### Phase 5: Observability + Security (Week 5-6)

```
Goal: Full host visibility, security hardening complete

Tasks:
  [ ] Prometheus metrics exporter
  [ ] Per-VM metrics collection (cgroups + libvirt)
  [ ] Audit logging for all operations
  [ ] Console log capture
  [ ] Host hardening script (sysctl, SELinux, firewall, service lockdown)
  [ ] Health checks (host + per-VM)
  [ ] Security tests: attempt VM escape, verify containment

Deliverable: Grafana dashboard showing all VM resource usage + host health
```

### Phase 6: Production Readiness (Week 6-7)

```
Goal: Robust, production-quality platform

Tasks:
  [ ] Error recovery (VM crash cleanup, orphaned resource detection)
  [ ] Base image management (upload, list, delete)
  [ ] Configuration file support (YAML)
  [ ] systemd service file for daemon
  [ ] Comprehensive documentation
  [ ] Load testing (many concurrent VMs)
  [ ] Graceful shutdown (drain VMs on daemon stop)
  [ ] VM TTL support (auto-destroy after N hours)

Deliverable: `systemctl start agentvm` runs the full platform
```

---

## 13. Configuration File

```yaml
# /etc/agentvm/agentvm.yaml

host:
  name: "agentvm-host-01"
  max_vms: 20

storage:
  base_dir: "/var/lib/agentvm"
  base_images_dir: "/var/lib/agentvm/base"
  vm_data_dir: "/var/lib/agentvm/vms"
  default_image: "ubuntu-24.04-amd64"

network:
  bridge_name: "agentvm-br0"
  bridge_subnet: "10.0.0.0/24"
  bridge_gateway: "10.0.0.1"
  dhcp_range_start: "10.0.0.100"
  dhcp_range_end: "10.0.0.254"
  default_bandwidth_mbps: 100
  wan_interface: "eth0"           # for NAT masquerade

resources:
  default_cpu_cores: 2
  default_memory_mb: 4096
  default_disk_gb: 20
  max_cpu_cores: 16
  max_memory_mb: 65536
  max_disk_gb: 200
  # Reserve cores for host (never allocate to VMs)
  reserved_cores: [0, 1]
  # Reserved memory for host OS (MB)
  reserved_memory_mb: 4096

api:
  host: "127.0.0.1"               # bind to localhost only by default
  port: 9090
  # API keys (or use separate auth file)
  api_keys:
    - key: "change-me-in-production"
      name: "admin"
      permissions: ["create", "destroy", "list", "admin"]

security:
  selinux_enforcing: true
  enable_audit_log: true
  vm_max_lifetime_hours: 24       # auto-destroy after 24h (0 = no limit)
  ssh_key_required: true          # require SSH key for VM creation

observability:
  metrics_enabled: true
  metrics_port: 9091              # Prometheus exporter port
  log_level: "INFO"
  console_log_dir: "/var/lib/agentvm/logs"
```

---

## 14. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| QEMU VM escape via device vulnerability | Low | Critical | Minimal device model (virtio only), no USB/audio/video, keep QEMU updated |
| Kernel exploit allowing host access | Low | Critical | Host kernel hardening (sysctl), SELinux enforcing, regular patching |
| Resource exhaustion (too many VMs) | Medium | High | Capacity checking before creation, resource reservation, alerts at 80% |
| Network isolation misconfiguration | Medium | High | Automated iptables management (no manual rules), integration tests |
| Orphaned resources after crash | Medium | Medium | Periodic cleanup job, resource tracking in SQLite |
| Nested virt performance degradation | High | Low | Document overhead expectations, let agent tune within VM |
| API authentication bypass | Low | Critical | Token auth, bind to localhost by default, optional TLS |

---

## 15. Technology Stack Summary

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Available in environment, libvirt bindings, async support |
| Hypervisor | KVM/QEMU via libvirt | Only option with production-grade nested virt support |
| API Framework | FastAPI + Uvicorn | Async, auto OpenAPI docs, Pydantic validation |
| CLI | Click | Standard Python CLI framework |
| Metadata Store | SQLite (aiosqlite) | Simple, zero-config, sufficient for single-host |
| Metrics | Prometheus client + custom exporter | Industry standard, integrates with Grafana |
| Logging | structlog | Structured JSON logging |
| Networking | libvirt NAT + iptables + tc | Battle-tested, fully automated |
| Storage | qcow2 overlays on base images | Fast provisioning (COW), efficient disk usage |
| VM Config | cloud-init | Standard for VM initialization |
| Packaging | pip/setuptools | Simple Python packaging |

---

## 16. Key Design Decisions Summary

| Decision | Choice | Why |
|---|---|---|
| Hypervisor | KVM/QEMU + libvirt | Nested virt support, mature, battle-tested |
| VM type | Full VMs (not containers) | Hardware isolation, adversarial agent assumption |
| API style | REST (JSON) | Simple, language-agnostic, easy to integrate |
| Storage backend | qcow2 COW overlays | Fast create/destroy, space-efficient |
| Metadata | SQLite | Simple, embedded, sufficient for single-host |
| Network | NAT bridge + iptables | Proven isolation, automated management |
| Security model | Defense-in-depth (6 layers) | No single point of failure |
| Resource control | cgroups v2 | Kernel-enforced, per-process granularity |

This design prioritizes **host security over agent convenience** while still giving agents the freedom to run arbitrary workloads including Docker, Podman, and nested VMs.

---

That is the complete design. Shall I proceed to implementation, or would you like to adjust any aspect of the design first?

