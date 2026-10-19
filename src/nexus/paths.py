"""Where things live, and the table naming rule. No Spark import, so pure-Python modules can use it anywhere."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "target"


def table(layer: str, name: str) -> str:
    """nexus_<layer>.<name> locally; nexus.<layer>.<name> under Unity Catalog (NEXUS_CATALOG=nexus)."""
    catalog = os.environ.get("NEXUS_CATALOG")
    return f"{catalog}.{layer}.{name}" if catalog else f"nexus_{layer}.{name}"
