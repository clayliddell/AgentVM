# Project Context Summary

## Goal

The user initially wanted to test restoring a SeedVault backup in GrapheneOS by creating a GrapheneOS Android VM inside a podman sandbox. This evolved into a deep architectural exploration of sandboxing approaches, comparing clampdown (container-based) vs a hypothetical AgentVMs (VM-based) design, and then revising the AgentVMs design document to achieve feature parity with clampdown for future orchestrator compatibility.

## Instructions

- The work environment is a clampdown sandbox (container-based AI agent sandbox). Podman is available via a sidecar daemon on the host. KVM exists on the host but is **not accessible** from the sandbox (Landlock/OCI hooks block `/dev/kvm`).
- The user asked to explore the clampdown repository (89luca89/clampdown on GitHub) to understand its architecture and security model.
- The user provided a `DESIGN.md` file — a hypothetical design for "AgentVMs" (KVM/QEMU-based VM isolation for AI agents) — and asked for a comparison with clampdown.
- The user asked whether it makes sense to refactor clampdown to incorporate AgentVMs. The conclusion: **no, they should be separate tools** with an orchestrator on top.
- The user then asked to evaluate AgentVMs design against clampdown for feature parity, specifically addressing: (1) auth proxy for API secret injection, (2) shared folder with host, (3) extensive testing with red-team tactics.
- The user asked to revise `DESIGN.md` to incorporate all changes for feature parity.

## Discoveries

- **clampdown architecture**: Container-based sandboxing using Landlock (filesystem), seccomp (syscalls), OCI hooks (`security-policy` with 17 checks, `seal-inject` for Landlock), a seccomp-notif supervisor intercepting 20 syscalls, auth proxy (real API keys never enter agent), and two-tier network policy (deny-by-default agent, allow tool containers). The `security-policy` hook blocks dangerous devices including `/dev/kvm` — **there is no opt-out**.
- **KVM is unsafe to grant in clampdown**: KVM kernel module is a large attack surface, VMs can do DMA without IOMMU, timing side-channels exist. Clampdown correctly blocks it.
- **Two philosophies are fundamentally different**: Clampdown uses host kernel features (Landlock, seccomp, OCI hooks) for container isolation. AgentVMs uses hardware virtualization (KVM, cgroups, SELinux sVirt) for VM isolation. The security enforcement layers are irreconcilable — they use different kernel APIs.
- **Orchestrator pattern is viable**: A thin routing layer can sit above both backends, using a uniform `IsolationBackend` protocol. The orchestrator routes based on workload needs (KVM? → agentvm; lightweight? → clampdown).
- **GrapheneOS cuttlefish images are NOT published** on `releases.grapheneos.org`. The releases page only has device-specific install/OTA images. Cuttlefish images would need to be built from source or obtained from AOSP CI.
- **Podman in this sandbox**: Containers run as root (uid 0) for the OCI security policy to accept them. Non-root `USER` directives in Dockerfiles cause `OCI runtime error` from the security-policy hook.

## Accomplished

1. **Explored clampdown architecture** — read the GitHub README, understood the 4-container model (sidecar, auth proxy, agent, tool), 17 OCI hook checks, Landlock tiers, seccomp profiles, network isolation.

2. **Compared clampdown vs AgentVMs** — detailed analysis of isolation primitives, security models, nested virt gap, performance/density tradeoffs, network models. Concluded they should be separate tools.

3. **Evaluated AgentVMs for feature parity** — identified gaps: session model, runtime network control, auth proxy, shared folder, unified audit format, filesystem policy, orchestrator contract, image metadata with capabilities, testing strategy.

4. **Revised DESIGN.md** — wrote complete 2,140-line revised design (up from 1,118 lines) incorporating:
   - Auth proxy (§4.3, §5.5) — Go static binary, per-session, host-side, real keys never enter VM
   - Shared folders (§4.2, §5.4) — virtiofs/9p with AppArmor escape prevention
   - Session model (§5.2) — `WorkloadSession` abstraction for orchestrator compatibility
   - Three network modes (§5.3) — strict (deny-by-default + allowlist), restricted (allow + blocklist), permissive; with runtime `allow/block/reset` via ipset
   - Orchestrator contract (§11) — `IsolationBackend` protocol, `BackendCapabilities`, routing logic, feature parity matrix
   - Testing strategy (§12) — unit (≥80-95% coverage), integration (15 suites), E2E (9 suites), red-team (13 attack categories)
   - Unified audit format (§5.7), image metadata with capabilities (§5.4.2), enhanced API (§6) with 12 new endpoints
   - Expanded implementation to 8 phases / 8 weeks

5. **Built a GrapheneOS VM container** (attempted) — created `Dockerfile` and `entrypoint.sh` in the working directory, but the actual GrapheneOS VM could not be launched due to no KVM access and no published cuttlefish images.

## Relevant files / directories

- `/home/clayliddell/Documents/Personal/dev/containers/grapheneOSvm/DESIGN.md` — **The revised AgentVMs design document** (2,140 lines). This is the primary deliverable.
- `/home/clayliddell/Documents/Personal/dev/containers/grapheneOSvm/DESIGN.md.bak` — Backup of the original DESIGN.md (1,118 lines).
- `/home/clayliddell/Documents/Personal/dev/containers/grapheneOSvm/Dockerfile` — Container image for running GrapheneOS VM (built as `grapheneos-vm` image, Debian bookworm + QEMU + adb).
- `/home/clayliddell/Documents/Personal/dev/containers/grapheneOSvm/entrypoint.sh` — Shell script for downloading GrapheneOS cuttlefish images and launching QEMU VM.
- `/tmp/grapheneos-build/` — Build context used during container image construction.
