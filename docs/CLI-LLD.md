# CLI — Low-Level Design

## Component Name: CLI

The CLI provides a command-line interface for managing sessions, VMs, network policy, proxies, shared folders, images, and host status. It communicates with the agentvm daemon via the REST API. Built with Click.

**Source file:** `src/agentvm/cli/main.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| CLI-FR-01 | Provide `session` subcommands: `create`, `destroy`, `list`, `status` | 7 |
| CLI-FR-02 | Provide `vm` subcommands: `create`, `destroy`, `list`, `status` (legacy) | 7 |
| CLI-FR-03 | Provide `network` subcommands: `allow`, `block`, `reset`, `list` | 7 |
| CLI-FR-04 | Provide `proxy` subcommands: `status`, `logs` | 7 |
| CLI-FR-05 | Provide `shared` subcommands: `info`, `sync` | 7 |
| CLI-FR-06 | Provide `ssh` command to get SSH command or open SSH session | 7 |
| CLI-FR-07 | Provide `logs` command to tail session logs | 7 |
| CLI-FR-08 | Provide `audit` command to show audit events | 7 |
| CLI-FR-09 | Provide `images` command to manage base images | 7 |
| CLI-FR-10 | Provide `host` command to show host health and capacity | 7 |
| CLI-FR-11 | Support `--format` flag: `table` (default), `json`, `yaml` | 7 |
| CLI-FR-12 | Support `--api-url` flag to override daemon endpoint (default `http://localhost:9090`) | 7 |
| CLI-FR-13 | Support `--api-key` flag for authentication | 7 |
| CLI-FR-14 | Support `--verbose` flag for detailed output | 7 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| CLI-NFR-01 | CLI must be a thin HTTP client — no business logic, all logic in daemon | Architecture |
| CLI-NFR-02 | Table output must be human-readable with aligned columns | UX |
| CLI-NFR-03 | All commands must produce parseable JSON output with `--format json` | Automation |
| CLI-NFR-04 | Unit test coverage ≥80% for argument parsing and output formatting | 12.1 |

---

## 3. Component API Contracts

### 3.1 CLI Command Map

```
agentvm
├── session
│   ├── create    (--name, --image, --cpu, --memory, --disk, --ssh-key, --network-policy, --api-key, --shared-folder)
│   ├── destroy   <session-id>
│   ├── list      [--owner]
│   └── status    <session-id>
├── vm
│   ├── create    (--name, --image, --cpu, --memory, --disk, --ssh-key)
│   ├── destroy   <vm-id>
│   ├── list
│   └── status    <vm-id>
├── network
│   ├── allow     <session-id> <domain> [--port]
│   ├── block     <session-id> <domain> [--port]
│   ├── reset     <session-id>
│   └── list      <session-id>
├── proxy
│   ├── status    <session-id>
│   └── logs      <session-id> [--follow] [--limit]
├── shared
│   ├── info      <session-id>
│   └── sync      <session-id>
├── ssh           <session-id>
├── logs          <session-id> [--follow]
├── audit         [--session <session-id>] [--last <n>]
├── images
│   ├── list
│   ├── upload    <name> <disk-path> [--metadata <json>]
│   └── delete    <name>
├── host
│   ├── health
│   └── capacity
└── capabilities
```

### 3.2 HTTP Client Interface

The CLI is a pure HTTP client. It calls the REST API endpoints:

| CLI Command | HTTP Method | Endpoint |
|---|---|---|
| `session create` | POST | `/api/v1/sessions` |
| `session destroy` | DELETE | `/api/v1/sessions/{sid}` |
| `session list` | GET | `/api/v1/sessions?owner=...` |
| `session status` | GET | `/api/v1/sessions/{sid}` |
| `network allow` | POST | `/api/v1/sessions/{sid}/network/allow` |
| `network block` | POST | `/api/v1/sessions/{sid}/network/block` |
| `network reset` | POST | `/api/v1/sessions/{sid}/network/reset` |
| `network list` | GET | `/api/v1/sessions/{sid}/network` |
| `proxy status` | GET | `/api/v1/sessions/{sid}/proxy` |
| `proxy logs` | GET | `/api/v1/sessions/{sid}/proxy/logs` |
| `ssh` | GET | `/api/v1/sessions/{sid}/ssh` |
| `logs` | GET | `/api/v1/sessions/{sid}/logs` |
| `audit` | GET | `/api/v1/sessions/{sid}/audit` |
| `images list` | GET | `/api/v1/images` |
| `images upload` | POST | `/api/v1/images` |
| `images delete` | DELETE | `/api/v1/images/{name}` |
| `host health` | GET | `/api/v1/health` |
| `host capacity` | GET | `/api/v1/capacity` |
| `capabilities` | GET | `/api/v1/capabilities` |

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **REST API** | All CLI operations are proxied through the API |

