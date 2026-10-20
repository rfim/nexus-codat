"""An MCPServer stand-in for the browser: same decorator and tool listing, no transport."""
import inspect
import typing
from types import SimpleNamespace

_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _schema(fn):
    sig, hints = inspect.signature(fn), typing.get_type_hints(fn)
    props, required = {}, []
    for name, p in sig.parameters.items():
        t = hints.get(name)
        base = next((a for a in getattr(t, "__args__", ()) if a is not type(None)), t)
        props[name] = {"type": _JSON.get(typing.get_origin(base) or base, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


class MCPServer:
    def __init__(self, name, instructions=None, **_):
        self.name, self.instructions, self._tools = name, instructions, {}

    def tool(self, name=None, **_):
        def deco(fn):
            self._tools[name or fn.__name__] = fn
            return fn
        return deco

    async def list_tools(self):
        return [SimpleNamespace(name=n, description=(f.__doc__ or "").strip().splitlines()[0], input_schema=_schema(f))
                for n, f in self._tools.items()]

    async def call_tool(self, name, arguments):
        return self._tools[name](**arguments)

    def run(self, transport="stdio"):
        # Run on mcp_server.py: show what a client would see instead of starting a transport
        print(f"MCP server {self.name!r}: the stdio transport doesn't run in a browser, so here are its tools.")
        print("Locally: python -m nexus.mcp_server (stdio), or call the tools directly as in examples/04.\n")
        for n, f in self._tools.items():
            print(f"  {n}({', '.join(_schema(f).get('properties', {}))})  {(f.__doc__ or '').strip().splitlines()[0]}")
