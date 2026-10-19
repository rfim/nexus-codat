#!/usr/bin/env bash
# Rebuild everything the site shows from a clean run: data, pipeline, contracts, export.
# Locally the catalog lives for one Spark session, so the run and the export share a process.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf target landing
export PYTHONPATH=src
# The whole graph through Dagster: land → conform → publish → SQL + Great Expectations checks → on-call agent → export.
# The on-call agent uses Claude when ANTHROPIC_API_KEY (or another Anthropic credential) is set, offline rules otherwise.
python -m nexus.orchestration.run
python scripts/manifest.py
