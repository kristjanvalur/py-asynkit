#!/usr/bin/env python3

import asyncio
import asynkit


async def test_simple_case():
    """Test a simple async case to debug the issue"""

    async def simple_coro():
        await asyncio.sleep(0)
        return "simple result"

    print("=== Testing simple async case ===")
    cs = asynkit._cext.CoroStart(simple_coro())
    print(f"Initial done(): {cs.done()}")
    print(
        f"s_value is None: {cs.s_value is None if hasattr(cs, 's_value') else 'no s_value attr'}"
    )
    print(
        f"s_exc_type is None: {cs.s_exc_type is None if hasattr(cs, 's_exc_type') else 'no s_exc_type attr'}"
    )

    if not cs.done():
        print("Coroutine is not done, attempting to await...")
        result = await cs
        print(f"Result: {result}")
    else:
        result = cs.result()
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(test_simple_case())
