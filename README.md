# Personal AI Employee - Gold Tier

**Tier Declaration: Gold**

Local-first, agent-driven personal automation powered by Claude Code and Obsidian. Your life and business on autopilot.

## Overview

This project implements the Gold tier of the Personal AI Employee hackathon — a Digital FTE (Full-Time Equivalent) that uses an Obsidian vault as its knowledge base and Claude Code as its reasoning engine. It monitors multiple input channels (filesystem, Gmail, LinkedIn, Facebook, Instagram, Twitter), manages business accounting via Odoo, generates weekly CEO briefings, recovers from errors with exponential backoff, and autonomously completes multi-step tasks using the Ralph Wiggum loop pattern.

### Gold Tier Features (builds on Silver)

- **Full Cross-Domain Integration** — Personal (email, social) and Business (Odoo accounting) in one system
- **Facebook & Instagram Watchers** — Playwright MCP monitors notifications, messages, and friend/follow requests
- **Twitter (X) Watcher** — Monitors mentions, DMs, follows, and engagement
- **Odoo Accounting Integration** — JSON-RPC client for invoices, payments, and journal entries with mock data in DEV_MODE
- **Monday Morning CEO Briefing** — Weekly business audit: revenue, completed tasks, bottlenecks, and proactive suggestions
- **Error Recovery & Graceful Degradation** — `with_retry` decorator, `ErrorTracker` circuit breaker, error classification
- **Comprehensive Audit Logging** — All actions and errors tracked in structured JSON logs
- **Ralph Wiggum Loop** — Stop hook pattern for autonomous multi-step task completion
- **Six New Agent Skills** — `post-facebook`, `post-instagram`, `post-twitter`, `generate-briefing`, `odoo-accounting`, `ralph-loop`

### Silver Tier Features (included)

- **Obsidian Vault** with `Dashboard.md`, `Company_Handbook.md`, and `Business_Goals.md`
- **Three Watchers** — FileSystem (watchdog), Gmail API, LinkedIn (Playwright MCP)
- **Claude Reasoning Loop** — Planner reads `/Needs_Action` items and creates structured `Plan.md` files
- **Human-in-the-Loop Approval** — sensitive actions require human sign-off via `/Pending_Approval`
- **Scheduler** — lightweight cron-like system with periodic and daily task modes
- **Seven Silver Agent Skills** — `process-inbox`, `update-dashboard`, `vault-manager`, `create-plan`, `manage-approvals`, `send-email`, `post-linkedin`
- **Orchestrator** — coordinates all components

## Architecture

```
PERCEPTION LAYER          OBSIDIAN VAULT              REASONING LAYER
+-----------------+       +--------------------+      +------------------+
| FileSystem      | ----> | /Inbox             |      |                  |
| Watcher         |       | /Needs_Action      | <--> | Claude Code      |
+-----------------+       | /Done              |      | (Agent Skills)   |
| Gmail Watcher   | ----> | /Plans             |      |                  |
+-----------------+       | /Logs              |      | Planner          |
| LinkedIn        | ----> | /Pending_Approval  |      | (Plan.md gen)    |
| Watcher         |       | /Approved          |      +------------------+
+-----------------+       | /Rejected          |
| Facebook        | ----> | /Briefings         |      ACTION LAYER
| Watcher         |       | /Accounting        |      +------------------+
+-----------------+       | Dashboard.md       |      | Orchestrator     |
| Instagram       | ----> | Company_Handbook.md|      | Scheduler        |
| Watcher         |       | Business_Goals.md  |      | Approval Manager |
+-----------------+       +--------------------+      | Error Tracker    |
| Twitter         | ---->                             | Ralph Loop       |
| Watcher         |        ACCOUNTING LAYER           +------------------+
+-----------------+        +----------------+
                           | Odoo Connector |
                           | (JSON-RPC)     |
                           +----------------+
```

