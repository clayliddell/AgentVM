# Phase 4: Network Isolation + Policy

**Goal:** Three network modes (strict, restricted, permissive) working with runtime domain-based control.

**Weeks:** 4–5

---

## Network Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| NetworkManager.base_iptables | Implement base iptables rules in `firewall.py` — for each VM with IP `10.0.0.X`: block VM→VM/host subnet, block VM→host, block entire private CIDRs (10/8, 172.16/12, 192.168/16). Ref: NETWORK-LLD §6.1 | High | Blocked |
| NetworkManager.ipset_mode_rules | Implement ipset creation and mode-specific rules in `policy.py`: strict (allowlist ipset), restricted (blocklist ipset), permissive (no ipset). Ref: NETWORK-LLD §6.2 | High | Blocked |
| NetworkManager.allow_domain | Implement `allow_domain()` — resolve domain via DNS, add resolved IPs to allowlist (strict) or remove from blocklist (restricted). Persist rule to metadata. Emit `network.allow` audit event. Return type: None. Ref: NETWORK-LLD §6.3 | High | Blocked |
| NetworkManager.block_domain | Implement `block_domain()` — inverse of allow_domain. Return type: None. Ref: NETWORK-LLD §6.3 | High | Blocked |
| NetworkManager.reset_network | Implement `reset_network()` — flush both ipsets. Mark all runtime rules as `removed_at` in metadata. Ref: NETWORK-LLD §6.3 | High | Blocked |
| NetworkManager.get_rules | Implement `get_rules()` — read from `network_rules` metadata table where `removed_at IS NULL`. Ref: NETWORK-LLD §6.4 | Medium | Blocked |
| NetworkManager.dnsmasq_filtering | Implement dnsmasq domain filtering (NET-FR-13) — generate per-session dnsmasq config: strict (only allowlisted), restricted (block blocklisted), permissive (no filtering). Reload dnsmasq after changes. Ref: NETWORK-LLD §6.5 | High | Blocked |
| NetworkManager.rate_limiter_apply | Implement `RateLimiter.apply_rate_limit()` — `tc qdisc add dev <vnet> root tbf rate <mbps>mbit burst 32kbit latency 400ms`. Ref: NETWORK-LLD §6.6 | Medium | Blocked |
| NetworkManager.rate_limiter_remove | Implement `RateLimiter.remove_rate_limit()` — `tc qdisc del dev <vnet> root`. Ref: NETWORK-LLD §6.6 | Medium | Blocked |
| NetworkManager.cleanup_session | Implement `cleanup_session_network()` — delete session iptables rules, destroy ipsets, remove tc rules, delete `network_rules` metadata entries. Ref: NETWORK-LLD §6.7 | High | Blocked |
| NetworkManager.get_session_network_policy | Implement `get_session_network_policy()` — return mode, vm_ip, vnet_name, rules, default_action. Ref: NETWORK-LLD §6.8 | Medium | Blocked |
| NetworkManager.update_session_ip | Implement `update_session_ip()` — update iptables rules when VM IP changes on resume. Ref: NETWORK-LLD §6.8 | Medium | Blocked |
| NetworkManager.test_network_modes | Implement `test_network_modes.py` — create VMs in each mode, verify isolation. Ref: NETWORK-LLD §6.9 | Medium | Blocked |
| NetworkManager.test_network_runtime | Implement `test_network_runtime.py` — start VM in strict mode, allow a domain, verify access, block it, verify access revoked. Ref: NETWORK-LLD §6.9 | Medium | Blocked |

## Metadata Store

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| MetadataStore.network_rule_crud | Implement network rule CRUD: `create_network_rule()`, `get_network_rules()` (with `active_only`), `deactivate_network_rule()`, `deactivate_all_network_rules()`, `delete_network_rules()`. Ref: METADATA-LLD §7.1 | High | Blocked |

---

## Phase 4 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P4-FR-01 | VM isolation — VMs cannot reach other VMs, the host, or private CIDRs (10/8, 172.16/12, 192.168/16) | iptables rules block all inter-VM and VM→host traffic; private CIDRs fully blocked |
| P4-FR-02 | Strict mode — only domains in the allowlist ipset are reachable; all other outbound blocked | `allow_domain()` adds IPs to allowlist; non-allowlisted domains unreachable |
| P4-FR-03 | Restricted mode — domains in the blocklist ipset are blocked; all other outbound allowed | `block_domain()` adds IPs to blocklist; blocklisted domains unreachable; others reachable |
| P4-FR-04 | Permissive mode — no outbound restrictions beyond base isolation | VM can reach any external host but not other VMs or private CIDRs |
| P4-FR-05 | `allow_domain()` and `block_domain()` return `None` (matching HLD contract) | Function signatures return `None` |
| P4-FR-06 | Network rules persisted to metadata store and survive daemon restart | Query `network_rules` table after restart; rules with `removed_at IS NULL` are still active |
| P4-FR-07 | DNS resolution per session filtered by dnsmasq according to network policy mode (NET-FR-13) | Strict: only allowlisted domains resolve. Restricted: blocklisted domains do not resolve. Permissive: all domains resolve |
| P4-FR-08 | Bandwidth rate limiting enforced via `tc` — VM throughput does not exceed configured `network_mbps` | `iperf3` test inside VM shows throughput <= configured limit |
| P4-FR-09 | `cleanup_session_network()` removes all iptables rules, ipsets, tc rules, and metadata for a session | After destroy: `iptables-save` shows no session rules; `ipset list` shows no session ipsets; `tc qdisc show` shows no session qdiscs |
| P4-FR-10 | RFC1918 blocking covers entire ranges: `10.0.0.0/8` (not just `/24`), `172.16.0.0/12`, `192.168.0.0/16` | `iptables -L` shows rules matching full CIDR ranges |

## Phase 4 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-4.1: VM isolation** — Create 2 sessions, verify VM-A cannot ping VM-B, cannot ping host, cannot reach 10.0.0.0/8, 172.16.0.0/12, or 192.168.0.0/16
- [ ] **E2E-4.2: Strict mode allow** — Create session in strict mode, verify outbound fails by default; `allow_domain("api.openai.com")`, verify outbound to resolved IPs succeeds
- [ ] **E2E-4.3: Restricted mode block** — Create session in restricted mode, verify outbound works by default; `block_domain("evil.com")`, verify outbound to resolved IPs fails
- [ ] **E2E-4.4: Permissive mode** — Create session in permissive mode, verify outbound to arbitrary domains works (only base isolation applies)
- [ ] **E2E-4.5: DNS filtering** — In strict mode, verify only allowlisted domains resolve via dnsmasq. In restricted mode, verify blocklisted domains do not resolve. In permissive mode, verify all domains resolve
- [ ] **E2E-4.6: Rate limiting** — Create session with `network_mbps=100`, run `iperf3` inside VM, verify throughput <= 100 Mbit/s
- [ ] **E2E-4.7: Network cleanup** — Create session, destroy session, verify all iptables rules, ipsets, tc rules, and metadata records for that session are gone
- [ ] **E2E-4.8: Rule persistence** — Allow a domain in strict mode, restart daemon, verify rule still active in metadata and ipset
