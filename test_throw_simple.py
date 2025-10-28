#!/usr/bin/env python3
"""
Test script for throw method functionality
"""

import asyncio
import asynkit


async def test_coro():
    try:
        await asyncio.sleep(0)
        return 'should not reach here'
    except ValueError as e:
        return f'caught: {e}'


def test_throw_c_extension():
    """Test throw method with C extension"""
    print("=== Testing C extension throw ===")
    
    cs = asynkit._cext.CoroStart(test_coro())
    print(f"Initial done(): {cs.done()}")
    
    if not cs.done():
        # Get the wrapper and test throw
        wrapper = cs.__await__()
        try:
            result = wrapper.throw(ValueError('test exception'))
            print(f'Throw returned: {result}')
        except StopIteration as e:
            print(f'Coroutine completed with: {e.value}')
        except Exception as e:
            print(f'Throw failed: {e}')
    else:
        print("Coroutine already done")


def test_throw_python():
    """Test throw method with Python implementation"""
    print("\n=== Testing Python throw ===")
    
    cs = asynkit.CoroStart(test_coro())
    print(f"Initial done(): {cs.done()}")
    
    if not cs.done():
        try:
            # Python version's athrow is async, but throw is sync
            result = cs.throw(ValueError('test exception'))
            print(f'Python throw result: {result}')
        except Exception as e:
            print(f'Python throw failed: {e}')
    else:
        print("Coroutine already done")


if __name__ == "__main__":
    test_throw_c_extension()
    test_throw_python()