**Flow:** Input detected by Watcher → Action file in `/Needs_Action` → Planner creates `Plan.md` in `/Plans` → Sensitive actions go to `/Pending_Approval` → Human approves/rejects → Approved items processed → Moved to `/Done` → Dashboard updated. Weekly scheduler triggers CEO Briefing and accounting summary.

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.13+ |
| UV | Latest (package manager) |
| Claude Code | Active subscription |
| Obsidian | v1.10.6+ (optional, for viewing vault) |
| Gmail API | OAuth2 credentials (optional) |
| Playwright MCP | Running server (optional, for social watchers) |
| Odoo Community | Running instance (optional, for accounting) |

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

6. **Use Claude Code with Agent Skills** — run Claude Code from the project root. All thirteen skills are available.

### Optional: Gmail Watcher Setup

1. Create OAuth2 credentials at [Google Cloud Console](https://console.cloud.google.com/)
2. Download `credentials.json` to the project root
3. Set `ENABLE_GMAIL=true` in `.env`
4. On first run, complete the OAuth2 flow in your browser

### Optional: Social Media Watcher Setup (Facebook / Instagram / Twitter)

1. Start the Playwright MCP server:
   ```bash
   bash .claude/skills/browsing-with-playwright/scripts/start-server.sh
   ```
2. Log into each platform in the Playwright browser session
3. Set `ENABLE_FACEBOOK=true`, `ENABLE_INSTAGRAM=true`, and/or `ENABLE_TWITTER=true` in `.env`
4. Set the corresponding `*_SESSION_PATH` variables to persist your browser sessions

### Optional: Odoo Accounting Setup

1. Install and run [Odoo Community](https://www.odoo.com/page/community)
2. Set `ENABLE_ODOO=true` and configure `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` in `.env`
3. The connector will sync invoices and payments on each cycle

### Optional: CEO Briefing Setup

- Set `ENABLE_CEO_BRIEFING=true` in `.env`
- The briefing generates automatically every Sunday at 20:00 UTC
- Briefings appear in `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`

### Optional: Ralph Wiggum Loop (Stop Hook)

Configure the stop hook in `.claude/settings.json`:
```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python src/ralph_loop.py --vault-path ./vault"
          }
        ]
      }
    ]
  }
}
```

### Optional: Scheduling

Generate cron entries or Windows Task Scheduler XML:
```bash
# Linux/macOS cron entries
uv run python -c "from src.scheduler import generate_cron_entries; print(generate_cron_entries())"

# Windows Task Scheduler XML
uv run python -c "from src.scheduler import generate_windows_task_xml; print(generate_windows_task_xml())"
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
| `ENABLE_GMAIL` | `false` | Enable Gmail watcher |
| `ENABLE_LINKEDIN` | `false` | Enable LinkedIn watcher |
| `ENABLE_FACEBOOK` | `false` | Enable Facebook watcher |
| `ENABLE_INSTAGRAM` | `false` | Enable Instagram watcher |
| `ENABLE_TWITTER` | `false` | Enable Twitter watcher |
| `ENABLE_ODOO` | `false` | Enable Odoo accounting integration |
| `ENABLE_CEO_BRIEFING` | `true` | Enable weekly CEO briefing generation |
| `GMAIL_CREDENTIALS` | `credentials.json` | Path to Gmail OAuth2 credentials |
| `GMAIL_TOKEN` | `token.json` | Path to saved Gmail auth token |
| `GMAIL_QUERY` | `is:unread is:important` | Gmail search query filter |
| `LINKEDIN_SESSION_PATH` | (none) | Playwright persistent session for LinkedIn |
| `FACEBOOK_SESSION_PATH` | (none) | Playwright persistent session for Facebook |
| `INSTAGRAM_SESSION_PATH` | (none) | Playwright persistent session for Instagram |
| `TWITTER_SESSION_PATH` | (none) | Playwright persistent session for Twitter |
| `MCP_CLIENT_PATH` | `.claude/skills/.../mcp-client.py` | Path to MCP client script |
| `MCP_SERVER_URL` | `http://localhost:8808` | Playwright MCP server URL |
| `ODOO_URL` | `http://localhost:8069` | Odoo instance URL |
| `ODOO_DB` | `odoo` | Odoo database name |
| `ODOO_USER` | `admin` | Odoo login username |
| `ODOO_PASSWORD` | (none) | Odoo login password |

## Project Structure

```
Personal-AI-Employee/
├── .claude/skills/                  # Claude Code Agent Skills (13 total)
│   ├── browsing-with-playwright/      # Pre-configured Playwright MCP
│   ├── process-inbox/                 # Process /Needs_Action items
│   ├── update-dashboard/              # Refresh Dashboard.md
│   ├── vault-manager/                 # Vault maintenance operations
│   ├── create-plan/                   # Generate Plan.md files
│   ├── manage-approvals/              # HITL approval workflow
│   ├── send-email/                    # Gmail sending with approval
│   ├── post-linkedin/                 # LinkedIn posting with approval
│   ├── post-facebook/                 # Facebook posting with approval
│   ├── post-instagram/                # Instagram posting with approval
│   ├── post-twitter/                  # Twitter posting with approval
│   ├── generate-briefing/             # Monday Morning CEO Briefing
│   ├── odoo-accounting/               # Odoo accounting management
│   └── ralph-loop/                    # Autonomous task loop (Stop hook)
├── src/
│   ├── watchers/
│   │   ├── base_watcher.py            # Abstract base class
│   │   ├── filesystem_watcher.py      # File drop watcher (watchdog)
│   │   ├── gmail_watcher.py           # Gmail API watcher
│   │   ├── linkedin_watcher.py        # LinkedIn watcher (Playwright MCP)
│   │   ├── social_base_watcher.py     # Abstract base for social watchers
│   │   ├── facebook_watcher.py        # Facebook watcher (Playwright MCP)
│   │   ├── instagram_watcher.py       # Instagram watcher (Playwright MCP)
│   │   └── twitter_watcher.py         # Twitter watcher (Playwright MCP)
│   ├── orchestrator.py                # Master process coordinator
│   ├── approval.py                    # HITL approval workflow manager
│   ├── planner.py                     # Plan.md generation engine
│   ├── scheduler.py                   # Cron-like task scheduler
│   ├── odoo_connector.py              # Odoo JSON-RPC client
│   ├── briefing.py                    # CEO Briefing generator
│   ├── ralph_loop.py                  # Ralph Wiggum autonomous loop
│   └── retry_handler.py               # Error recovery (with_retry, ErrorTracker)
├── tests/
│   ├── test_base_watcher.py           # 12 tests
│   ├── test_filesystem_watcher.py     # 39 tests
│   ├── test_orchestrator.py           # 26 tests (Bronze regression)
│   ├── test_orchestrator_silver.py    # 30 tests (Silver features)
│   ├── test_orchestrator_gold.py      # 40 tests (Gold features)
│   ├── test_approval.py               # 41 tests
│   ├── test_planner.py                # 52 tests
│   ├── test_planner_gold.py           # 40 tests (Gold plan templates)
│   ├── test_scheduler.py              # 42 tests
│   ├── test_gmail_watcher.py          # 40 tests
│   ├── test_linkedin_watcher.py       # 34 tests
│   ├── test_social_watchers.py        # 76 tests (Facebook/Instagram/Twitter)
│   ├── test_odoo_connector.py         # 32 tests
│   ├── test_briefing.py               # 43 tests
│   ├── test_ralph_loop.py             # 47 tests
│   └── test_retry_handler.py          # 37 tests
├── vault/                             # Obsidian vault (knowledge base)
│   ├── Inbox/                         # Drop folder (monitored)
│   ├── Needs_Action/                  # Items awaiting processing
│   ├── Done/                          # Completed items archive
│   ├── Plans/                         # Generated action plans
│   ├── Logs/                          # JSON audit logs
│   ├── Pending_Approval/              # Items needing human approval
│   ├── Approved/                      # Human-approved actions
│   ├── Rejected/                      # Human-rejected actions
│   ├── Briefings/                     # Generated CEO briefing reports
│   ├── Accounting/                    # Financial summaries from Odoo
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

All 580 tests pass, covering:
- **Regression**: All 77 Bronze tests + 316 Silver tests pass unchanged
- **Retry Handler**: with_retry decorator, ErrorTracker circuit breaker, error classification
- **Social Watchers**: Facebook/Instagram/Twitter notification parsing, MCP integration, classification
- **Odoo Connector**: JSON-RPC client, mock DEV_MODE data, financial summary generation
- **Briefing Generator**: Weekly done-item scanning, log aggregation, financial section, Markdown output
- **Ralph Loop**: State persistence, completion detection (promise + file), stop hook, active loop listing
- **Gold Orchestrator**: Gold component initialization, social watcher startup, error tracking, dashboard
- **Gold Planner**: All 14 new plan templates for Facebook/Instagram/Twitter/Odoo action types

## Security

- **Credentials**: No credentials are stored in the vault or committed to git. The `.env` file is in `.gitignore`.
- **Dev Mode**: `DEV_MODE=true` (default) prevents any real external actions. Odoo connector returns mock data.
- **Dry Run**: `DRY_RUN=true` (default) logs intended actions without executing.
- **Audit Trail**: All watcher and orchestrator actions are logged as structured JSON in `vault/Logs/`.
- **HITL Pattern**: Sensitive actions (payments, emails, social posts) create approval requests in `/Pending_Approval` — the system will not act until a human moves the file to `/Approved`.
- **Path Traversal Prevention**: File names are sanitized to block `../` attacks.
- **YAML Injection Prevention**: User-supplied strings are escaped before embedding in YAML frontmatter.
- **Thread Safety**: All log file writes protected by `threading.Lock`.
- **Graceful Degradation**: Each watcher and integration is independently optional.
- **Circuit Breaker**: ErrorTracker automatically stops retrying after repeated failures to prevent cascade issues.

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
| `post-facebook` | Scheduled or on demand | Drafts Facebook post, creates approval request, publishes via Playwright |
| `post-instagram` | Scheduled or on demand | Drafts Instagram post, creates approval request, publishes via Playwright |
| `post-twitter` | Scheduled or on demand | Drafts tweet, creates approval request, publishes via Playwright |
| `generate-briefing` | Sunday 20:00 UTC or on demand | Generates Monday Morning CEO Briefing with KPIs, revenue, and suggestions |
| `odoo-accounting` | Invoice/payment events or on demand | Syncs Odoo accounting data, generates monthly financial summaries |
| `ralph-loop` | Multi-step autonomous tasks | Injects Stop hook to keep Claude iterating until task is complete |

## Approval Workflow

Actions that **always require human approval**:
- `payment`, `email_send`, `linkedin_post`, `social_post`
- `file_delete`, `external_api_call`, `new_contact_email`
- `facebook_post`, `instagram_post`, `twitter_post`
- `odoo_payment`, `odoo_invoice_post`, `accounting_action`

Actions that are **auto-approved**:
- `file_organize`, `log_create`, `dashboard_update`, `plan_create`
- `briefing_generate`, `accounting_summary`, `social_summary`

**How to approve/reject**: Move the file from `vault/Pending_Approval/` to either `vault/Approved/` or `vault/Rejected/`. The orchestrator will process the decision on its next cycle.

## Ralph Wiggum Loop

The Ralph Wiggum loop enables Claude to autonomously complete multi-step tasks without stopping prematurely. Two completion strategies are supported:

1. **Promise-based**: Claude outputs `<promise>TASK_COMPLETE</promise>` when done
2. **File-movement-based**: A task file moves to `/Done` when work is complete

State is persisted to `vault/Logs/ralph_<task_id>.json` between iterations. The stop hook (configured in `.claude/settings.json`) intercepts Claude's stop signal and re-injects the prompt if the task is not yet complete.

## Error Recovery

All external integrations use exponential backoff retry logic:

```python
@with_retry(max_attempts=3, base_delay=1.0, max_delay=60.0)
def call_external_api():
    ...
```

The `ErrorTracker` circuit breaker monitors error rates and stops retrying after a configurable threshold, preventing cascade failures from propagating.
