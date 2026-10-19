"""yaml.safe_load for Pyodide, backed by js-yaml with the core schema (no timestamp conversion)."""
import js


def safe_load(text):
    obj = js.jsyaml.load(text, js.Object.fromEntries([["schema", js.jsyaml.CORE_SCHEMA]]))
    return obj.to_py() if hasattr(obj, "to_py") else obj
