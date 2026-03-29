# Getting Started

## Goal

AgentVM is a platform that provides isolated KVM-based virtual machine sessions for AI coding agents. Each session runs a full VM with network isolation, auth proxy for secure API key forwarding, shared folder access, and resource enforcement via cgroups. The platform exposes a REST API and CLI for session lifecycle management, and an orchestrator adapter for integration with workload orchestrators.

The ultimate goal: enable AI coding agents to operate in fully isolated, resource-bounded VMs with controlled network access, preventing key exfiltration and cross-tenant interference while maintaining developer-level productivity.

## Getting Started

### 1. First-Time Setup

Run the automated setup script from the repository root. It installs system packages, creates the Python venv, builds the Go proxy, and configures libvirtd. See [SETUP.md](SETUP.md) for full details.

```bash
git clone <repo-url> agentvm
cd agentvm
./dev/setup.sh
```

After setup completes, a `.env` file is created with `AGENTVM_ENV_SETUP_DONE=true`. This file is gitignored and signals to subsequent agent sessions that the environment is ready.

### 2. Every Session — Activate Environment

At the start of **every** working session (including AI agent sessions):

```bash
source .venv/bin/activate
source .env
```

Check `AGENTVM_ENV_SETUP_DONE` in `.env`:
- If `false` (or missing), run `./dev/setup.sh` first.
- If `true`, the environment is ready — proceed to development.

### 3. Manual Setup (Alternative)

If `setup.sh` is not available or you prefer manual steps:

```bash
# System packages (Ubuntu/Debian)
sudo apt-get install -y \
    qemu-kvm libvirt-daemon-system libvirt-clients libvirt-dev \
    dnsmasq iptables cgroup-tools pkg-config \
    python3.12 python3.12-venv python3-pip \
    golang-1.22 \
    git make genisoimage

# Verify nested KVM support
cat /sys/module/kvm_intel/parameters/nested  # or kvm_amd
# Should output: Y

# Verify /dev/kvm exists
ls -la /dev/kvm

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Build Go auth proxy
cd proxy && make && cd ..

# Verify libvirt connection
python -c "import libvirt; conn = libvirt.open('qemu:///system'); print(conn.getVersion())"
```

### 4. Project Structure

```
agentvm/
├── src/
│   ├── agentvm/
│   │   ├── session_manager/    # Session lifecycle orchestration
│   │   ├── vm_manager/         # libvirt VM create/destroy/status
│   │   ├── network_manager/    # Bridge, iptables, ipset, dnsmasq
│   │   ├── storage_manager/    # Disk overlays, cloud-init, images
│   │   ├── auth_proxy_manager/ # Proxy process lifecycle
│   │   ├── host_manager/       # CPU topology, capacity, cgroups
│   │   ├── metadata_store/     # SQLite persistence
│   │   ├── observability/      # Audit, metrics, health, logging
│   │   ├── orchestrator/       # IsolationBackend protocol
│   │   ├── config/             # YAML config loading
│   │   ├── api/                # FastAPI REST endpoints
│   │   └── cli/                # Click CLI commands
│   └── daemon.py               # Entrypoint — startup, wiring, shutdown
├── proxy/                      # Go auth proxy binary
│   ├── cmd/proxy/main.go
│   ├── internal/
│   └── Makefile
├── tests/
│   ├── unit/                   # 95% coverage target
│   ├── integration/            # Cross-component contract tests
│   └── e2e/                    # Full workflow tests
├── docs/
│   ├── designs/
│   │   ├── HLD.md              # High-Level Design
│   │   └── *-LLD.md            # Low-Level Designs per component
│   └── adr/                    # Architecture Decision Records
├── dev/
│   ├── CODE-STANDARD.md        # Code quality standards
│   ├── todo/
│   │   ├── todo.md             # Kanban guide
│   │   └── PHASE1..PHASE7.md   # Task boards per phase
│   ├── setup.sh                # Automated dev environment setup
│   ├── SETUP.md                # Setup documentation
│   └── GETTING-STARTED.md      # This file
├── .venv/                      # Python virtual environment (gitignored)
├── .env                        # Session env marker (gitignored)
└── README.md                   # Project overview
```

### 5. Running Tests

