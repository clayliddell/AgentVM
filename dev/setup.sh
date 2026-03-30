#!/usr/bin/env bash
#
# setup.sh — Bootstrap the AgentVM development environment.
#
# Run from the repository root:
#   ./dev/setup.sh              # full setup (system packages + Python + Go + storage)
#   ./dev/setup.sh --dev-only   # lightweight: Python venv + pre-commit only
#
# Safe to re-run; all steps are idempotent.
#
set -euo pipefail

# Resolve repo root (parent of this script's directory)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
VENV_DIR="${REPO_ROOT}/.venv"
PROXY_DIR="${REPO_ROOT}/proxy"

DEV_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --dev-only) DEV_ONLY=true ;;
        *) ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; }

need_sudo() {
    if [[ $EUID -eq 0 ]]; then
        echo ""
    else
        echo "sudo"
    fi
}

SUDO="$(need_sudo)"

is_container() {
    # Detect Docker, LXC, or other container runtimes
    [[ -f /.dockerenv ]] && return 0
    [[ -f /run/.containerenv ]] && return 0
    grep -qE '(docker|lxc|container)' /proc/1/cgroup 2>/dev/null && return 0
    return 1
}

SKIP_HOST=false
if is_container; then
    SKIP_HOST=true
    log "Container environment detected — skipping KVM/libvirt/system package steps."
fi

# ── 1. System packages ───────────────────────────────────────────────────────

install_system_packages() {
    if $SKIP_HOST || $DEV_ONLY; then
        log "Skipping system packages (container or --dev-only mode)."
        return 0
    fi
    log "Installing system packages (requires sudo)..."
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq \
        qemu-kvm libvirt-daemon-system libvirt-clients libvirt-dev \
        dnsmasq iptables cgroup-tools pkg-config \
        python3.12 python3.12-venv python3-pip \
        golang-1.22 \
        git make \
        genisoimage \
        > /dev/null 2>&1 || $SUDO apt-get install -y -qq \
        qemu-kvm libvirt-daemon-system libvirt-clients libvirt-dev \
        dnsmasq iptables cgroup-tools pkg-config \
        python3.12 python3.12-venv python3-pip \
        golang-1.22 \
        git make \
        genisoimage
    log "System packages installed."
}

# ── 2. Verify KVM / nested virt ─────────────────────────────────────────────

verify_kvm() {
    if $SKIP_HOST || $DEV_ONLY; then
        log "Skipping KVM verification (container or --dev-only mode)."
        return 0
    fi
    log "Verifying KVM support..."
    if [[ ! -e /dev/kvm ]]; then
        err "/dev/kvm not found. Nested virtualization may not be enabled."
        err "Check: cat /sys/module/kvm_intel/parameters/nested"
        exit 1
    fi
    local nested
    nested=$(cat /sys/module/kvm_intel/parameters/nested 2>/dev/null \
          || cat /sys/module/kvm_amd/parameters/nested 2>/dev/null \
          || echo "N/A")
    log "Nested KVM: ${nested}"
    log "KVM OK."
}

# ── 3. libvirtd ──────────────────────────────────────────────────────────────

setup_libvirtd() {
    if $SKIP_HOST || $DEV_ONLY; then
        log "Skipping libvirtd setup (container or --dev-only mode)."
        return 0
    fi
    log "Starting libvirtd..."
    $SUDO systemctl enable --now libvirtd 2>/dev/null || true
    # Ensure the default network is active (needed for some libvirt setups)
    $SUDO virsh net-start default 2>/dev/null || true
    $SUDO virsh net-autostart default 2>/dev/null || true
    # Add current user to libvirt and kvm groups
    $SUDO usermod -aG libvirt "$(whoami)" 2>/dev/null || true
    $SUDO usermod -aG kvm "$(whoami)" 2>/dev/null || true
    log "libvirtd ready."
}

# ── 4. Python virtual environment ────────────────────────────────────────────

setup_python_venv() {
    log "Setting up Python 3.12 virtualenv at ${VENV_DIR}..."
    if [[ ! -d "${VENV_DIR}" ]]; then
        python3.12 -m venv "${VENV_DIR}" 2>/dev/null \
            || python3 -m venv "${VENV_DIR}"
    fi
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    pip install --upgrade pip -q

    # Install dev dependencies if requirements-dev.txt exists
    if [[ -f "${REPO_ROOT}/requirements-dev.txt" ]]; then
        log "Installing Python dev dependencies..."
        pip install -r "${REPO_ROOT}/requirements-dev.txt" -q
        pip install -q types-PyYAML  # Required for mypy strict type checking
    else
        warn "requirements-dev.txt not found — installing core dev tools directly."
        pip install -q \
            ruff \
            mypy \
            pytest \
            pytest-cov \
            mutmut \
            structlog \
            pyyaml \
            pre-commit \
            click \
            fastapi \
            uvicorn \
            libvirt-python \
            pip-audit \
            detect-secrets
    fi
    log "Python venv ready."
}

