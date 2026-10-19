"""List the files the site's code editor can open: assets/data/files.json. Run by scripts/build.sh and CI."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOBS = ["examples/*.py", "src/nexus/*.py", "src/nexus/orchestration/*.py", "contracts/*.yml", "contracts/products/*.yml", "semantic/*.yml",
         "evals/*.yml", "tests/*.py", "scripts/*.sh", "scripts/*.py", "databricks.yml", ".github/workflows/ci.yml",
         "requirements.txt"]
SPARK = {"bronze.py", "silver.py", "gold.py", "pipeline.py", "export.py", "spark.py",
         "test_bronze.py", "test_scd2.py", "test_silver.py", "test_gold.py", "conftest.py"}
LOCAL = {"quality_gx.py", "oncall_agent.py", "assets.py", "definitions.py", "resources.py", "run.py",
         "test_quality_gx.py", "test_oncall_agent.py", "test_orchestration.py"}


def manifest() -> list[dict]:
    out = []
    for g in GLOBS:
        for p in sorted(ROOT.glob(g)):
            rel = p.relative_to(ROOT).as_posix()
            runs = "spark" if p.name in SPARK else "local" if p.name in LOCAL or "/orchestration/" in rel else "browser" if p.suffix == ".py" and rel.startswith(("examples/", "src/")) \
                else "tests" if rel.startswith("tests/") else "view"
            out.append({"path": rel, "folder": rel.rsplit("/", 1)[0] if "/" in rel else ".", "runs": runs,
                        "lines": len(p.read_text().splitlines())})
    return out


if __name__ == "__main__":
    (ROOT / "assets" / "data" / "files.json").write_text(json.dumps(manifest(), indent=1))
    print(len(manifest()), "files")
    import code_lineage  # the editor's Lineage tab
    (ROOT / "assets" / "data" / "code_lineage.json").write_text(json.dumps(code_lineage.build(), indent=1))
