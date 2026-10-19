Small stand-ins that let the repository's pure-Python code run unchanged inside Pyodide in the browser.
They are only put on `sys.path` by `assets/code.js`; local runs and CI use the real packages.

- `yaml.py`: `safe_load` through js-yaml (core schema, so dates stay strings).
- `pytest.py`: just enough of pytest (`mark.parametrize`, `raises`, `skip`, `importorskip`, `fixture`) for the browser test runner.
- `mcp/server/mcpserver.py`: an `MCPServer` that registers tools and lists them with JSON schemas, without the transport.
- `nexus_browser.py`: runs a file as `__main__`, and runs test files with the stand-in pytest.
