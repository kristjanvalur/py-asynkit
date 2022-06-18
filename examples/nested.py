from asynkit import nest, nested_jit
from contextlib import contextmanager


@contextmanager
def a():
    yield "a"


@contextmanager
def b():
    yield "b"


with nest, nested_jit(a, b) as v:
    print(v)
