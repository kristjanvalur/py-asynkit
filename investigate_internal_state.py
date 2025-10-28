#!/usr/bin/env python3
"""
Investigate internal state of CoroStart during its lifecycle
"""

import asyncio
import sys

sys.path.insert(0, "/mnt/e/git/py-asynkit/src")

import asynkit.coroutine as coroutine_mod

PyCoroStart = coroutine_mod.PyCoroStart


async def sync_coro():
    return 42


async def async_coro():
    await asyncio.sleep(0.001)
    return "async result"


def inspect_corostart_state(cs, label):
    """Inspect internal state of CoroStart"""
    print(f"\n{label}:")
    print(f"  done(): {cs.done()}")

    # Check if we can access internal attributes
    if hasattr(cs, "start_result"):
        print(f"  start_result: {cs.start_result}")
    if hasattr(cs, "coro"):
        print(f"  coro: {cs.coro}")
        if cs.coro:
            print(f"  coro state: {getattr(cs.coro, 'gi_frame', 'no gi_frame')}")

    # Try to get result
    try:
        result = cs.result()
        print(f"  result(): {result}")
    except Exception as e:
        print(f"  result() failed: {type(e).__name__}: {e}")


async def investigate_lifecycle():
    """Investigate the full lifecycle of CoroStart"""
    print("=== Sync Coroutine Lifecycle ===")

    # Sync coroutine
    cs_sync = PyCoroStart(sync_coro())
    inspect_corostart_state(cs_sync, "1. After creation (sync)")

    # Await it
    result = await cs_sync
    print(f"\nAwaited result: {result}")
    inspect_corostart_state(cs_sync, "2. After await (sync)")

    print("\n" + "=" * 50)
    print("=== Async Coroutine Lifecycle ===")

    # Async coroutine
    cs_async = PyCoroStart(async_coro())
    inspect_corostart_state(cs_async, "1. After creation (async)")

    # Await it
    result = await cs_async
    print(f"\nAwaited result: {result}")
    inspect_corostart_state(cs_async, "2. After await (async)")


if __name__ == "__main__":
    asyncio.run(investigate_lifecycle())
