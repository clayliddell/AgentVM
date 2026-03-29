# AgentVM Code Standard

## 1. Language & Toolchain

### 1.1 Python (Daemon, CLI, Tests)

| Tool | Version | Purpose |
|------|---------|---------|
| Python | >=3.12 | Runtime |
| ruff | >=0.4 | Linting + formatting (replaces flake8, isort, black) |
| mypy | >=1.10 | Static type checking |
| pytest | >=8.0 | Unit test framework |
| pytest-cov | >=5.0 | Coverage reporting |
| mutmut | >=2.4 | Mutation testing |
| structlog | >=24.0 | Structured logging |
| pyyaml | >=6.0 | Config parsing |

### 1.2 Go (Auth Proxy)

| Tool | Version | Purpose |
|------|---------|---------|
| Go | >=1.22 | Runtime |
| golangci-lint | >=1.57 | Linting (all enabled linters) |
| go test | built-in | Unit + integration tests |
| gosec | latest | Security scanning |

### 1.3 System Dependencies

| Tool | Version | Purpose |
|------|---------|---------|
| libvirt | >=9.0 | VM management |
| QEMU | >=6.0 | Hypervisor |
| dnsmasq | >=2.89 | DNS filtering |
| iptables / nftables | system | Firewall |
| cgroup v2 | kernel >=5.2 | Resource enforcement |
| Go toolchain | >=1.22 | Auth proxy build |

## 2. Linting & Formatting

### 2.1 Python

```bash
# Run lint + format check
ruff check src/
ruff format --check src/

# Auto-fix
ruff check --fix src/
ruff format src/

# Type checking
mypy src/ --strict
```

**ruff rules:**
- `E` — pycodestyle errors
- `F` — pyflakes
- `I` — isort
- `N` — pep8-naming
- `UP` — pyupgrade
- `B` — flake8-bugbear
- `S` — flake8-bandit (security)
- `T20` — flake8-print (no print statements in production code)
- `SIM` — flake8-simplify

**mypy config:**
- `strict = true`
- `disallow_untyped_defs = true`
- `disallow_any_generics = true`
- `warn_return_any = true`
- `warn_unused_configs = true`

### 2.2 Go

```bash
golangci-lint run ./...
```

**Required linters:** `errcheck`, `govet`, `staticcheck`, `gosec`, `ineffassign`, `unused`, `gosimple`, `typecheck`, `gocritic`, `revive`.

## 3. Testing Requirements

### 3.1 Coverage Targets

| Test Type | Coverage Target | Tool | Enforcement |
|-----------|----------------|------|-------------|
| Unit Test | >=95% line coverage | pytest-cov | CI gate — PR blocked below threshold |
| Mutation Test | >=90% mutation score | mutmut | CI gate — PR blocked below threshold |
| Integration Test | 100% of cross-component contracts | pytest | CI gate |
| E2E Test | 100% of user-facing workflows | pytest | CI gate |

### 3.2 Test Categories

**Unit Tests** (`tests/unit/`):
- Test individual functions/methods in isolation.
- All external dependencies must be mocked (libvirt, filesystem, network, subprocess).
- Naming: `test_<module>_<method>_<scenario>_<expected>`.
- Run: `pytest tests/unit/ --cov=src/ --cov-report=term-missing`

**Mutation Tests** (`tests/unit/`):
- Run on all unit-tested code.
- Target: 90% mutation score (killed / (killed + survived)).
- Run: `mutmut run --paths-to-mutate=src/`
- Surviving mutants must be documented as intentional or fixed.

**Integration Tests** (`tests/integration/`):
- Test cross-component interactions.
- Use real subsystems where feasible (in-memory SQLite, mocked libvirt).
- Every LLD contract boundary must have at least one integration test.
- Run: `pytest tests/integration/ -m integration`

**E2E Tests** (`tests/e2e/`):
- Test full user workflows: session create → SSH → network policy → destroy.
- Require a real VM host (run in CI with nested KVM or in staging).
- Run: `pytest tests/e2e/ -m e2e`

### 3.3 Test Naming Convention

```python
def test_create_session_when_capacity_exceeded_raises_capacity_error():
    ...
```

Pattern: `test_<action>_<condition>_<expected_result>`

## 4. Test-Driven Development (TDD)

**All agents MUST follow TDD.** No production code may be written without a failing test first.

### 4.1 TDD Cycle

1. **RED** — Write a failing test that defines the desired behavior.
2. **GREEN** — Write the minimum code to make the test pass.
3. **REFACTOR** — Clean up code while keeping tests green.

### 4.2 Enforcement

- PRs that add production code without corresponding tests will be rejected.
- Every PR must pass `pytest --cov` at >=95% and `mutmut run` at >=90% before merge.
- CI pipeline runs: lint → typecheck → unit tests → coverage check → mutation tests → integration tests → E2E tests. Fail-fast on any step.

### 4.3 Exceptions

- Prototyping is allowed on feature branches but must be rewritten with TDD before merge.
- Configuration files and documentation are exempt.

## 5. API & Contract Compliance

