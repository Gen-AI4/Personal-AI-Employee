# Personal AI Employee - Bronze Tier

**Tier Declaration: Bronze**

Local-first, agent-driven personal automation powered by Claude Code and Obsidian. Your life and business on autopilot.

## Overview

This project implements the Bronze tier of the Personal AI Employee hackathon — a Digital FTE (Full-Time Equivalent) that uses an Obsidian vault as its knowledge base and Claude Code as its reasoning engine. It monitors a local file drop folder, triages incoming files with priority classification, and maintains a real-time dashboard.

### Bronze Tier Features

- **Obsidian Vault** with `Dashboard.md`, `Company_Handbook.md`, and `Business_Goals.md`
- **File System Watcher** — monitors the `/Inbox` folder for new file drops using watchdog
- **Claude Code Integration** — reads from and writes to the vault via Agent Skills
- **Vault Folder Structure** — `/Inbox`, `/Needs_Action`, `/Done`, `/Plans`, `/Logs`, `/Pending_Approval`, `/Approved`, `/Rejected`
- **Agent Skills** — `process-inbox`, `update-dashboard`, `vault-manager` (all AI functionality as Skills)
- **Orchestrator** — coordinates watchers, processes approved items, updates the dashboard
- **Structured Logging** — JSON action logs in `/Logs` for full audit trail

## Architecture

```
PERCEPTION LAYER          OBSIDIAN VAULT              REASONING LAYER
+-----------------+       +--------------------+      +------------------+
| FileSystem      | ----> | /Inbox             |      |                  |
| Watcher         |       | /Needs_Action      | <--> | Claude Code      |
| (watchdog)      |       | /Done              |      | (Agent Skills)   |
+-----------------+       | /Plans             |      +------------------+
                          | /Logs              |
                          | /Pending_Approval  |      ACTION LAYER
                          | /Approved          |      +------------------+
                          | /Rejected          |      | Orchestrator     |
                          | Dashboard.md       | <--> | (process cycles) |
                          | Company_Handbook.md|      +------------------+
                          +--------------------+
```

**Flow:** File dropped in `/Inbox` -> Watcher detects & creates action file in `/Needs_Action` -> Claude Code processes via Skills -> Result moved to `/Done` -> Dashboard updated.

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.13+ |
| UV | Latest (package manager) |
| Claude Code | Active subscription |
| Obsidian | v1.10.6+ (optional, for viewing vault) |

## Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd Personal-AI-Employee
   ```

2. **Install dependencies with UV**
   ```bash
   uv sync --all-extras
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run the orchestrator**
   ```bash
   uv run python src/orchestrator.py
   ```

5. **Drop files into `vault/Inbox/`** — the watcher will automatically detect them, classify priority, and create action files in `/Needs_Action`.

6. **Use Claude Code with Agent Skills** — run Claude Code from the project root. The skills `process-inbox`, `update-dashboard`, and `vault-manager` are available.

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `./vault` | Path to the Obsidian vault |
| `WATCH_FOLDER` | `./vault/Inbox` | Folder to monitor for file drops |
| `CHECK_INTERVAL` | `10` | Seconds between polling checks |
| `DEV_MODE` | `true` | Prevents real external actions |
| `DRY_RUN` | `true` | Logs intended actions without executing |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Project Structure

```
Personal-AI-Employee/
├── .claude/skills/              # Claude Code Agent Skills
│   ├── browsing-with-playwright/  # Pre-configured Playwright MCP
│   ├── process-inbox/             # Process /Needs_Action items
│   ├── update-dashboard/          # Refresh Dashboard.md
│   └── vault-manager/             # Vault maintenance operations
├── src/
│   ├── watchers/
│   │   ├── base_watcher.py        # Abstract base class for all watchers
│   │   └── filesystem_watcher.py  # File drop watcher (watchdog)
│   └── orchestrator.py            # Master process coordinator
├── tests/
│   ├── test_base_watcher.py       # 12 tests
│   ├── test_filesystem_watcher.py # 26 tests
│   └── test_orchestrator.py       # 26 tests
├── vault/                         # Obsidian vault (knowledge base)
│   ├── Inbox/                     # Drop folder (monitored)
│   ├── Needs_Action/              # Items awaiting processing
│   ├── Done/                      # Completed items archive
│   ├── Plans/                     # Action plans
│   ├── Logs/                      # JSON audit logs
│   ├── Pending_Approval/          # Items needing human approval
│   ├── Approved/                  # Human-approved actions
│   ├── Rejected/                  # Human-rejected actions
│   ├── Briefings/                 # Generated reports
│   ├── Accounting/                # Financial tracking
│   ├── Dashboard.md               # Real-time status dashboard
│   ├── Company_Handbook.md        # Rules of engagement
│   └── Business_Goals.md          # Business objectives
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Running Tests

```bash
uv run pytest tests/ -v
```

All 64 tests should pass, covering:
- **Unit tests**: BaseWatcher initialization, logging, run loop error handling
- **Unit tests**: FileSystemWatcher file detection, priority classification, action file creation
- **Unit tests**: Orchestrator pending/approved items, dashboard updates, cycle processing
- **Integration tests**: Full file-drop-to-done workflow, multi-file processing, orchestrator lifecycle

## Security Disclosure

- **Credentials**: No credentials are stored in the vault or committed to git. The `.env` file (containing any API keys or tokens) is in `.gitignore`.
- **Dev Mode**: `DEV_MODE=true` (default) prevents any real external actions.
- **Dry Run**: `DRY_RUN=true` (default) logs intended actions without executing.
- **Audit Trail**: All watcher and orchestrator actions are logged as structured JSON in `vault/Logs/`.
- **HITL Pattern**: Sensitive actions create approval requests in `/Pending_Approval` — the system will not act until a human moves the file to `/Approved`.
- **No external network calls**: The Bronze tier implementation is fully local — no API keys or external services required.

## Agent Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| `process-inbox` | Pending items in `/Needs_Action` | Reads handbook rules, processes items by priority, moves to `/Done` |
| `update-dashboard` | After processing or on schedule | Refreshes `Dashboard.md` with counts, recent activity, stats |
| `vault-manager` | Maintenance tasks | Verifies structure, cleans up, checks pending approvals, generates reports |
