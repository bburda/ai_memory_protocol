# AI Memory Protocol

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/python-≥3.10-blue.svg)](https://python.org)
[![CI](https://github.com/bburda/ai_memory_protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/bburda/ai_memory_protocol/actions/workflows/ci.yml)

**Versioned, graph-based persistent memory for AI coding agents** — powered by [Sphinx-Needs](https://sphinx-needs.readthedocs.io/).

AI agents lose context between sessions. This protocol gives them a structured way to **remember**, **recall**, and **evolve** knowledge — with full Git history, typed entries, graph links, and machine-readable output.

## Features

- **Typed memories** — observations, decisions, facts, preferences, risks, goals, open questions
- **Graph links** — relates, supports, depends, supersedes, contradicts, example_of
- **Tag-based discovery** — `topic:api`, `repo:backend`, `tier:core`
- **Context-optimized output** — brief / compact / context / JSON formats with body toggling
- **Stale detection** — auto-expire, review reminders, staleness checks
- **Auto-scaling** — RST files split at 50 entries, transparent to queries
- **Git-native** — every memory is an RST directive, fully diffable and versioned
- **MCP server** — expose memory as tools for Claude Desktop, VS Code Copilot, and other MCP clients
- **CLI-first** — 12 subcommands for full lifecycle management

## Installation

```bash
# From PyPI (when published)
pipx install ai-memory-protocol

# From source
git clone https://github.com/bburda/ai_memory_protocol.git
pipx install -e ai_memory_protocol/

# With MCP server support
pipx install -e 'ai_memory_protocol/[mcp]'
```

This installs the `memory` CLI command (and optionally `memory-mcp-stdio`) globally on PATH.

## Quick Start

```bash
# 1. Create a memory workspace
memory init .memories --name "My Project" --install

# 2. Add your first memory
memory add fact "API runs on port 8080" \
  --tags "topic:api,repo:backend" \
  --confidence high \
  --body "Gateway listens on 0.0.0.0:8080 by default" \
  --rebuild

# 3. Search
memory recall api port
memory recall --tag topic:api --format brief

# 4. Get full details
memory get FACT_api_runs_on_port_8080
```

## How It Works

```
RST files (memory/*.rst)          ← Human + AI editable, Git-tracked
    │
    ▼ memory rebuild (sphinx-build)
needs.json (_build/html/needs.json)   ← Machine-readable index
    │
    ▼ memory recall / get / list
Formatted output                  ← Optimized for LLM context windows
```

Memories are stored as [Sphinx-Needs](https://sphinx-needs.readthedocs.io/) directives in RST files. A `memory rebuild` command runs Sphinx to produce `needs.json` — the single query layer for all search operations. This means memories are simultaneously human-readable documentation and machine-queryable data.

## CLI Reference

```bash
memory init <dir>                       # Create a new workspace
memory add <type> "<title>" [options]   # Record a memory
memory recall [query] [--tag ...] [--format brief|compact|context|json]
memory get <ID>                         # Full details of one memory
memory related <ID> [--hops N]          # Graph walk from a memory
memory list [--type TYPE] [--status S]  # Browse all memories
memory update <ID> [--confidence ...] [--add-tags ...]
memory deprecate <ID> [--by NEW_ID]     # Mark as deprecated
memory tags [--prefix PREFIX]           # Discover tags in use
memory stale                            # Find expired/overdue memories
memory review                           # Show memories needing review
memory rebuild                          # Rebuild needs.json
```

Key flags for `recall`:
- `--format brief` — ultra-compact, minimal tokens
- `--body` — include body text (off by default)
- `--sort newest|oldest|confidence|updated`
- `--limit N` — cap results
- `--expand 0` — disable graph expansion
- `--stale` — only expired/review-overdue

## MCP Server

Expose memory tools to LLM clients via the [Model Context Protocol](https://modelcontextprotocol.io/).

### Setup

Install with MCP extras:

```bash
pipx install -e 'ai_memory_protocol/[mcp]'
```

### Claude Code

```bash
claude mcp add --transport stdio --env MEMORY_DIR=/path/to/.memories memory -- memory-mcp-stdio
```

Or add to `.mcp.json` in your project root (project scope):

```json
{
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "memory-mcp-stdio",
      "env": {
        "MEMORY_DIR": "/path/to/.memories"
      }
    }
  }
}
```

### VS Code (GitHub Copilot)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "memory": {
      "command": "memory-mcp-stdio",
      "env": {
        "MEMORY_DIR": "${workspaceFolder}/.memories"
      }
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `memory_recall` | Search memories by text/tags with formatting options |
| `memory_get` | Get full details of a specific memory |
| `memory_add` | Record a new memory with tags and metadata |
| `memory_update` | Update metadata (status, confidence, tags, etc.) |
| `memory_deprecate` | Mark a memory as deprecated |
| `memory_tags` | List all tags with counts |
| `memory_stale` | Find expired/overdue memories |
| `memory_rebuild` | Rebuild needs.json index |

## Memory Types

| Type | Prefix | Use Case |
|------|--------|----------|
| `mem` | `MEM_` | Observation, note, or finding |
| `dec` | `DEC_` | Design or architectural decision |
| `fact` | `FACT_` | Verified, stable knowledge |
| `pref` | `PREF_` | Coding style or convention |
| `risk` | `RISK_` | Uncertainty or assumption |
| `goal` | `GOAL_` | Objective or target |
| `q` | `Q_` | Open question needing resolution |

## Graph Links

| Link | Meaning |
|------|---------|
| `relates` | General association |
| `supports` | Evidence or justification |
| `depends` | Hard dependency |
| `supersedes` | Replaces older memory |
| `contradicts` | Conflict or tension |
| `example_of` | Concrete instance of concept |

## Metadata

| Field | Values | Purpose |
|-------|--------|---------|
| `confidence` | `low` / `medium` / `high` | Trust level |
| `scope` | `global`, `repo:X`, `product:X` | Applicability |
| `tags` | `prefix:value` format | Categorization |
| `source` | URL, commit, description | Provenance |
| `review_after` | ISO date | Staleness trigger |
| `expires_at` | ISO date | Auto-expire date |
| `created_at` | ISO date | Capture timestamp |

## Tagging Conventions

Tags use `prefix:value` format for consistent discovery:

- `topic:` — Subject area (`topic:gateway`, `topic:auth`)
- `repo:` — Repository (`repo:backend`, `repo:web-ui`)
- `domain:` — Knowledge domain (`domain:robotics`, `domain:web`)
- `tier:` — Importance level (`tier:core`, `tier:detail`)
- `intent:` — Purpose (`intent:decision`, `intent:coding-style`)

## AI Agent Integration

### Recommended Workflow

1. **RECALL before working** — always check existing knowledge before starting a task
2. **ADD after learning** — record discoveries, decisions, and observations immediately
3. **SUPERSEDE, don't edit** — when knowledge changes, add a new memory and deprecate the old one
4. **CHECK STALENESS periodically** — use `memory stale` to maintain knowledge quality

### Context Window Optimization

- Default `recall` omits body text — use `memory get <ID>` only when you need details
- Use `--format brief` for initial scanning, then drill into specific IDs
- Use `--limit 10` when exploring broad topics
- Use `--expand 0` to skip graph expansion for exact matches only
- Use `--tag` filters to narrow results instead of free-text
- Use `memory tags` to discover available tag prefixes before filtering

## Project Structure

```
ai_memory_protocol/
├── pyproject.toml           # Package definition, CLI + MCP entry points
├── README.md
├── LICENSE                  # Apache 2.0
├── CONTRIBUTING.md
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
└── src/
    └── ai_memory_protocol/
        ├── __init__.py
        ├── cli.py           # CLI (argparse, 12 subcommands)
        ├── mcp_server.py    # MCP server (8 tools, stdio transport)
        ├── config.py        # Type definitions, constants
        ├── engine.py        # Workspace detection, search, graph walk
        ├── formatter.py     # Output formatting (brief/compact/context/json)
        ├── rst.py           # RST generation, editing, file splitting
        └── scaffold.py      # Workspace scaffolding (init command)
```

Memory data lives in a **separate workspace** (e.g., `.memories/`), created with `memory init`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

## License

[Apache 2.0](LICENSE)
