#!/usr/bin/env python3
"""
Performance comparison between asynkit's eager task factory and
Python 3.12's native eager_task_factory.

This test measures:
1. Latency to first yield point (immediate execution time)
2. Total throughput for tasks that repeatedly sleep(0)
"""

import asyncio
import statistics
import time
from collections.abc import Callable
from typing import Any

import asynkit

# Test parameters
NUM_TASKS = 100
NUM_SLEEPS_PER_TASK = 100

# Global list to collect latency measurements
latency_measurements = []


async def latency_test_coro(creation_time: float) -> str:
    """Coroutine for latency testing - records time to first yield."""
    # Record the time when we start executing (immediately with eager)
    start_execution_time = time.perf_counter()

    # Some immediate work before yielding
    result = "immediate_work_done"

    # Record latency from creation to first yield
    latency = start_execution_time - creation_time
    latency_measurements.append(latency)

    await asyncio.sleep(0)  # First yield point
    return result


async def throughput_test_coro() -> int:
    """Coroutine for throughput testing - repeatedly sleeps."""
    count = 0
    for _ in range(NUM_SLEEPS_PER_TASK):
        await asyncio.sleep(0)
        count += 1
    return count


class PerformanceTest:
    """Performance testing framework for task factories."""

    def __init__(self, factory_name: str, factory: Callable[..., Any] | None = None):
        self.factory_name = factory_name
        self.factory = factory

    async def setup_factory(self):
        """Set up the task factory for testing."""
        loop = asyncio.get_running_loop()
        self.old_factory = loop.get_task_factory()
        if self.factory is not None:
            loop.set_task_factory(self.factory)

    async def cleanup_factory(self):
        """Restore the original task factory."""
        loop = asyncio.get_running_loop()
        loop.set_task_factory(self.old_factory)

    async def measure_latency(self, num_iterations: int = 1000) -> list[float]:
        """Measure latency from create_task() to first yield point."""
        global latency_measurements
        latency_measurements.clear()  # Reset measurements

        tasks = []
        for _ in range(num_iterations):
            # Record creation time and pass it to the coroutine
            creation_time = time.perf_counter()
            task = asyncio.create_task(latency_test_coro(creation_time))
            tasks.append(task)

        # Wait for all tasks to complete
        await asyncio.gather(*tasks)

        # Return the collected latency measurements
        return latency_measurements.copy()

    async def measure_throughput(self) -> float:
        """Measure throughput for many tasks doing repeated sleeps."""
        start_time = time.perf_counter()

        # Create all tasks
        tasks = [asyncio.create_task(throughput_test_coro()) for _ in range(NUM_TASKS)]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)

        end_time = time.perf_counter()
        total_time = end_time - start_time

        # Verify all tasks completed correctly
        assert all(result == NUM_SLEEPS_PER_TASK for result in results)

        # Calculate operations per second
        total_operations = NUM_TASKS * NUM_SLEEPS_PER_TASK
        throughput = total_operations / total_time

        return throughput

    async def run_tests(self) -> dict[str, Any]:
        """Run all performance tests and return results."""
        await self.setup_factory()

        try:
            print(f"\n=== Testing {self.factory_name} ===")

            # Measure latency
            print("Measuring latency to first yield...")
            latencies = await self.measure_latency()

            latency_stats = {
                "mean": statistics.mean(latencies)
                * 1_000_000,  # Convert to microseconds
                "median": statistics.median(latencies) * 1_000_000,
                "min": min(latencies) * 1_000_000,
                "max": max(latencies) * 1_000_000,
                "stdev": statistics.stdev(latencies) * 1_000_000,
            }

            print(f"  Mean latency: {latency_stats['mean']:.2f} μs")
            print(f"  Median latency: {latency_stats['median']:.2f} μs")
            print(f"  Min latency: {latency_stats['min']:.2f} μs")
            print(f"  Max latency: {latency_stats['max']:.2f} μs")
            print(f"  Std dev: {latency_stats['stdev']:.2f} μs")

            # Measure throughput
            print(
                f"\nMeasuring throughput ({NUM_TASKS} tasks × "
                f"{NUM_SLEEPS_PER_TASK} sleeps)..."
            )
            throughput = await self.measure_throughput()

            print(f"  Throughput: {throughput:.0f} operations/second")

            return {
                "factory_name": self.factory_name,
                "latency": latency_stats,
                "throughput": throughput,
            }

        finally:
            await self.cleanup_factory()


