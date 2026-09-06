"""TOONFLOW-PHASE-019 — Project CLI & Batch Runner Foundation.

Module entry point. Runs :func:`workflow.cli.main` and forwards the
returned exit code to the operating system via :func:`sys.exit`.

Usage examples:

    python -m workflow validate project.json
    python -m workflow show project.json
    python -m workflow run project.json

This module is intentionally tiny. All real work lives in
:mod:`workflow.cli`.
"""

import sys

from .cli import main


if __name__ == "__main__":
    sys.exit(main())
