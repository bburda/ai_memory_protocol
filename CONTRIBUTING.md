# Contributing to AI Memory Protocol

Thank you for your interest in contributing! This project is open source under the Apache 2.0 license.

## Getting Started

```bash
# Clone the repo
git clone https://github.com/bburda/ai_memory_protocol.git
cd ai_memory_protocol

# Install in development mode
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[mcp]'
pip install ruff pytest pre-commit

# Set up pre-commit hooks
pre-commit install
```

## Development Workflow

1. Create a feature branch from `main`
2. Make your changes
3. Run linting: `ruff check src/ && ruff format --check src/`
4. Test the CLI: `memory --version`
5. Submit a pull request

## Code Style

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (line length 100)
- **Linter**: Ruff with pycodestyle, pyflakes, isort, bugbear, pyupgrade, simplify rules
- **Python**: ≥3.10, use `from __future__ import annotations` for modern type hints

Pre-commit hooks enforce formatting automatically on every commit.

## Project Structure

- `src/ai_memory_protocol/cli.py` — CLI entry point (argparse)
- `src/ai_memory_protocol/mcp_server.py` — MCP server with 8 tools
- `src/ai_memory_protocol/engine.py` — Core search and graph traversal
- `src/ai_memory_protocol/formatter.py` — Output formatting
- `src/ai_memory_protocol/rst.py` — RST generation and editing
- `src/ai_memory_protocol/config.py` — Constants and type definitions
- `src/ai_memory_protocol/scaffold.py` — Workspace initialization

## Reporting Issues

Please use [GitHub Issues](https://github.com/bburda/ai_memory_protocol/issues) for bug reports and feature requests. Include:

- Steps to reproduce
- Expected vs actual behavior
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
