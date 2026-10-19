"""Just enough pytest for the browser test runner. Local runs and CI use real pytest."""


class Skipped(Exception):
    pass


def skip(msg=""):
    raise Skipped(msg)


def importorskip(name):
    try:
        return __import__(name)
    except ImportError:
        raise Skipped(f"{name} is not available here")


class _Raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            raise AssertionError(f"DID NOT RAISE {self.exc.__name__}")
        if not issubclass(et, self.exc):
            return False
        self.value = ev
        return True


def raises(exc):
    return _Raises(exc)


def fixture(*a, **k):
    if a and callable(a[0]):
        a[0]._is_fixture = True
        return a[0]
    def deco(fn):
        fn._is_fixture = True
        return fn
    return deco


class _Mark:
    def parametrize(self, names, values, ids=None):
        def deco(fn):
            fn._params = getattr(fn, "_params", []) + [([n.strip() for n in names.split(",")], list(values), ids)]
            return fn
        return deco

    def __getattr__(self, _):
        return lambda *a, **k: (lambda fn: fn)


mark = _Mark()