### 5.1 LLD Alignment

Every function MUST reference its LLD section in the docstring:

```python
def create_session(self, request: SessionCreateRequest) -> WorkloadSession:
    """Create a new session with all resources.

    Ref: SESSION-MANAGER-LLD §5.3
    """
```

### 5.2 Contract Testing

- Every component boundary must have a contract test that validates input/output types match the LLD schema.
- Use `pytest` fixtures that represent the exact data shapes defined in LLDs.
- Run: `pytest tests/integration/ -k "contract"`

### 5.3 Schema Validation

- REST API request/response bodies must be validated against Pydantic models that match the LLD schemas.
- Any schema change requires updating both the LLD and the Pydantic model in the same PR.

## 6. Dependency & Security

### 6.1 Dependency Scanning

```bash
# Python
pip-audit

# Go
govulncheck ./...
```

Run in CI. Any `CRITICAL` or `HIGH` vulnerability blocks merge.

### 6.2 Secrets Scanning

```bash
detect-secrets scan > .secrets.baseline
detect-secrets audit .secrets.baseline
```

- Run `detect-secrets` on every commit (pre-commit hook).
- No API keys, passwords, or tokens in source code, config files, or logs.
- Secrets must be passed via environment variables or a secrets manager.

### 6.3 SBOM Generation

Generate Software Bill of Materials on every release:

```bash
# Python
pip-licenses --format=json --output-file=sbom-python.json

# Go
go-licenses csv ./... > sbom-go.csv
```

## 7. Documentation Compliance

### 7.1 Docstrings

- Every public function/class/method must have a Google-style docstring.
- Must include a `Ref:` line pointing to the LLD section.
- Parameter types and return types must be documented.

### 7.2 Architecture Decision Records (ADRs)

Any deviation from HLD/LLD requires an ADR in `docs/adr/`:

```
docs/adr/NNNN-short-title.md
```

Format:
- **Title**
- **Status:** Proposed | Accepted | Rejected | Superseded
- **Context:** Why the change is needed
- **Decision:** What was decided
- **Consequences:** Impact on architecture, other components

### 7.3 README per Component

Each `src/<component>/` directory must have a `README.md` with:
- Component purpose (1 paragraph)
- Public API summary
- LLD reference link
- Usage examples

## 8. Performance & Reliability

### 8.1 Latency Budgets

| Operation | Budget | Source |
|-----------|--------|--------|
| Session create | <30s | HLD §5 |
| Session destroy | <15s | HLD §5 |
| Network allow/block | <5s | HLD §6 |
| Health check | <500ms | HLD §7 |
| API request (non-VM) | <200ms | HLD §8 |

- All operations must emit timing metrics.
- Exceeding budget triggers a warning log and metric alert.

### 8.2 Load Testing

Before each release:
- Concurrent session creation: 10 sessions simultaneously
- Rapid create/destroy cycles: 100 cycles in 10 minutes
- Network policy changes under load: 50 domain allow/block operations while sessions are active

### 8.3 Chaos Testing

- Simulate daemon crash mid-operation (kill -9 during session create).
- Verify `reconcile_allocations()` recovers orphaned resources on restart.
- Verify no resource leaks (iptables rules, ipsets, cgroup scopes, disk files).

## 9. Audit & Traceability

### 9.1 Audit Event Coverage

Every mutation to session state MUST emit an audit event. This is enforced by:
- Unit test that enumerates all state transitions and verifies event emission.
- Integration test that verifies audit log contains expected events after a workflow.

### 9.2 Audit Event Types

All events listed in OBSERVABILITY-LLD §5.1 must have corresponding test coverage. Missing events are a merge blocker.

### 9.3 LLD-to-Code Traceability

- Every production file must have a module-level docstring referencing its LLD.
- Every public method must reference its LLD section.
- CI script verifies that all LLD-referenced functions exist and all implemented functions have LLD references.

## 10. CI/CD Pipeline

### 10.1 Pipeline Stages

```
1. Lint          → ruff check, ruff format --check, golangci-lint
2. Typecheck     → mypy --strict
3. Unit Tests    → pytest tests/unit/ --cov-fail-under=95
4. Mutation      → mutmut run --test-timeout=300
5. Security      → pip-audit, govulncheck, detect-secrets
6. Integration   → pytest tests/integration/ -m integration
7. E2E           → pytest tests/e2e/ -m e2e (staging only)
8. SBOM          → generate and attach to release
```

### 10.2 Fail-Fast

Any stage failure stops the pipeline. No merge until all required stages pass.

### 10.3 Pre-Commit Hooks

Install with: `pre-commit install`

Hooks:
- `ruff check --fix`
- `ruff format`
- `detect-secrets scan`
- `mypy --strict` (on changed files only)

## 11. Version Pinning

- All Python dependencies must be pinned to exact versions in `requirements.txt` or `pyproject.toml`.
- Go dependencies pinned via `go.mod` and `go.sum`.
- System dependency versions documented in `AGENTS.md` and verified in CI.
- Dependency updates require a PR with changelog review.