async def compare_eager_start_parameter():
    """Test Python 3.12's per-task eager_start parameter if available."""
    import inspect

    # Check if eager_start parameter is available
    sig = inspect.signature(asyncio.create_task)
    if "eager_start" not in sig.parameters:
        print("\n=== Python 3.12 eager_start Parameter ===")
        print("  eager_start parameter not available in this Python version")
        print("  (eager_start was added in Python 3.12.0a7+)")
        return

    print("\n=== Testing Python 3.12 eager_start Parameter ===")

    global latency_measurements

    # Test with eager_start=True
    latency_measurements.clear()
    creation_time = time.perf_counter()
    task_eager = asyncio.create_task(latency_test_coro(creation_time), eager_start=True)
    await task_eager
    eager_latency = latency_measurements[0] if latency_measurements else 0

    # Test with eager_start=False
    latency_measurements.clear()
    creation_time = time.perf_counter()
    task_lazy = asyncio.create_task(latency_test_coro(creation_time), eager_start=False)
    await task_lazy
    lazy_latency = latency_measurements[0] if latency_measurements else 0

    print(f"  eager_start=True latency: {eager_latency * 1_000_000:.2f} μs")
    print(f"  eager_start=False latency: {lazy_latency * 1_000_000:.2f} μs")
    if lazy_latency > 0:
        print(f"  Speedup: {lazy_latency / eager_latency:.1f}x")


async def test_asynkit_create_task_eager():
    """Test asynkit's create_task with eager_start=True."""
    print("\n=== Testing asynkit.create_task(eager_start=True) ===")

    global latency_measurements

    # Test with eager_start=True
    latency_measurements.clear()
    creation_time = time.perf_counter()
    task_eager = asynkit.create_task(latency_test_coro(creation_time), eager_start=True)
    await task_eager
    eager_latency = latency_measurements[0] if latency_measurements else 0

    # Test with eager_start=False
    latency_measurements.clear()
    creation_time = time.perf_counter()
    task_lazy = asynkit.create_task(latency_test_coro(creation_time), eager_start=False)
    await task_lazy
    lazy_latency = latency_measurements[0] if latency_measurements else 0

    print(f"  asynkit eager_start=True latency: {eager_latency * 1_000_000:.2f} μs")
    print(f"  asynkit eager_start=False latency: {lazy_latency * 1_000_000:.2f} μs")
    if lazy_latency > 0:
        print(f"  Speedup: {lazy_latency / eager_latency:.1f}x")


async def main():
    """Run all performance comparisons."""
    print("Python 3.12 vs asynkit Eager Task Factory Performance Comparison")
    print("=" * 70)
    print("Test configuration:")
    print("  Latency test: 1000 iterations")
    print(f"  Throughput test: {NUM_TASKS} tasks × {NUM_SLEEPS_PER_TASK} sleeps")

    # Test configurations
    test_configs = [
        PerformanceTest("Standard asyncio (no eager)", None),
        PerformanceTest("Python 3.12 eager_task_factory", asyncio.eager_task_factory),
        PerformanceTest("asynkit eager_task_factory", asynkit.eager_task_factory),
    ]

    # Run all tests
    results = []
    for test in test_configs:
        result = await test.run_tests()
        results.append(result)

    # Test per-task eager parameters
    await compare_eager_start_parameter()
    await test_asynkit_create_task_eager()

    # Summary comparison
    print("\n" + "=" * 70)
    print("SUMMARY COMPARISON")
    print("=" * 70)

    print("\nLatency to First Yield (microseconds):")
    print(f"{'Factory':<30} {'Mean':<10} {'Median':<10} {'Min':<10} {'Max':<10}")
    print("-" * 70)
    for result in results:
        lat = result["latency"]
        print(
            f"{result['factory_name']:<30} "
            f"{lat['mean']:<10.2f} {lat['median']:<10.2f} "
            f"{lat['min']:<10.2f} {lat['max']:<10.2f}"
        )

    print("\nThroughput (operations/second):")
    print(f"{'Factory':<30} {'Ops/sec':<15} {'Relative':<10}")
    print("-" * 55)
    baseline_throughput = results[0]["throughput"]
    for result in results:
        throughput = result["throughput"]
        relative = throughput / baseline_throughput
        print(f"{result['factory_name']:<30} {throughput:<15.0f} {relative:<10.2f}x")

    # Calculate improvements
    if len(results) >= 3:
        python_eager = results[1]
        asynkit_eager = results[2]

        print("Key Insights:")
        baseline_latency = results[0]["latency"]["mean"]
        python_latency = python_eager["latency"]["mean"]
        asynkit_latency = asynkit_eager["latency"]["mean"]

        print(
            f"  Python 3.12 eager latency improvement: "
            f"{baseline_latency / python_latency:.1f}x"
        )
        print(
            f"  asynkit eager latency improvement: "
            f"{baseline_latency / asynkit_latency:.1f}x"
        )
        print(
            f"  Python 3.12 vs asynkit latency ratio: "
            f"{asynkit_latency / python_latency:.2f}"
        )
        print(
            f"  Python 3.12 vs asynkit throughput ratio: "
            f"{asynkit_eager['throughput'] / python_eager['throughput']:.2f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
