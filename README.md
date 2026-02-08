# AI Memory Protocol

Versioned, graph-based memory for AI agents — powered by [Sphinx-Needs](https://sphinx-needs.readthedocs.io/).

## What is this?

A **protocol** for AI agents to maintain, query, and evolve structured knowledge across sessions — with full Git history and traceability.

Every memory is a **need** (typed object). Every relation is a **link** (graph edge). Every build produces a machine-readable `needs.json`.

## Install

```bash
# Recommended: install globally via pipx (no venv management needed)
pipx install -e ai_memory_protocol/

# Alternative: install into a venv
cd ai_memory_protocol && python3 -m venv .venv && .venv/bin/pip install -e .
```

This installs the `memory` CLI command globally on PATH.

## Quick Start

```bash
# Create a new memory workspace
memory init ./my-project-memory --name "My Project" --author "yourname"
cd my-project-memory

# Install Sphinx deps (if not using --install flag)
python3 -m venv .venv && .venv/bin/pip install sphinx sphinx-needs sphinxcontrib-plantuml sphinx-rtd-theme sphinx-design

# Add your first memory
memory add mem "REST API returns 500 on large payloads" \
  --tags "topic:api,repo:backend" \
  --confidence medium \
  --body "Observed when sending >10MB payloads to /upload endpoint"

# Build needs.json
memory rebuild

# Search
memory recall api payload
memory recall --tag topic:api --format compact
```

## CLI Reference

```bash
# Initialize a new workspace
memory init <dir> [--name "Name"] [--author "name"] [--install]

# Add memories
memory add <type> "<title>" [--tags ...] [--confidence ...] [--body ...] [--source ...]
memory add mem "Title" --tags "topic:X" --rebuild   # Auto-rebuild after adding
#   types: mem, dec, fact, pref, risk, goal, q

# Search / recall
memory recall <words>                    # Free-text (OR logic)
memory recall --tag topic:api            # By tag
memory recall --tag repo:X --type fact   # Combined filters
memory recall gateway --format json      # Output as JSON
memory recall --format brief             # Ultra-compact for scanning
memory recall --sort newest              # Sort by creation date (newest first)
memory recall --sort confidence          # Sort by confidence (high first)
memory recall --limit 10                 # Cap results
memory recall --body                     # Include body text (off by default)
memory recall --expand 0                 # No graph expansion
memory recall --stale                    # Only expired/review-overdue memories

# View a specific memory (full metadata, no file reading needed)
memory get <ID>

# Explore related memories (graph walk)
memory related <ID> [--hops 2]

# List all memories
memory list [--type fact] [--status active] [--all]

# Update metadata
memory update <ID> --confidence high
memory update <ID> --status promoted
memory update <ID> --add-tags "tier:core,topic:new"
memory update <ID> --remove-tags "topic:old"
memory update <ID> --review-after 2026-06-01

# Deprecate
memory deprecate <ID> [--by <NEW_ID>]

# Tag discovery
memory tags                              # All tags grouped by prefix with counts
memory tags --prefix topic               # Only topic:* tags

# Stale detection
memory stale                             # Show expired + review-overdue memories

# Maintenance
memory rebuild                           # Rebuild needs.json
memory review                            # Show memories due for review
```

### Shell Wrapper

For AI agents in a workspace, use `memory.sh` which auto-sets the workspace directory:

```bash
MEMORY="bash ~/workspace/ai_memory_protocol/memory.sh"
$MEMORY recall gateway
$MEMORY add mem "New observation" --tags "topic:gateway"
```

## Memory Types

| Type | Directive | Use Case |
|------|-----------|----------|
| `mem` | `.. mem::` | Observation or note |
| `dec` | `.. dec::` | Architectural/design decision |
| `pref` | `.. pref::` | User or team preference |
| `fact` | `.. fact::` | Stable, validated fact |
| `risk` | `.. risk::` | Risk, assumption, uncertainty |
| `goal` | `.. goal::` | Objective or target |
| `q` | `.. q::` | Open question |

## Protocol Operations

1. **Capture** — Record a new observation with source and tags
2. **Promote** — Elevate validated observations to facts/decisions
3. **Supersede** — Replace outdated knowledge (never silently edit)
4. **Review** — Periodic maintenance of memory health

## Graph Relations

| Link | Meaning |
|------|---------|
| `relates` | General association |
| `supports` | Evidence or justification |
| `depends` | Hard dependency |
| `supersedes` | Replaces older memory |
| `contradicts` | Conflict or tension |
| `example_of` | Concrete instance of concept |

## Metadata Fields

| Field | Values | Purpose |
|-------|--------|---------|
| `confidence` | `low`, `medium`, `high` | Trust level |
| `scope` | `global`, `repo:X`, `product:X` | Applicability |
| `tags` | `prefix:value` (e.g., `topic:gateway`) | Categorization |
| `source` | URL, commit, or description | Provenance |
| `review_after` | ISO date | Staleness trigger |
| `expires_at` | ISO date | Auto-expire date |
| `created_at` | ISO date | When captured |

## Tagging Conventions

Tags use `prefix:value` format:
- `topic:` — Subject area (e.g., `topic:gateway`, `topic:discovery`)
- `repo:` — Repository (e.g., `repo:ros2_medkit`, `repo:sovd_web_ui`)
- `domain:` — Knowledge domain (e.g., `domain:robotics`, `domain:web`)
- `tier:` — Importance (e.g., `tier:core`, `tier:detail`)
- `intent:` — Purpose (e.g., `intent:decision`, `intent:coding-style`)

## Output Formats

- **context** (default) — Grouped by type, facts first. For AI context windows.
- **compact** — One line per memory. For scanning.
- **brief** — Ultra-compact `[ID] Title (confidence) {tags}`. Minimal tokens.
- **json** — Raw JSON. For programmatic use.

## Scaling

RST files auto-split at 50 entries per file (e.g., `facts.rst` → `facts_002.rst`).
Split files are auto-discovered by Sphinx via glob toctree.
All edit operations (update, add-tags, deprecate) search across split files.
`needs.json` is the single query layer — file splitting is transparent to `recall`/`get`/`list`.

## Data Flow

```
RST files (memory/*.rst)
    │
    ▼ memory rebuild (sphinx-build)
needs.json (_build/html/needs.json)
    │
    ▼ memory recall / get / list / related
Filtered, linked, formatted output
```

## Project Structure

```
ai_memory_protocol/              # Pure library — no Sphinx workspace here
├── pyproject.toml               # Package definition with CLI entry point
├── README.md
├── memory.sh                    # Shell wrapper for AI agents
└── src/
    └── ai_memory_protocol/      # Installable Python package
        ├── __init__.py
        ├── cli.py               # CLI entry point (argparse, 12 subcommands)
        ├── config.py            # Type definitions, constants
        ├── engine.py            # Workspace detection, search, graph walk
        ├── formatter.py         # Output formatting (brief/compact/context/json)
        ├── rst.py               # RST generation, in-place editing, file splitting
        └── scaffold.py          # init command (workspace scaffolding)
```

Memory data lives in a **separate workspace** (e.g., `.memories/`), created with `memory init`.

## License

Apache 2.0
