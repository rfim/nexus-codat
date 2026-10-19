"""Run a repository file, or its tests, inside Pyodide."""
import asyncio
import importlib
import inspect
import os
import runpy
import sys
import time
import traceback

import pytest

REPO = "/repo"


def _drive(coro):
    """asyncio.run for coroutines that never really wait (the MCP stand-in)."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("coroutine awaited something real")


asyncio.run = _drive


def run_file(path):
    os.chdir(REPO)
    for m in [m for m in sys.modules if m == "nexus" or m.startswith("nexus.")]:
        del sys.modules[m]
    runpy.run_path(f"{REPO}/{path}", run_name="__main__")


def run_tests(paths):
    os.chdir(REPO)
    if f"{REPO}/tests" not in sys.path:
        sys.path.insert(0, f"{REPO}/tests")
    results = []
    for path in paths:
        mod_name = path.rsplit("/", 1)[-1][:-3]
        try:
            sys.modules.pop(mod_name, None)
            mod = importlib.import_module(mod_name)
        except pytest.Skipped as e:
            results.append((path, "(module)", "skipped", str(e), 0)); continue
        except Exception as e:  # noqa: BLE001
            results.append((path, "(import)", "failed", f"{type(e).__name__}: {e}", 0)); continue
        for name, fn in list(vars(mod).items()):
            if not name.startswith("test_") or not callable(fn):
                continue
            needs = [p for p in inspect.signature(fn).parameters]
            cases = [({}, name)]
            for names, values, ids in getattr(fn, "_params", []):
                cases = [(dict(c, **dict(zip(names, v if len(names) > 1 else (v,)))),
                          f"{name}[{ids[i] if ids else i}]") for c, _ in cases for i, v in enumerate(values)]
            for kwargs, label in cases:
                missing = [n for n in needs if n not in kwargs]
                t0 = time.time()
                if missing:
                    results.append((path, label, "skipped", f"needs fixture: {', '.join(missing)}", 0)); continue
                try:
                    fn(**kwargs)
                    results.append((path, label, "passed", "", time.time() - t0))
                except pytest.Skipped as e:
                    results.append((path, label, "skipped", str(e), 0))
                except Exception as e:  # noqa: BLE001
                    tb = traceback.extract_tb(e.__traceback__)[-1]
                    results.append((path, label, "failed", f"{type(e).__name__}: {e} (line {tb.lineno})", time.time() - t0))
    return results
