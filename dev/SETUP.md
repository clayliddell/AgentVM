# AgentVM Development Environment Setup

This document explains how to bootstrap a development environment for AgentVM. The process is automated via `./dev/setup.sh`.

## Prerequisites

- **Python 3.12** (the only hard requirement for `--dev-only` mode)
- **OS:** Ubuntu 24.04 LTS (or compatible Debian-based distro) for full setup
- **Hardware:** CPU with virtualization support (Intel VT-x or AMD-V), nested KVM enabled — only for full setup
- **Access:** `sudo` privileges for installing system packages — only for full setup

## Quick Start

### Full setup (KVM host)

```bash
git clone <repo-url> agentvm
cd agentvm
./dev/setup.sh
source .venv/bin/activate
source .env
```

### Dev-only setup (containers, CI, non-KVM machines)

```bash
git clone <repo-url> agentvm
cd agentvm
./dev/setup.sh --dev-only
source .venv/bin/activate
source .env
```

This skips system packages, KVM verification, libvirtd, Go toolchain, and storage directories. It sets up only the Python venv and pre-commit hooks — sufficient for linting, type checking, and running unit/integration tests.

## What `setup.sh` Does

The script performs the following steps (all idempotent — safe to re-run):

| Step | Description | `--dev-only` |
|------|-------------|:------------:|
| 1. System packages | Installs `qemu-kvm`, `libvirt-daemon-system`, `dnsmasq`, `iptables`, `cgroup-tools`, `python3.12`, `python3.12-venv`, `golang-1.22`, `git`, `make`, `genisoimage` | skipped |
| 2. KVM verification | Checks `/dev/kvm` exists and nested virt is enabled | skipped |
| 3. libvirtd | Starts and enables `libvirtd`, adds user to `libvirt` and `kvm` groups | skipped |
| 4. Python venv | Creates `.venv/` with Python 3.12, installs dev dependencies from `requirements-dev.txt` (or falls back to inline install of ruff, mypy, pytest, etc.) | **runs** |
| 5. Go toolchain | Verifies Go 1.22, builds the auth proxy from `proxy/Makefile` | skipped |
| 6. Pre-commit hooks | Runs `pre-commit install` for linting and secrets scanning | **runs** |
| 7. Storage dirs | Creates `/var/lib/agentvm/` with subdirectories (`base/`, `vms/`, `shared/`, `proxy/`, `keys/`, `logs/`) | skipped |
| 8. Env marker | Sets `AGENTVM_ENV_SETUP_DONE=true` in `.env` | **runs** |
| 9. Tool verification | Checks that all dev tools are on PATH | **runs** |

## Container Environments

The setup script auto-detects Docker, LXC, and other container runtimes. When a container is detected, steps 1-3 and 7 are skipped automatically (same as `--dev-only`). You do not need to pass `--dev-only` explicitly in containers.

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
pre-commit --version
pip-audit --version
mutmut --version

# Run tests
pytest tests/unit/ -v

# Full check suite (same as CI pre-commit)
ruff check src/ && ruff format --check src/ && mypy src/ --strict && pytest tests/unit/ --cov-fail-under=95

# Only on a full KVM host:
go version
python -c "import libvirt; conn = libvirt.open('qemu:///system'); print('libvirt OK:', conn.getVersion())"
ls -la /dev/kvm
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
| `python3.12` not found | Use `--dev-only` or install: `sudo apt-get install python3.12 python3.12-venv` |
