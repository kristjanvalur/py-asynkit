#!/usr/bin/env python3
"""
Simple test to measure eager task creation latency with detailed timing.
"""

import asyncio
import time


async def test_coro():
    """Coroutine that prints timestamp immediately."""
    import time
    import asynkit.coroutine
    
    t_coro_start = time.perf_counter_ns()
    
    # Calculate the key metric: time from helper entry to coro start
    helper_entry = asynkit.coroutine._helper_entry_time
    if helper_entry > 0:
        latency_to_coro = (t_coro_start - helper_entry) / 1000  # microseconds
        print(f"  >>> HELPER_TO_CORO_LATENCY: {latency_to_coro:.2f} μs <<<")
    
    print(f"  coro_start: {t_coro_start}")
    return "done"


async def main():
    """Test eager task creation latency."""
    import asynkit

    print("Testing asynkit.create_task with eager_start=True latency")
    print("=" * 60)

    # Run test 5 times
    for i in range(5):
        print(f"\nRun {i + 1}:")
        t_before = time.perf_counter_ns()
        print(f"  before_create_task: {t_before}")
        
        task = asynkit.create_task(test_coro(), eager_start=True)
        
        t_after = time.perf_counter_ns()
        print(f"  after_create_task: {t_after}")
        
        result = await task
        
        t_done = time.perf_counter_ns()
        print(f"  after_await: {t_done}")
        print(f"  Total latency: {(t_after - t_before) / 1000:.2f} μs")


if __name__ == "__main__":
    asyncio.run(main())
