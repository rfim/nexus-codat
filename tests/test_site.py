"""Every page links only to files that exist, and the PDFs and GIFs it offers are in the repo."""
import re

import pytest

from nexus.paths import ROOT

PAGES = ["index.html", "orchestrator.html", "mcp.html", "run.html", "oncall.html"]


@pytest.mark.parametrize("page", PAGES)
def test_local_links_and_assets_exist(page):
    html = (ROOT / page).read_text()
    for ref in re.findall(r'(?:href|src)="([^"#:]+)"', html):
        assert (ROOT / ref).exists(), f"{page} links to missing {ref}"


@pytest.mark.parametrize("page", PAGES)
def test_every_page_says_it_is_synthetic_and_independent(page):
    html = (ROOT / page).read_text()
    assert "ynthetic" in html and "not affiliated with" in html


def test_downloads_are_present():
    for f in ("Nexus_Codat_VIM.pdf", "VIM_Codat_one_page.pdf", "VIM_Codat_companion_note.pdf",
              "gif/1_NEXUS_Codat_enable_MCP.gif", "gif/2_NEXUS_Codat_on_call.gif"):
        assert (ROOT / "assets" / f).stat().st_size > 50_000, f


def test_no_real_codat_data_or_credentials_in_the_repo():
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "contracts").rglob("*.yml")):
        text = p.read_text()
        assert not re.search(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]+", text), p


def test_the_code_editor_lists_exactly_the_repo_files():
    import json
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from manifest import manifest
    assert json.loads((ROOT / "assets" / "data" / "files.json").read_text()) == manifest()


def test_the_examples_run_unchanged_in_the_browser_runtime():
    """Examples only use modules that need no Spark, so the editor can run them."""
    for p in (ROOT / "examples").glob("*.py"):
        text = p.read_text()
        assert "pyspark" not in text and "nexus.spark" not in text and "bronze" not in text, p.name
