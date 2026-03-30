# AgentVM Development Environment Setup

This document explains how to bootstrap a development environment for AgentVM. The process is automated via `./dev/setup.sh`.

## Prerequisites

- **OS:** Ubuntu 24.04 LTS (or compatible Debian-based distro)
- **Hardware:** CPU with virtualization support (Intel VT-x or AMD-V), nested KVM enabled
- **Access:** `sudo` privileges for installing system packages

## Quick Start

```bash
git clone <repo-url> agentvm
cd agentvm
./dev/setup.sh
source .venv/bin/activate
source .env
```

## What `setup.sh` Does

The script performs the following steps (all idempotent — safe to re-run):

| Step | Description |
|------|-------------|
| 1. System packages | Installs `qemu-kvm`, `libvirt-daemon-system`, `dnsmasq`, `iptables`, `cgroup-tools`, `python3.12`, `python3.12-venv`, `golang-1.22`, `git`, `make`, `genisoimage` |
| 2. KVM verification | Checks `/dev/kvm` exists and nested virt is enabled |
| 3. libvirtd | Starts and enables `libvirtd`, adds user to `libvirt` and `kvm` groups |
| 4. Python venv | Creates `.venv/` with Python 3.12, installs dev dependencies from `requirements-dev.txt` (or falls back to inline install of ruff, mypy, pytest, etc.) |
| 5. Go toolchain | Verifies Go 1.22, builds the auth proxy from `proxy/Makefile` |
| 6. Pre-commit hooks | Runs `pre-commit install` for linting and secrets scanning |
| 7. Storage dirs | Creates `/var/lib/agentvm/` with subdirectories (`base/`, `vms/`, `shared/`, `proxy/`, `keys/`, `logs/`) |
| 8. Env marker | Sets `AGENTVM_ENV_SETUP_DONE=true` in `.env` |

## The `.env` File

A `.env` file tracks whether the environment has been set up:

```
AGENTVM_ENV_SETUP_DONE=true
```

- **Purpose:** Prevents redundant setup when multiple AI agent sessions work in the same workspace.
- **Usage:** Source it at the start of each session: `source .env`
- **Gitignored:** `.env` is in `.gitignore` — it is per-developer and never committed.

## Verifying the Setup

```bash
# Activate venv
source .venv/bin/activate

# Check Python tools
ruff --version
mypy --version
pytest --version

# Check Go
go version

# Check libvirt connectivity
python -c "import libvirt; conn = libvirt.open('qemu:///system'); print('libvirt OK:', conn.getVersion())"

# Check KVM
ls -la /dev/kvm

# Check storage
ls /var/lib/agentvm/
```

## Manual Setup (Without `./dev/setup.sh`)

If you prefer manual setup or `./dev/setup.sh` fails, follow the steps in [GETTING-STARTED.md](GETTING-STARTED.md) §3 (Manual Setup).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `libvirt: QEMU driver not found` | `sudo systemctl start libvirtd` |
| `KVM not available` | Check nested virt: `cat /sys/module/kvm_intel/parameters/nested` — must be `Y` |
| `/dev/kvm` permission denied | `sudo usermod -aG kvm $USER` then log out and back in |
| `cgroup v2 not writable` | Verify `Delegate=yes` in systemd unit; check `mount \| grep cgroup2` |
| `dnsmasq` port conflict | `sudo systemctl disable dnsmasq` (system dnsmasq) |
| Go not found | Add to PATH: `export PATH=/usr/lib/go-1.22/bin:$PATH` |
| `pip` not installed | `sudo apt-get install python3-pip` then re-run `./dev/setup.sh` |