| Components That Call This | None — the CLI is a standalone entry point |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 3: API + CLI (Week 3-4)

**Phase Goal:** Full CLI with session management and runtime network control.

**User Stories & Tasks:**

* **Story:** As a developer, I have a Click CLI application with all subcommands.
  * **Task:** Implement `main.py` — Click group with global options (`--api-url`, `--api-key`, `--format`, `--verbose`). Create an HTTP client helper that wraps `httpx` or `requests` with auth header injection and error handling.
    * *Identified Blockers/Dependencies:* REST API must be running.

* **Story:** As a user, I can create/list/status/destroy sessions from the CLI.
  * **Task:** Implement `session` group with `create`, `destroy`, `list`, `status` commands.
    - `create`: Accept all options from HLD Section 7, build `SessionCreateRequest` JSON, POST to API, print response in selected format.
    - `destroy`: DELETE to API, print confirmation.
    - `list`: GET from API, print table with columns: ID, Name, Status, Image, CPU, Memory, Created.
    - `status`: GET from API, print detailed session info.
    * *Identified Blockers/Dependencies:* REST API session endpoints.

* **Story:** As a user, I can manage network policy from the CLI.
  * **Task:** Implement `network` group with `allow`, `block`, `reset`, `list` commands.
    - `allow <session-id> <domain> [--port]`: POST to API.
    - `block <session-id> <domain> [--port]`: POST to API.
    - `reset <session-id>`: POST to API.
    - `list <session-id>`: GET from API, print table with columns: Domain, IP, Port, Action, Source, Created.
    * *Identified Blockers/Dependencies:* REST API network endpoints.

* **Story:** As a user, I can view proxy status and logs.
  * **Task:** Implement `proxy` group with `status` and `logs` commands.
    - `status`: GET from API, print proxy config.
    - `logs`: GET from API, print log entries. Support `--follow` via polling or SSE.
    * *Identified Blockers/Dependencies:* REST API proxy endpoints.

* **Story:** As a user, I can SSH into a session's VM.
  * **Task:** Implement `ssh` command — GET SSH info from API, print the `ssh` command string, or optionally exec it directly via `os.execvp("ssh", ...)`.
    * *Identified Blockers/Dependencies:* REST API SSH endpoint.

* **Story:** As a user, I can view host health and capacity.
  * **Task:** Implement `host` group with `health` and `capacity` commands.
    * *Identified Blockers/Dependencies:* REST API health/capacity endpoints.

* **Story:** As a user, I can manage images and view capabilities.
  * **Task:** Implement `images` group and `capabilities` command.
    * *Identified Blockers/Dependencies:* REST API image/capabilities endpoints.

* **Story:** As a developer, I have unit tests for CLI argument parsing and output formatting.
  * **Task:** Implement `test_cli.py` — test each command with Click's `CliRunner`, mock HTTP responses, verify correct API calls and output formatting (table, JSON).
    * *Identified Blockers/Dependencies:* None.

---

## 5. Output Formats

### Table Format (Default)

```
$ agentvm session list
ID              Name                Status    Image                 CPU   Memory   Created
sess-a1b2c3d4   agent-research-bot  running   ubuntu-24.04-amd64    4     8G       2026-03-28T14:30:00Z
sess-e5f67890   code-reviewer       creating  debian-12-amd64       2     4G       2026-03-28T14:31:00Z
```

### JSON Format

```json
$ agentvm session list --format json
[
  {
    "id": "sess-a1b2c3d4",
    "name": "agent-research-bot",
    "status": "running",
    ...
  }
]
```

---

## 6. Error Handling

| Error Condition | Handling |
|---|---|
| Daemon not reachable | Print error with daemon URL, suggest `systemctl start agentvm` |
| Authentication failure | Print "Invalid API key" |
| Session not found | Print "Session {id} not found" |
| Invalid arguments | Click's built-in validation + custom error messages |
| API returns 500 | Print error detail, suggest checking daemon logs |
