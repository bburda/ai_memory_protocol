.PHONY: install install-dev install-mcp inject-mcp test test-cov test-unit test-integration lint format doctor uninstall help

install:  ## Install via pipx (CLI only)
	pipx install -e .

install-mcp:  ## Install via pipx with MCP support
	pipx install -e '.[mcp]'

install-dev:  ## Install for development (editable + dev deps)
	pip install -e '.[mcp]'
	pip install ruff pytest pytest-cov

inject-mcp:  ## Add MCP to existing pipx install
	pipx inject ai-memory-protocol mcp

test:  ## Run all tests
	pytest tests/ -v

test-unit:  ## Run unit tests only (no Sphinx needed)
	pytest tests/ -v -m "not integration"

test-integration:  ## Run integration tests (requires Sphinx)
	pytest tests/ -v -m integration

test-cov:  ## Run tests with coverage
	pytest tests/ -v --cov=ai_memory_protocol --cov-report=term-missing --cov-report=html

lint:  ## Run linters
	ruff check src/ tests/
	ruff format --check src/ tests/

format:  ## Format code
	ruff format src/ tests/

doctor:  ## Verify installation
	memory doctor

uninstall:  ## Uninstall from pipx
	pipx uninstall ai-memory-protocol

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' Makefile | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