# ── 5. Go toolchain ─────────────────────────────────────────────────────────

setup_go() {
    if $DEV_ONLY; then
        log "Skipping Go toolchain (--dev-only mode)."
        return 0
    fi
    log "Verifying Go toolchain..."
    export PATH="/usr/lib/go-1.22/bin:${PATH}"
    if ! command -v go &>/dev/null; then
        warn "Go not found on PATH. Trying /usr/lib/go-1.22/bin/go..."
        if [[ -x /usr/lib/go-1.22/bin/go ]]; then
            export PATH="/usr/lib/go-1.22/bin:${PATH}"
        else
            warn "Go toolchain not available — proxy build will be skipped."
            return 0
        fi
    fi
    log "Go version: $(go version)"

    # Build auth proxy if Makefile exists
    if [[ -f "${PROXY_DIR}/Makefile" ]]; then
        log "Building Go auth proxy..."
        make -C "${PROXY_DIR}" build 2>/dev/null || make -C "${PROXY_DIR}" 2>/dev/null || warn "Proxy build skipped (Makefile may not be ready yet)."
    else
        warn "proxy/Makefile not found — skipping proxy build."
    fi
}

# ── 6. Pre-commit hooks ─────────────────────────────────────────────────────

setup_precommit() {
    log "Installing pre-commit hooks..."
    if command -v pre-commit &>/dev/null || [[ -x "${VENV_DIR}/bin/pre-commit" ]]; then
        (
            # shellcheck disable=SC1091
            source "${VENV_DIR}/bin/activate"
            pre-commit install 2>/dev/null || warn "pre-commit install skipped (no .pre-commit-config.yaml yet)."
        )
    else
        warn "pre-commit not found — skipping hook installation."
    fi
}

# ── 7. Storage directories ──────────────────────────────────────────────────

setup_storage_dirs() {
    if $SKIP_HOST || $DEV_ONLY; then
        log "Skipping storage directory creation (container or --dev-only mode)."
        return 0
    fi
    log "Creating storage directory tree..."
    local base="/var/lib/agentvm"
    for sub in base vms shared proxy keys logs; do
        $SUDO mkdir -p "${base}/${sub}"
    done
    $SUDO chown -R "$(whoami):$(whoami)" "${base}" 2>/dev/null || true
    chmod 0755 "${base}" "${base}"/  2>/dev/null || true
    log "Storage tree at ${base} ready."
}

# ── 8. Write .env marker ────────────────────────────────────────────────────

write_env_marker() {
    log "Writing .env marker..."
    cat > "${ENV_FILE}" <<'EOF'
# Track whether the dev environment has been set up by a prior session.
# After running setup.sh, this is set to "true".
# Source this file before working: source .env
AGENTVM_ENV_SETUP_DONE=true

# Make Go 1.22 available on PATH
export PATH="/usr/lib/go-1.22/bin:${PATH}"
EOF
    log ".env updated — AGENTVM_ENV_SETUP_DONE=true"
}

# ── 9. Verify tools ─────────────────────────────────────────────────────────

verify_tools() {
    log "Verifying installed tools..."
    local all_ok=true

    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    for tool in ruff mypy pytest pre-commit pip-audit detect-secrets mutmut; do
        if command -v "$tool" &>/dev/null; then
            log "  $tool: OK"
        else
            err "  $tool: NOT FOUND"
            all_ok=false
        fi
    done

    if $all_ok; then
        log "All dev tools verified."
    else
        err "Some tools are missing. Try: pip install -r requirements-dev.txt"
        exit 1
    fi
}

# ── 10. Summary ──────────────────────────────────────────────────────────────

summary() {
    echo ""
    log "════════════════════════════════════════════════════════════"
    log "  AgentVM dev environment setup complete."
    log "════════════════════════════════════════════════════════════"
    echo ""
    log "Next steps:"
    log "  1. source .venv/bin/activate"
    log "  2. source .env          # loads AGENTVM_ENV_SETUP_DONE"
    if ! $DEV_ONLY && ! $SKIP_HOST; then
        log "  3. Verify libvirt: python -c \"import libvirt; print('libvirt OK')\""
        log "  4. Read dev/CODE-STANDARD.md and dev/todo/todo.md to start work."
    else
        log "  3. Run tests: pytest tests/unit/ -v"
        log "  4. Read dev/CODE-STANDARD.md and dev/todo/todo.md to start work."
    fi
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    log "Starting AgentVM dev environment setup..."
    log "Repo root: ${REPO_ROOT}"
    if $DEV_ONLY; then
        log "Mode: dev-only (Python venv + pre-commit)"
    fi

    install_system_packages
    verify_kvm
    setup_libvirtd
    setup_python_venv
    setup_go
    setup_precommit
    setup_storage_dirs
    write_env_marker
    verify_tools
    summary
}

main "$@"
