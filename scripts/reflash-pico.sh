#!/usr/bin/env bash
# Backwards-compatible wrapper for the original Raspberry Pi Pico target.
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/flash-board.sh" pico "$@"