```bash
# All unit tests with coverage
pytest tests/unit/ --cov=src/ --cov-report=term-missing --cov-fail-under=95

# Integration tests (requires libvirt)
pytest tests/integration/ -m integration

# E2E tests (requires real VM host)
pytest tests/e2e/ -m e2e

# Mutation testing
mutmut run --paths-to-mutate=src/

# Linting
ruff check src/
ruff format --check src/
mypy src/ --strict
```

### 6. Development Workflow

Before starting, read [CODE-STANDARD.md](CODE-STANDARD.md), [todo.md](todo/todo.md), and the `todo/PHASE#.md` file corresponding to whichever phase your working on. Make sure you have sourced your environment:

```bash
source .venv/bin/activate
source .env
```

1. **Pick a task** from the current phase board in `dev/todo/PHASE<N>.md`.
2. **Update status** to `In Progress` in `main` branch (no need to push).
3. **Checkout a new Branch** - Checkout a new branch in git for tracking your progress. You'll later use this branch to create a PR for your work.
3. **Read the LLD** — every task references its LLD section. Read it before writing code.
4. **Write a failing test first** (TDD). See [CODE-STANDARD.md](CODE-STANDARD.md) §4.
5. **Implement the minimum** to make the test pass.
6. **Refactor** while keeping tests green.
7. **Run the full check suite:**
   ```bash
   ruff check src/ && ruff format --check src/ && mypy src/ --strict && pytest tests/unit/ --cov-fail-under=95
   ```
8. **Update task status** to `Ready for Review` in `main` branch (no need to push).
9. **Submit PR.** CI must pass all gates before merge.

### 7. Key Conventions

- **Docstrings:** Every public function must have a Google-style docstring with a `Ref:` line pointing to the LLD section.
- **Types:** All functions must have complete type annotations. `mypy --strict` is enforced.
- **No print statements:** Use `structlog` for all logging.
- **No hardcoded secrets:** Environment variables only.
- **Component isolation:** Components only interact through defined interfaces. No direct cross-component imports — use dependency injection via `daemon.py`.

### 8. Configuration

The daemon loads config from YAML. Default path: `/etc/agentvm/config.yaml`. Override with `AGENTVM_CONFIG` env var.

See `docs/designs/CONFIG-LLD.md` for schema. Key sections:
- `api` — listen address, API keys, TLS
- `network` — bridge name, CIDR, default policy mode
- `storage` — base path, image store
- `security` — VM max lifetime, resource defaults
- `logging` — level, format

### 9. Daemon

Start the daemon:

```bash
source .venv/bin/activate
python -m src.agentvm.daemon --config /etc/agentvm/config.yaml
```

Or via systemd:

```bash
sudo systemctl start agentvm
sudo journalctl -u agentvm -f
```

**Note:** The systemd unit must include `Delegate=yes` for cgroup v2 delegation. See [HOST-MANAGER-LLD](docs/designs/HOST-MANAGER-LLD.md) §5.1.

### 10. Common Tasks

```bash
# Create a session via CLI
agentvm session create --name my-session --image ubuntu-22.04 --cpu 2 --memory 4096

# List sessions
agentvm session list

# SSH into a session
agentvm ssh <session-id>

# Allow a domain in strict mode
agentvm network allow <session-id> api.openai.com

# View audit log
agentvm audit --session <session-id>

# View host capacity
agentvm host capacity
```

### 11. Troubleshooting

| Problem | Solution |
|---------|----------|
| `libvirt: QEMU driver not found` | Ensure `libvirtd` is running: `sudo systemctl start libvirtd` |
| `KVM not available` | Check nested virt: `cat /sys/module/kvm_intel/parameters/nested` |
| `Permission denied on /dev/kvm` | Add user to `kvm` group: `sudo usermod -aG kvm $USER` |
| `cgroup v2 not writable` | Verify `Delegate=yes` in systemd unit and cgroup v2 mount: `mount | grep cgroup2` |
| `dnsmasq port conflict` | Disable system dnsmasq: `sudo systemctl disable dnsmasq` |
| `Mutation score below 90%` | Run `mutmut results` and fix surviving mutants or document intentional ones |
| `AGENTVM_ENV_SETUP_DONE=false` | Run `./dev/setup.sh` then `source .env`. See [SETUP.md](SETUP.md). |

### 12. Where to Ask Questions

- Check the LLD for the relevant component first.
- Check `docs/designs/HLD.md` for architecture overview.
- If the LLD contradicts the HLD, the HLD is authoritative. File an ADR.
- For process questions, see `dev/todo/todo.md` for Kanban guidance.
