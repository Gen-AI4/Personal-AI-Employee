# Personal AI Employee - Silver Tier

**Tier Declaration: Silver**

Local-first, agent-driven personal automation powered by Claude Code and Obsidian. Your life and business on autopilot.

## Overview

This project implements the Silver tier of the Personal AI Employee hackathon — a Digital FTE (Full-Time Equivalent) that uses an Obsidian vault as its knowledge base and Claude Code as its reasoning engine. It monitors multiple input channels (filesystem, Gmail, LinkedIn), creates structured action plans, manages human-in-the-loop approvals, and runs on a configurable schedule.

### Silver Tier Features (builds on Bronze)

- **Obsidian Vault** with `Dashboard.md`, `Company_Handbook.md`, and `Business_Goals.md`
- **Three Watchers** — FileSystem (watchdog), Gmail API, LinkedIn (Playwright MCP)
- **Claude Reasoning Loop** — Planner reads `/Needs_Action` items and creates structured `Plan.md` files with step-by-step checkboxes
- **Human-in-the-Loop Approval** — sensitive actions require human sign-off via `/Pending_Approval` → `/Approved` or `/Rejected`
- **Scheduler** — lightweight cron-like system with periodic and daily task modes, plus cron/Windows Task Scheduler config generation
- **MCP Server Integration** — Playwright browser automation for LinkedIn posting and monitoring
- **Seven Agent Skills** — `process-inbox`, `update-dashboard`, `vault-manager`, `create-plan`, `manage-approvals`, `send-email`, `post-linkedin`
- **Orchestrator** — coordinates all watchers, planner, approvals, scheduler, and dashboard updates

## Architecture

```
PERCEPTION LAYER          OBSIDIAN VAULT              REASONING LAYER
+-----------------+       +--------------------+      +------------------+
| FileSystem      | ----> | /Inbox             |      |                  |
| Watcher         |       | /Needs_Action      | <--> | Claude Code      |
| (watchdog)      |       | /Done              |      | (Agent Skills)   |
+-----------------+       | /Plans             |      |                  |
| Gmail Watcher   | ----> | /Logs              |      | Planner          |
| (Gmail API)     |       | /Pending_Approval  |      | (Plan.md gen)    |
+-----------------+       | /Approved          |      +------------------+
| LinkedIn        | ----> | /Rejected          |
| Watcher         |       | Dashboard.md       |      ACTION LAYER
| (Playwright MCP)|       | Company_Handbook.md|      +------------------+
+-----------------+       +--------------------+      | Orchestrator     |
                                                      | Scheduler        |
          APPROVAL LAYER                              | Approval Manager |
          +-----------------+                         +------------------+
          | /Pending_Approval|
          | /Approved (HITL) |
          | /Rejected        |
          +-----------------+
```

**Flow:** Input detected by Watcher → Action file in `/Needs_Action` → Planner creates `Plan.md` in `/Plans` → Sensitive actions go to `/Pending_Approval` → Human approves/rejects → Approved items processed → Moved to `/Done` → Dashboard updated.

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.13+ |
| UV | Latest (package manager) |
| Claude Code | Active subscription |
| Obsidian | v1.10.6+ (optional, for viewing vault) |
| Gmail API | OAuth2 credentials (optional, for email watcher) |
| Playwright MCP | Running server (optional, for LinkedIn) |

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

6. **Use Claude Code with Agent Skills** — run Claude Code from the project root. All seven skills are available.

### Optional: Gmail Watcher Setup

