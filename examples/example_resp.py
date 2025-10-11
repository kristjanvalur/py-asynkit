from collections.abc import Generator
from typing import Any

import pytest

from asynkit import Monitor, await_sync

"""
Example of a stateful parser, implemented via recursive async calls,
and suspended via Monitor.
Can be used both in async and sync code.
An example of a `generator` based parser is also included, for comparison.
"""

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


CRNL = b"\r\n"


def parse_resp_gen(
    unparsed: bytes,
) -> Generator[tuple[Any, bytes] | None, bytes | None, None]:
    """
    This is a generator function that parses a Redis RESP string.
    we only support ints and arrays of ints for simplicity
    the generator approach maintains state between calls
    Invoking a sub-generator requires some standard boilerplate.
    """
    # wait until we have the first line
    parts = unparsed.split(CRNL, 1)
    while len(parts) == 1:
        incoming = yield None
        assert incoming is not None
        unparsed += incoming
        parts = unparsed.split(CRNL, 1)

    line, unparsed = parts
    cmd, value = line[:1], line[1:]

    if cmd == b":":
        yield int(value), unparsed

    elif cmd == b"*":
        count = int(value)
        result_array: list[Any] = []
        for _ in range(count):
            # recursively parse each sub-object
            # boilerplate required.
            parser = parse_resp_gen(unparsed)
            parsed = parser.send(None)
            while parsed is None:
                incoming = yield None
                assert incoming is not None
                parsed = parser.send(incoming)
            item, unparsed = parsed
            result_array.append(item)
        yield result_array, unparsed


def test_generator() -> None:
    """
    Test our generator based parser for Redis RESP strings.
    """
    # construct a resp string consisting of an array of arrays of ints
    resp = b"*2\r\n*3\r\n:1\r\n:2\r\n:3\r\n*2\r\n:4\r\n:5\r\n"
    # split it up into chunks of two bytes
    chunks = [resp[i : i + 2] for i in range(0, len(resp), 2)]

    # create the parser
    parser = parse_resp_gen(b"")
    parsed = parser.send(None)
    assert parsed is None
    # send the chunks to the parser
    while True:
        parsed = parser.send(chunks.pop(0))
        if parsed is not None:
            break
    assert parsed == ([[1, 2, 3], [4, 5]], b"")


async def parse_resp_mon(
    monitor: Monitor[tuple[Any, bytes]], unparsed: bytes
) -> tuple[Any, bytes]:
    """
    A Monitor based parser for Redis RESP strings.
    """
    # get first line
    parts = unparsed.split(CRNL, 1)
    while len(parts) == 1:
        # request more data
        unparsed += await monitor.oob()
        parts = unparsed.split(CRNL, 1)
    line, unparsed = parts
    cmd, value = line[:1], line[1:]

    if cmd == b":":
        return int(value), unparsed

    elif cmd == b"*":
        count = int(value)
        result_array: list[Any] = []
        # recursively parse each sub-object
        # no boilerplate required.
        for _ in range(count):
            item, unparsed = await parse_resp_mon(monitor, unparsed)
            result_array.append(item)
        return result_array, unparsed
    raise ValueError(f"unknown command '{cmd.decode()}'")


async def test_monitor() -> None:
    """Test our monitor based parser for Redis RESP strings."""
    # construct a resp string consisting of an array of arrays of ints
    resp = b"*2\r\n*3\r\n:1\r\n:2\r\n:3\r\n*2\r\n:4\r\n:5\r\n"
    # split it up into chunks of two bytes
    chunks = [resp[i : i + 2] for i in range(0, len(resp), 2)]

    # create the parser
    m: Monitor[tuple[Any, bytes]] = Monitor()
    parser = parse_resp_mon(m, b"")
    await m.start(parser)

    while True:
        parsed = await m.try_await(parser, chunks.pop(0))
        if parsed is not None:
            break

    assert parsed == ([[1, 2, 3], [4, 5]], b"")


def test_monitor_sync() -> None:
    """Test our monitor based parser for Redis RESP strings.
    from synchronous code.
    """
    # construct a resp string consisting of an array of arrays of ints
    resp = b"*2\r\n*3\r\n:1\r\n:2\r\n:3\r\n*2\r\n:4\r\n:5\r\n"
    # split it up into chunks of two bytes
    chunks = [resp[i : i + 2] for i in range(0, len(resp), 2)]

    # create the parser
    m: Monitor[tuple[Any, bytes]] = Monitor()
    parser = parse_resp_mon(m, b"")
    await_sync(m.start(parser))

    while True:
        parsed = await_sync(m.try_await(parser, chunks.pop(0)))
        if parsed is not None:
            break

    assert parsed == ([[1, 2, 3], [4, 5]], b"")
