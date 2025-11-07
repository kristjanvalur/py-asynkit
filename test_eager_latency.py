#!/usr/bin/env python3
"""
Simple test to measure eager task creation latency with detailed timing.
"""

import asyncio
import time
import asynkit
import asynkit.coroutine


async def test_coro():
    """Coroutine that records timestamp immediately."""
    t_coro_start = time.perf_counter_ns()
    
    # Store the coro start time in the module so we can read it later
    asynkit.coroutine._coro_start_time = t_coro_start
    
    return "done"


async def main():
    """Test eager task creation latency."""
    print("Testing asynkit.create_task with eager_start=True latency")
    print("=" * 60)

    # Run test 5 times
    for i in range(5):
        print(f"\nRun {i + 1}:")
        t_before = time.perf_counter_ns()
        
        task = asynkit.create_task(test_coro(), eager_start=True)
        
        t_after = time.perf_counter_ns()
        
        # Calculate the key metric: time from helper entry to coro start
        helper_entry = asynkit.coroutine._helper_entry_time
        coro_start = asynkit.coroutine._coro_start_time
        timing_data = asynkit.coroutine._timing_data
        
        if helper_entry > 0 and coro_start > 0:
            latency_to_coro = (coro_start - helper_entry) / 1000  # microseconds
            print(f"  >>> HELPER_TO_CORO_LATENCY: {latency_to_coro:.2f} μs <<<")
        
        # Print timing breakdown
        for key, value in timing_data.items():
            if key == 'helper_entry':
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value:.2f} μs")
        
        result = await task
        
        print(f"  Total latency (measured): {(t_after - t_before) / 1000:.2f} μs")


if __name__ == "__main__":
    asyncio.run(main())
