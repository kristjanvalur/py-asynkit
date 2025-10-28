#!/usr/bin/env python3

import asyncio
import asynkit


async def test_first_send_assertion():
    """Test that the first send() call must be None"""

    async def simple_coro():
        await asyncio.sleep(0)
        return 42

    # Test C extension
    cs_c = asynkit._cext.CoroStart(simple_coro())
    wrapper_c = cs_c.__await__()

    # First send should work with None
    try:
        result = wrapper_c.send(None)
        print(f"C extension - First send(None): {type(result)} (expected awaitable)")
    except Exception as e:
        print(f"C extension - First send(None) failed: {type(e).__name__}: {e}")

    # Try to violate the protocol with non-None first send
    cs_c2 = asynkit._cext.CoroStart(simple_coro())
    wrapper_c2 = cs_c2.__await__()

    try:
        result = wrapper_c2.send("invalid")
        print(
            f"C extension - ERROR: send('invalid') should have failed but got: {result}"
        )
    except TypeError as e:
        print(
            f"C extension - send('invalid') correctly raised: {type(e).__name__}: {e}"
        )
    except Exception as e:
        print(
            f"C extension - send('invalid') raised unexpected: {type(e).__name__}: {e}"
        )

    print()

    # Compare with native coroutine behavior
    async def test_native():
        await asyncio.sleep(0)
        return 42

    # Test native coroutine
    native_coro = test_native()
    native_iter = native_coro.__await__()

    try:
        result = native_iter.send("invalid")
        print(
            f"Native coroutine - ERROR: send('invalid') should have failed but got: {result}"
        )
    except TypeError as e:
        print(
            f"Native coroutine - send('invalid') correctly raised: {type(e).__name__}: {e}"
        )
    except Exception as e:
        print(f"Native coroutine - send('invalid') raised: {type(e).__name__}: {e}")

    # Clean up
    native_coro.close()


if __name__ == "__main__":
    asyncio.run(test_first_send_assertion())
