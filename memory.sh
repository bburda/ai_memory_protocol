#!/usr/bin/env bash
# AI Memory Protocol — shell wrapper
# Sets MEMORY_DIR and delegates to the installed 'memory' CLI.
#
# Usage (direct):
#   bash ai_memory_protocol/memory.sh recall gateway
#   bash ai_memory_protocol/memory.sh add mem "Title" --tags "topic:x"
#
# Usage (sourced — exports MEMORY_DIR into current shell):
#   source ai_memory_protocol/memory.sh
#   memory recall gateway
#
# Installation:
#   pipx install -e ai_memory_protocol   # puts 'memory' on PATH globally
#   Then just: export MEMORY_DIR=~/workspace/.memories

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default to .memories workspace; override with MEMORY_DIR env var
export MEMORY_DIR="${MEMORY_DIR:-$WORKSPACE_DIR/.memories}"

# If script is run directly (not sourced), execute with arguments
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    exec memory "$@"
fi
