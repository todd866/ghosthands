#!/usr/bin/env python3
"""Compatibility wrapper for running ghosthands directly from the checkout."""
from ghosthands.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
