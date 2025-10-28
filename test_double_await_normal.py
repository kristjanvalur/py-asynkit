#!/usr/bin/env python3
"""
Test what happens when you await a normal coroutine twice
"""
import asyncio

async def sync_coro():
    return 42

async def test_double_await():
    coro = sync_coro()
    print(f"First await...")
    result = await coro
    print(f"  Result: {result}")
    print(f"Second await...")
    try:
        result2 = await coro
        print(f"  Second result: {result2}")
    except Exception as e:
        print(f"  Second await raised: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_double_await())
