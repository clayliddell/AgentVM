# Network Manager — Low-Level Design

## Component Name: Network Manager

The Network Manager provides per-VM network isolation via a NAT bridge, iptables firewall rules, ipset-based domain filtering, dnsmasq DHCP, and traffic control (tc) rate limiting. It supports three policy modes (strict, restricted, permissive) with runtime domain allow/block control.

**Source files:** `src/agentvm/net/bridge.py`, `src/agentvm/net/firewall.py`, `src/agentvm/net/dhcp.py`, `src/agentvm/net/rate_limit.py`, `src/agentvm/net/policy.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| NET-FR-01 | Create and manage a NAT bridge (`agentvm-br0`) with a configurable subnet (default `10.0.0.0/24`) | 5.3 |
| NET-FR-02 | Assign unique IP addresses to VMs via dnsmasq DHCP with per-VM lease tracking | 5.3 |
| NET-FR-03 | Block all VM→host traffic via iptables | 5.3, 5.3.3 |
| NET-FR-04 | Block all VM→VM traffic via iptables | 5.3, 5.3.3 |
| NET-FR-05 | Block all VM→private CIDR (RFC 1918) traffic via iptables | 5.3, 5.3.3 |
| NET-FR-06 | Implement three network policy modes: strict (deny-all + allowlist), restricted (allow-all + blocklist), permissive (allow-all) | 5.3.1 |
| NET-FR-07 | Support runtime `allow_domain()` — resolve domain to IPs and add to session's ipset | 5.3.2 |
| NET-FR-08 | Support runtime `block_domain()` — resolve domain to IPs and add to session's blocklist ipset | 5.3.2 |
| NET-FR-09 | Support runtime `reset_network()` — flush session ipsets back to startup defaults | 5.3.2 |
| NET-FR-10 | Apply per-VM bandwidth rate limiting via `tc` (traffic control) | 5.3.3 |
| NET-FR-11 | Clean up all iptables rules, ipsets, and tc rules on session destroy | 5.3, 5.1 |
| NET-FR-12 | Return current network rules for a session | 5.3.2 |
| NET-FR-13 | Support domain filtering via dnsmasq to restrict DNS resolution per policy mode | 5.3 |
| NET-FR-14 | Provide DNS resolution utility for domain→IP mapping (used by allow/block operations) | 5.3.2 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NET-NFR-01 | Network rule application (per-VM) must complete within 2 seconds | Reliability |
| NET-NFR-02 | Runtime allow/block operations must take effect within 5 seconds | 5.3.2 |
| NET-NFR-03 | Unit test coverage ≥95% for policy logic and rule generation (security-critical) | 12.1 |
| NET-NFR-04 | All iptables/ipset commands must be atomic — partial application must roll back | Security |
| NET-NFR-05 | Bridge creation must be idempotent — safe to call on daemon startup even if bridge exists | Reliability |
| NET-NFR-06 | Network cleanup on destroy must be exhaustive — no orphaned rules or ipsets | Reliability |

---

## 3. Component API Contracts

### 3.1 Inputs (Methods Exposed)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class NetworkRule:
    domain: str
    ip_address: Optional[str]
    port: Optional[int]
    action: str                        # "allow" | "block"
    source: str                        # "startup" | "runtime"
    created_at: str

class NetworkPolicyEngine:
    """Runtime network policy control."""

    def setup_session_network(self, session_id: str, vm_ip: str,
                              policy: str, bandwidth_mbps: int) -> None:
        """Apply all network rules for a new session VM."""

    def cleanup_session_network(self, session_id: str, vm_ip: str) -> None:
        """Remove all iptables/ipset/tc rules for a session."""

    def allow_domain(self, session_id: str, domain: str,
                     port: Optional[int] = None) -> None:
        """Resolve domain, add IPs to allowlist (strict) or remove from blocklist (restricted)."""

    def block_domain(self, session_id: str, domain: str,
                     port: Optional[int] = None) -> None:
        """Resolve domain, add IPs to blocklist (restricted) or remove from allowlist (strict)."""

    def reset_network(self, session_id: str) -> None:
        """Flush session ipsets to startup defaults."""

    def get_rules(self, session_id: str) -> list[NetworkRule]:
        """Return current network rules for a session."""

    def get_session_network_policy(self, session_id: str) -> dict:
        """Return session's effective network policy: mode, default action, vnet_name, vm_ip, active rule count."""

    def update_session_ip(self, session_id: str, old_ip: str, new_ip: str) -> None:
        """Update iptables rules after VM IP changes (e.g., on resume). Replaces old_ip with new_ip in all per-VM rules."""

class BridgeManager:
    """Bridge lifecycle management."""

    def ensure_bridge(self) -> str:
        """Create bridge if not exists, return bridge name. Idempotent."""

    def get_vm_ip(self, session_id: str, vm_mac: str) -> Optional[str]:
        """Look up VM IP from dnsmasq lease file."""

    def allocate_vm_interface(self, session_id: str) -> tuple[str, str]:
        """Allocate vnet name and MAC address. Returns (vnet_name, mac_address)."""

class RateLimiter:
    """Per-VM bandwidth control."""

    def apply_rate_limit(self, vnet_name: str, bandwidth_mbps: int) -> None:
        """Apply tc rate limit to VM's vnet interface."""

    def remove_rate_limit(self, vnet_name: str) -> None:
        """Remove tc rate limit from VM's vnet interface."""
```

