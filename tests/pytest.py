"""Minimal pytest compatibility shim for environments without pytest installed."""
import math
from contextlib import contextmanager


class _RaisesContext:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected {self.exc_type} but nothing was raised")
        return issubclass(exc_type, self.exc_type)


def raises(exc_type):
    return _RaisesContext(exc_type)


class approx:
    def __init__(self, expected, rel=1e-3, abs=1e-3):
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def __eq__(self, actual):
        return math.isclose(actual, self.expected, rel_tol=self.rel, abs_tol=self.abs)

    def __repr__(self):
        return f"approx({self.expected})"


def fixture(*args, **kwargs):
    def decorator(fn):
        return fn
    if args and callable(args[0]):
        return decorator(args[0])
    return decorator