1. Create OAuth2 credentials at [Google Cloud Console](https://console.cloud.google.com/)
2. Download `credentials.json` to the project root
3. Set `ENABLE_GMAIL=true` in `.env`
4. On first run, complete the OAuth2 flow in your browser
5. A `token.json` will be saved for future runs

### Optional: LinkedIn Watcher Setup

1. Start the Playwright MCP server:
   ```bash
   bash .claude/skills/browsing-with-playwright/scripts/start-server.sh
   ```
2. Log into LinkedIn in the Playwright browser session
3. Set `ENABLE_LINKEDIN=true` in `.env`

### Optional: Scheduling

Generate cron entries or Windows Task Scheduler XML:
```bash
# Linux/macOS cron entries
uv run python -c "from scheduler import generate_cron_entries; print(generate_cron_entries())"

# Windows Task Scheduler XML
uv run python -c "from scheduler import generate_windows_task_xml; print(generate_windows_task_xml())"
```

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `./vault` | Path to the Obsidian vault |
| `WATCH_FOLDER` | `./vault/Inbox` | Folder to monitor for file drops |
| `CHECK_INTERVAL` | `10` | Seconds between polling checks |
| `DEV_MODE` | `true` | Prevents real external actions |
| `DRY_RUN` | `true` | Logs intended actions without executing |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `ENABLE_GMAIL` | `false` | Enable Gmail watcher (requires credentials) |
| `ENABLE_LINKEDIN` | `false` | Enable LinkedIn watcher (requires MCP server) |
| `GMAIL_CREDENTIALS` | `credentials.json` | Path to Gmail OAuth2 credentials |
| `GMAIL_TOKEN` | `token.json` | Path to saved Gmail auth token |
| `GMAIL_QUERY` | `is:unread is:important` | Gmail search query filter |
| `LINKEDIN_SESSION_PATH` | (none) | Playwright persistent browser session path |
| `MCP_CLIENT_PATH` | `.claude/skills/.../mcp-client.py` | Path to MCP client script |
| `MCP_SERVER_URL` | `http://localhost:8808` | Playwright MCP server URL |

## Project Structure

```
Personal-AI-Employee/
├── .claude/skills/                  # Claude Code Agent Skills
│   ├── browsing-with-playwright/      # Pre-configured Playwright MCP
│   ├── process-inbox/                 # Process /Needs_Action items
│   ├── update-dashboard/             # Refresh Dashboard.md
│   ├── vault-manager/                # Vault maintenance operations
│   ├── create-plan/                  # Generate Plan.md files
│   ├── manage-approvals/             # HITL approval workflow
│   ├── send-email/                   # Gmail sending with approval
│   └── post-linkedin/               # LinkedIn posting with approval
├── src/
│   ├── watchers/
│   │   ├── base_watcher.py            # Abstract base class for all watchers
│   │   ├── filesystem_watcher.py      # File drop watcher (watchdog)
│   │   ├── gmail_watcher.py           # Gmail API watcher
│   │   └── linkedin_watcher.py        # LinkedIn watcher (Playwright MCP)
│   ├── orchestrator.py                # Master process coordinator
│   ├── approval.py                    # HITL approval workflow manager
│   ├── planner.py                     # Plan.md generation engine
│   └── scheduler.py                   # Cron-like task scheduler
├── tests/
│   ├── test_base_watcher.py           # 12 tests
│   ├── test_filesystem_watcher.py     # 39 tests
│   ├── test_orchestrator.py           # 26 tests (Bronze regression)
│   ├── test_orchestrator_silver.py    # 30 tests (Silver features)
│   ├── test_approval.py              # 41 tests
│   ├── test_planner.py               # 52 tests
│   ├── test_scheduler.py             # 42 tests
│   ├── test_gmail_watcher.py         # 40 tests
│   └── test_linkedin_watcher.py      # 34 tests
├── vault/                             # Obsidian vault (knowledge base)
│   ├── Inbox/                         # Drop folder (monitored)
│   ├── Needs_Action/                  # Items awaiting processing
│   ├── Done/                          # Completed items archive
│   ├── Plans/                         # Generated action plans
│   ├── Logs/                          # JSON audit logs
│   ├── Pending_Approval/              # Items needing human approval
│   ├── Approved/                      # Human-approved actions
│   ├── Rejected/                      # Human-rejected actions
│   ├── Briefings/                     # Generated reports
│   ├── Accounting/                    # Financial tracking
│   ├── Dashboard.md                   # Real-time status dashboard
│   ├── Company_Handbook.md            # Rules of engagement
│   └── Business_Goals.md             # Business objectives
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Running Tests

```bash
uv run pytest tests/ -v
```

All 316 tests should pass, covering:
- **Regression**: All 77 Bronze tests pass unchanged
- **Approval**: Request creation, decision processing, expiry, full lifecycle
- **Planner**: Frontmatter parsing, template selection, plan generation, batch processing
- **Scheduler**: Periodic/daily tasks, run loop, status reporting, cron/Windows config generation
- **Gmail Watcher**: Priority classification, API mocking, action file creation, deduplication
- **LinkedIn Watcher**: Notification parsing, MCP integration, classification, action files
- **Silver Orchestrator**: Multi-watcher management, Silver components, dashboard, backward compatibility

## Security Disclosure

- **Credentials**: No credentials are stored in the vault or committed to git. The `.env` file (containing any API keys or tokens) is in `.gitignore`.
- **Dev Mode**: `DEV_MODE=true` (default) prevents any real external actions.
- **Dry Run**: `DRY_RUN=true` (default) logs intended actions without executing.
- **Audit Trail**: All watcher and orchestrator actions are logged as structured JSON in `vault/Logs/`.
- **HITL Pattern**: Sensitive actions (payments, emails, social posts, API calls) create approval requests in `/Pending_Approval` — the system will not act until a human moves the file to `/Approved`.
- **Path Traversal Prevention**: File names are sanitized to block `../` and other traversal attacks.
- **YAML Injection Prevention**: User-supplied strings are escaped before embedding in YAML frontmatter.
- **Thread Safety**: All log file writes protected by `threading.Lock`.
- **Graceful Degradation**: Gmail and LinkedIn watchers are optional — the system works without them.

## Agent Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| `process-inbox` | Pending items in `/Needs_Action` | Reads handbook rules, processes items by priority, moves to `/Done` |
| `update-dashboard` | After processing or on schedule | Refreshes `Dashboard.md` with counts, recent activity, stats |
| `vault-manager` | Maintenance tasks | Verifies structure, cleans up, checks pending approvals, generates reports |
| `create-plan` | New items in `/Needs_Action` | Creates structured Plan.md with steps, checkboxes, and approval flags |
| `manage-approvals` | Pending approval requests | Reviews, approves/rejects, processes decisions, checks expiry |
| `send-email` | Email action required | Drafts email, creates approval request, sends via Gmail API after approval |
| `post-linkedin` | Scheduled or on demand | Drafts LinkedIn post, creates approval request, publishes via Playwright |

## Approval Workflow

Actions that **always require human approval**:
- `payment`, `email_send`, `linkedin_post`, `social_post`
- `file_delete`, `external_api_call`, `new_contact_email`

Actions that are **auto-approved**:
- `file_organize`, `log_create`, `dashboard_update`, `plan_create`

**How to approve/reject**: Move the file from `vault/Pending_Approval/` to either `vault/Approved/` or `vault/Rejected/`. The orchestrator will process the decision on its next cycle.
