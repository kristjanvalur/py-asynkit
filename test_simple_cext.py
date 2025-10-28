"""
Simple test for C extension CoroStart - step by step debugging

This tests the basic iterator interface without any fancy features.
"""

import asyncio
import asynkit
from asynkit.coroutine import _HAVE_C_EXTENSION


async def simple_test():
    """Test basic C extension functionality step by step"""

    print(f"C extension available: {_HAVE_C_EXTENSION}")

    # Test 1: Simple coroutine that suspends once
    async def simple_coro():
        print("  Coroutine started")
        await asyncio.sleep(0)  # Suspend once
        print("  Coroutine resumed")
        return "simple_result"

    print("\n=== Test 1: Simple coroutine ===")

    # Direct test with C extension if available
    if _HAVE_C_EXTENSION:
        try:
            from asynkit._cext import CoroStart as CCoroStart

            print("Testing C implementation directly...")

            # Create C CoroStart
            c_start = CCoroStart(simple_coro())
            print(f"  C CoroStart created: {type(c_start)}")

            # Check if it's done (should not be for simple_coro)
            done = c_start.done()
            print(f"  Done after creation: {done}")

            if done:
                result = c_start.result()
                print(f"  Immediate result: {result}")
            else:
                print("  Awaiting C CoroStart...")
                result = await c_start
                print(f"  Awaited result: {result}")

        except Exception as e:
            print(f"  C extension failed: {e}")
            import traceback

            traceback.print_exc()

    # Test with regular asynkit.CoroStart (may use C or Python)
    print("\nTesting via asynkit.CoroStart...")
    try:
        start = asynkit.CoroStart(simple_coro())
        print(f"  CoroStart created: {type(start)}")

        done = start.done()
        print(f"  Done after creation: {done}")

        if done:
            result = start.result()
            print(f"  Immediate result: {result}")
        else:
            print("  Awaiting CoroStart...")
            result = await start
            print(f"  Awaited result: {result}")

    except Exception as e:
        print(f"  asynkit.CoroStart failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(simple_test())