### 3.2 Outputs (Return Types and Events)

**Port-aware enforcement limitation:** The current implementation uses `ipset (hash:ip)` which does not support port matching. The `port` field in `NetworkRule` and `allow_domain()`/`block_domain()` is accepted for future use but is **not enforced** at the iptables level. To enforce port-specific rules, the ipset type must be changed to `hash:ip,port` and iptables rules must use `--match-set` with port matching. This is a known gap versus the HLD contract.

**IP/MAC preallocation contract:** When Session Manager creates a session, the following sequence ensures network identity is established before VM creation:
1. `BridgeManager.allocate_vm_interface(session_id)` → returns `(vnet_name, mac_address)`
2. These values are passed to `VMSpec` and used in libvirt XML generation
3. `NetworkPolicyEngine.setup_session_network(session_id, vm_ip, ...)` is called after VM boots and acquires its DHCP-assigned IP via the preallocated MAC
4. The dnsmasq lease file is consulted via `BridgeManager.get_vm_ip(session_id, mac_address)` to resolve the assigned IP

**Events emitted (to Audit Logger):**
- `network.allow` — Domain added to allowlist or removed from blocklist
- `network.block` — Domain added to blocklist or removed from allowlist
- `network.reset` — Session network rules reset to defaults

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Config** | Bridge name, subnet, DHCP range, WAN interface, default policy |
| **Metadata Store** | Network rules persistence (`network_rules` table) |
| **Observability** | Audit event emission (`observe/audit.py`) |

| Components That Call This | Purpose |
|---|---|
| **Session Manager** | `setup_session_network()` on create, `cleanup_session_network()` on destroy |
| **REST API** | Network policy endpoints (`/sessions/{sid}/network/*`) |
| **CLI** | `agentvm network allow/block/reset/list` commands |
| **Orchestrator Adapter** | `IsolationBackend.allow_network()`, `block_network()`, `reset_network()`, `get_network_rules()` |
| **VM Manager** | Receives bridge name and vnet name for XML generation |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Bridge exists and VMs can be assigned to it.

**User Stories & Tasks:**

* **Story:** As a developer, the agentvm NAT bridge exists and is functional.
  * **Task:** Implement `BridgeManager.ensure_bridge()` — check if `agentvm-br0` exists via `ip link show`. If not, create it: `ip link add agentvm-br0 type bridge`, assign IP `10.0.0.1/24`, bring up, add NAT masquerade rule for WAN interface.
    * *Identified Blockers/Dependencies:* Config must provide `network.bridge_name`, `network.bridge_subnet`, `network.wan_interface`.

* **Story:** As a developer, I can allocate a vnet interface and MAC for a new VM.
  * **Task:** Implement `BridgeManager.allocate_vm_interface()` — generate unique vnet name (`vnet<N>`) and random MAC address.
    * *Identified Blockers/Dependencies:* Bridge must exist.

---

### Phase 4: Network Isolation + Policy (Week 4-5)

**Phase Goal:** Three network modes working with runtime domain-based control.

**User Stories & Tasks:**

* **Story:** As a platform operator, each VM is isolated from the host, other VMs, and private CIDRs.
  * **Task:** Implement base iptables rules in `firewall.py` — for each VM with IP `10.0.0.X`:
    1. `-A FORWARD -i agentvm-br0 -s 10.0.0.X -d 10.0.0.0/24 -j DROP` (VM→VM/host subnet)
    2. `-A FORWARD -i agentvm-br0 -s 10.0.0.X -d <host_mgmt_ip> -j DROP` (VM→host)
    3. `-A FORWARD -i agentvm-br0 -s 10.0.0.X -d 10.0.0.0/8 -j DROP` (entire 10/8 private range per HLD)
    4. `-A FORWARD -i agentvm-br0 -s 10.0.0.X -d 172.16.0.0/12 -j DROP` (private CIDR)
    5. `-A FORWARD -i agentvm-br0 -s 10.0.0.X -d 192.168.0.0/16 -j DROP` (private CIDR)
    Rules are inserted at the top of FORWARD chain with unique comments for identification and cleanup.
    * *Identified Blockers/Dependencies:* Bridge must exist, VM must have an assigned IP.

