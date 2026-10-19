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
        raise RuntimeError("The MCP transport doesn't run in the browser; the tools are called directly.")
