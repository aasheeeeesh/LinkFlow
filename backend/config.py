"""Paths and data-release settings. Override with environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# absolute(), not resolve(): following junctions can land in a path this process cannot use.
REPO_ROOT = Path(__file__).absolute().parent.parent
DATA_DIR = Path(os.environ.get("LINKFLOW_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("LINKFLOW_DB", DATA_DIR / "linkflow.duckdb"))
# Phase 2 outputs (subgraph mapping, scores, runs) live apart from the 118M-row rank database.
ANALYSIS_DB_PATH = Path(os.environ.get("LINKFLOW_ANALYSIS_DB", DATA_DIR / "analysis.duckdb"))
DUCKDB_TEMP_DIR = DATA_DIR / "duckdb_tmp"
DUCKDB_MEMORY_LIMIT = os.environ.get("LINKFLOW_DUCKDB_MEMORY", "4GB")

RELEASE = os.environ.get("LINKFLOW_RELEASE", "cc-main-2026-may-jun-jul")
CC_BASE = "https://data.commoncrawl.org/projects/hyperlinkgraph"


def domain_url(release: str, filename: str) -> str:
    """URL of a file in a release's domain-level directory."""
    return f"{CC_BASE}/{release}/domain/{filename}"


def ranks_filename(release: str) -> str:
    """Name of the domain rank file for a release."""
    return f"{release}-domain-ranks.txt.gz"

# Phase 3 rank history: the 5 releases before RELEASE, in the order Common Crawl's official listing
# (https://commoncrawl.org/web-graphs, newest first) shows them on 2026-10-11. Not guessed.
HISTORY_RELEASES = (
    "cc-main-2026-apr-may-jun",
    "cc-main-2026-mar-apr-may",
    "cc-main-2026-feb-mar-apr",
    "cc-main-2026-jan-feb-mar",
    "cc-main-2025-26-dec-jan-feb",
)
HISTORY_DB_PATH = Path(os.environ.get("LINKFLOW_HISTORY_DB", DATA_DIR / "history.duckdb"))