* **Story:** As a platform operator, I can create sessions with strict, restricted, or permissive network modes.
  * **Task:** Implement ipset creation and mode-specific rules in `policy.py`:
    - **Strict**: Create `allow_<session_id>` ipset (hash:ip). Add `-A FORWARD -i agentvm-br0 -m set --match-set allow_<id> dst -j ACCEPT` before the final `-j DROP`.
    - **Restricted**: Create `block_<session_id>` ipset (hash:ip). Add `-A FORWARD -i agentvm-br0 -m set --match-set block_<id> dst -j DROP` before the final `-j ACCEPT`.
    - **Permissive**: No ipset, just `-A FORWARD -i agentvm-br0 -j ACCEPT` (private CIDRs already blocked).
    * *Identified Blockers/Dependencies:* Base iptables rules must be functional.

* **Story:** As a platform operator, I can allow/block domains at runtime.
  * **Task:** Implement `allow_domain()` — resolve domain via DNS (use `dns.resolver` or subprocess `dig`), add resolved IPs to `allow_<sid>` ipset (strict) or remove from `block_<sid>` ipset (restricted). Persist rule to `network_rules` metadata table. Emit `network.allow` audit event.
    * *Identified Blockers/Dependencies:* ipsets must exist, metadata store `network_rules` table.
  * **Task:** Implement `block_domain()` — inverse of above.
    * *Identified Blockers/Dependencies:* Same.
  * **Task:** Implement `reset_network()` — flush both `allow_<sid>` and `block_<sid>` ipsets. Mark all runtime rules as `removed_at` in metadata.
    * *Identified Blockers/Dependencies:* Same.

* **Story:** As a platform operator, I can query current network rules for a session.
  * **Task:** Implement `get_rules()` — read from `network_rules` metadata table where `removed_at IS NULL`, return `list[NetworkRule]`.
    * *Identified Blockers/Dependencies:* Metadata store.

* **Story:** As a platform operator, DNS resolution per session is filtered according to network policy mode via dnsmasq.
  * **Task:** Implement dnsmasq domain filtering (NET-FR-13) — generate per-session dnsmasq config under `/var/lib/agentvm/net/<session-id>.conf`:
    - **Strict mode**: `server=/<domain>/<resolver>` entries only for allowlisted domains; all other DNS queries return NXDOMAIN.
    - **Restricted mode**: `address=/<domain>/0.0.0.0` entries for blocklisted domains; all other queries pass through.
    - **Permissive mode**: no dnsmasq filtering, forward all to upstream resolver.
    Reload dnsmasq (`killall -HUP dnsmasq`) after config changes.
    * *Identified Blockers/Dependencies:* dnsmasq must be installed and configured per HLD Section 5.3.

* **Story:** As a platform operator, VM bandwidth is rate-limited.
  * **Task:** Implement `RateLimiter.apply_rate_limit()` — `tc qdisc add dev <vnet> root tbf rate <mbps>mbit burst 32kbit latency 400ms`.
    * *Identified Blockers/Dependencies:* vnet interface must exist.
  * **Task:** Implement `RateLimiter.remove_rate_limit()` — `tc qdisc del dev <vnet> root`.
    * *Identified Blockers/Dependencies:* Same.

* **Story:** As a platform operator, all network resources are cleaned up on session destroy.
  * **Task:** Implement `cleanup_session_network()` — delete session-specific iptables rules (identified by comment), destroy ipsets (`ipset destroy allow_<sid>`, `ipset destroy block_<sid>`), remove tc rules, delete `network_rules` metadata entries.
    * *Identified Blockers/Dependencies:* All rule creation paths must use consistent naming/commenting.

* **Story:** As a developer, I have integration tests for all three network modes.
  * **Task:** Implement `test_network_modes.py` — create VMs in each mode, verify: strict blocks all except allowlisted, restricted blocks blocklisted, permissive allows all except private CIDRs. Verify VM→VM and VM→host are blocked in all modes.
    * *Identified Blockers/Dependencies:* VM Manager must be functional.
  * **Task:** Implement `test_network_runtime.py` — start VM in strict mode, allow a domain, verify access, block it, verify access revoked.
    * *Identified Blockers/Dependencies:* Same.

---

### Phase 5: Resource Enforcement + Shared Folder (Week 5-6)

**Phase Goal:** Network bandwidth enforcement is validated under stress.

**User Stories & Tasks:**

* **Story:** As a platform operator, VMs cannot exceed their bandwidth allocation.
  * **Task:** Implement integration test `test_resource_limits.py` — run `iperf3` inside VM, verify throughput does not exceed configured `network_mbps`.
    * *Identified Blockers/Dependencies:* Rate limiter, VM with SSH access.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| Bridge creation failure (e.g., `agentvm-br0` already exists with different config) | Log warning, verify existing bridge config matches expected, raise error if mismatch |
| iptables command failure | Roll back any rules applied in this batch, raise `NetworkError` |
| ipset creation failure | Roll back associated iptables rules, raise `NetworkError` |
| DNS resolution failure (allow/block) | Return empty IP list with warning, do not modify ipset |
| tc command failure | Log warning, VM runs without rate limit (non-fatal) |
| Session cleanup: orphaned ipset | Daemon startup job detects and removes stale `allow_<orphan>` / `block_<orphan>` ipsets |
