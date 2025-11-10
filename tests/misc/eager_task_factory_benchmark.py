#!/usr/bin/env python3
"""
Performance comparison between asynkit's eager task factory and
Python 3.12's native eager_task_factory.

This test measures:
1. Latency to first yield point (immediate execution time)
2. Total throughput for tasks that repeatedly sleep(0)
"""

import asyncio
import contextlib
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

import asynkit


def find_outlier_indices_iqr(
    data: list[float], iqr_multiplier: float = 1.5
) -> set[int]:
    """
    Find outlier indices using Interquartile Range (IQR) method.

    More robust than sigma-based filtering for non-normal distributions
    common in performance data (right-skewed, heavy tails).

    Args:
        data: List of measurements to analyze
        iqr_multiplier: Multiplier for IQR to define outlier bounds (1.5 is standard)

    Returns:
        set: Indices of outlier values
    """
    if len(data) <= 4:  # Need at least 4 points for meaningful IQR
        return set()

    # Calculate quartiles
    sorted_data = sorted(data)
    n = len(sorted_data)

    # Use standard quartile calculation (method matches numpy/pandas)
    q1_idx = (n - 1) * 0.25
    q3_idx = (n - 1) * 0.75

    # Linear interpolation for non-integer indices
    def interpolate_quartile(idx: float) -> float:
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        weight = idx - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

    q1 = interpolate_quartile(q1_idx)
    q3 = interpolate_quartile(q3_idx)
    iqr = q3 - q1

    if iqr == 0:  # All values identical
        return set()

    # Define outlier bounds
    lower_bound = q1 - iqr_multiplier * iqr
    upper_bound = q3 + iqr_multiplier * iqr

    # Find outlier indices
    outlier_indices = set()
    for i, value in enumerate(data):
        if value < lower_bound or value > upper_bound:
            outlier_indices.add(i)

    return outlier_indices


def filter_outliers_iqr(
    data: list[float], iqr_multiplier: float = 1.5
) -> tuple[list[float], int]:
    """
    Filter outliers using Interquartile Range (IQR) method.

    DEPRECATED: Use find_outlier_indices_iqr() for index-based filtering
    to ensure consistent run-level filtering across multiple metrics.

    Args:
        data: List of measurements to filter
        iqr_multiplier: Multiplier for IQR to define outlier bounds (1.5 is standard)

    Returns:
        tuple: (filtered_data, num_outliers_removed)
    """
    outlier_indices = find_outlier_indices_iqr(data, iqr_multiplier)
    filtered = [data[i] for i in range(len(data)) if i not in outlier_indices]
    return filtered, len(outlier_indices)


# Test parameters
NUM_TASKS = 100
NUM_SLEEPS_PER_TASK = 100
NUM_BENCHMARK_RUNS = 15  # Number of consecutive runs (first run discarded as warmup)
WARMUP_RUNS = 1  # Number of initial runs to discard

# Global list to collect latency measurements
latency_measurements = []


@contextlib.contextmanager
def corostart_implementation(implementation_class):
    """Context manager to temporarily override CoroStart implementation."""
    import asynkit.coroutine

    original_corostart = asynkit.coroutine.CoroStart
    try:
        # Override the CoroStart class
        asynkit.coroutine.CoroStart = implementation_class
        yield
    finally:
        # Restore original
        asynkit.coroutine.CoroStart = original_corostart


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
        # Non-eager execution is when no factory is set (standard asyncio)
        self.is_non_eager = factory is None

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
        """Measure throughput for tasks that repeatedly sleep(0)."""
        start_time = time.perf_counter()

        # Create and run tasks
        tasks = []
        for _ in range(NUM_TASKS):
            task = asyncio.create_task(throughput_test_coro())
            tasks.append(task)

        # Wait for all tasks to complete
        await asyncio.gather(*tasks)

        end_time = time.perf_counter()
        total_time = end_time - start_time

        # Calculate total operations and throughput
        total_operations = NUM_TASKS * NUM_SLEEPS_PER_TASK
        throughput = total_operations / total_time

        return throughput

    async def run_tests(self) -> dict[str, Any]:
        """Run all performance tests multiple times and return statistical results."""
        await self.setup_factory()

        try:
            print(f"\n=== Testing {self.factory_name} ===")
            print(
                f"Running {NUM_BENCHMARK_RUNS + WARMUP_RUNS} runs "
                f"(discarding first {WARMUP_RUNS} as warmup)..."
            )

            all_latency_results = []
            all_throughput_results = []

            # Run multiple benchmark iterations
            for run_num in range(NUM_BENCHMARK_RUNS + WARMUP_RUNS):
                is_warmup = run_num < WARMUP_RUNS
                run_label = (
                    "warmup" if is_warmup else f"run {run_num - WARMUP_RUNS + 1}"
                )

                if not is_warmup:
                    print(f"  {run_label}...", end=" ", flush=True)

                # Measure latency for this run
                latencies = await self.measure_latency()

                # For non-eager execution, adjust latency
                adjustment_factor = 1000 if self.is_non_eager else 1
                adjusted_latencies = [lat / adjustment_factor for lat in latencies]

                # Filter outliers before calculating statistics using IQR method
                filtered_latencies, num_outliers = filter_outliers_iqr(
                    adjusted_latencies, iqr_multiplier=1.5
                )

                # Calculate statistics for this run (using filtered data)
                run_latency_stats = {
                    "mean": statistics.mean(filtered_latencies) * 1_000_000,
                    "median": statistics.median(filtered_latencies) * 1_000_000,
                    "min": min(filtered_latencies) * 1_000_000,
                    "max": max(filtered_latencies) * 1_000_000,
                    "std_dev": statistics.stdev(filtered_latencies) * 1_000_000,
                    "outliers_removed": num_outliers,
                    "total_samples": len(adjusted_latencies),
                }

                # Measure throughput for this run
                throughput = await self.measure_throughput()

                if is_warmup:
                    print("  Warmup run completed (discarded)")
                else:
                    outlier_info = ""
                    if run_latency_stats["outliers_removed"] > 0:
                        outlier_info = f" ({run_latency_stats['outliers_removed']} outliers filtered)"
                    print(
                        f"latency {run_latency_stats['mean']:.2f}μs, "
                        f"throughput {throughput:.0f} ops/s{outlier_info}"
                    )
                    all_latency_results.append(run_latency_stats)
                    all_throughput_results.append(throughput)

            # Extract cross-run data
            mean_latencies = [result["mean"] for result in all_latency_results]
            median_latencies = [result["median"] for result in all_latency_results]
            min_latencies = [result["min"] for result in all_latency_results]
            max_latencies = [result["max"] for result in all_latency_results]
            std_dev_latencies = [result["std_dev"] for result in all_latency_results]

            # Apply IQR filtering to identify outlier runs across both latency and throughput
            latency_outlier_indices = find_outlier_indices_iqr(mean_latencies)
            throughput_outlier_indices = find_outlier_indices_iqr(
                all_throughput_results
            )

            # Union of outlier indices - a run is excluded if it's an outlier in ANY metric
            all_outlier_indices = latency_outlier_indices | throughput_outlier_indices

            # Create filtered datasets using the same set of "good runs"
            good_run_indices = [
                i
                for i in range(len(all_latency_results))
                if i not in all_outlier_indices
            ]

            filtered_mean_latencies = [mean_latencies[i] for i in good_run_indices]
            filtered_median_latencies = [median_latencies[i] for i in good_run_indices]
            filtered_min_latencies = [min_latencies[i] for i in good_run_indices]
            filtered_max_latencies = [max_latencies[i] for i in good_run_indices]
            filtered_std_dev_latencies = [
                std_dev_latencies[i] for i in good_run_indices
            ]
            filtered_throughput = [all_throughput_results[i] for i in good_run_indices]

            # Warn about cross-run outliers (shouldn't happen with good methodology)
            num_outlier_runs = len(all_outlier_indices)
            if num_outlier_runs > 0:
                print(
                    f"\n  WARNING: {num_outlier_runs} outlier runs detected and excluded!"
                )
                print(f"    Latency outliers: {len(latency_outlier_indices)} runs")
                print(
                    f"    Throughput outliers: {len(throughput_outlier_indices)} runs"
                )
                print(
                    f"    Total excluded runs: {num_outlier_runs}/{len(all_latency_results)}"
                )
                print(
                    "    This may indicate system interference or measurement issues."
                )
                if latency_outlier_indices:
                    print(
                        f"    Latency outlier run indices: {sorted(latency_outlier_indices)}"
                    )
                if throughput_outlier_indices:
                    print(
                        f"    Throughput outlier run indices: {sorted(throughput_outlier_indices)}"
                    )

            # Aggregate latency statistics across runs (using same filtered runs for all metrics)
            final_latency_stats = {
                "mean": statistics.mean(filtered_mean_latencies),
                "mean_std": statistics.stdev(filtered_mean_latencies)
                if len(filtered_mean_latencies) > 1
                else 0,
                "median": statistics.mean(filtered_median_latencies),
                "median_std": statistics.stdev(filtered_median_latencies)
                if len(filtered_median_latencies) > 1
                else 0,
                "min": min(filtered_min_latencies) if filtered_min_latencies else 0,
                "max": max(filtered_max_latencies) if filtered_max_latencies else 0,
                "std_dev": statistics.mean(filtered_std_dev_latencies)
                if filtered_std_dev_latencies
                else 0,
                "runs": len(all_latency_results),
                "runs_used": len(good_run_indices),  # Track how many runs used
            }

            # Aggregate throughput statistics (using same filtered runs)
            final_throughput = statistics.mean(filtered_throughput)
            throughput_std = (
                statistics.stdev(filtered_throughput)
                if len(filtered_throughput) > 1
                else 0
            )

            # Calculate total outliers filtered
            total_outliers = sum(
                result.get("outliers_removed", 0) for result in all_latency_results
            )
            total_samples = sum(
                result.get("total_samples", 0) for result in all_latency_results
            )
            outlier_percentage = (
                (total_outliers / total_samples * 100) if total_samples > 0 else 0
            )

            # Display final results
            runs_info = (
                f"{final_latency_stats['runs_used']}/{final_latency_stats['runs']} runs"
            )
            if final_latency_stats["runs_used"] < final_latency_stats["runs"]:
                runs_info += " (cross-run outliers filtered)"

            print(f"\nFinal Results (averaged over {runs_info}):")
            print(
                f"  Mean latency: {final_latency_stats['mean']:.2f} ± {final_latency_stats['mean_std']:.2f} μs"
            )
            if self.is_non_eager:
                print("    (adjusted for per-task contribution in non-eager execution)")
                print("    (minimum latency - increases with work done before await)")
            print(
                f"  Median latency: {final_latency_stats['median']:.2f} ± {final_latency_stats['median_std']:.2f} μs"
            )
            print(f"  Min latency: {final_latency_stats['min']:.2f} μs")
            print(f"  Max latency: {final_latency_stats['max']:.2f} μs")
            print(f"  Std dev: {final_latency_stats['std_dev']:.2f} μs")
            print(
                f"  Throughput: {final_throughput:.0f} ± {throughput_std:.0f} operations/second"
            )
            if total_outliers > 0:
                print(
                    f"  Per-run outliers filtered: {total_outliers}/{total_samples} ({outlier_percentage:.1f}%) using IQR method (1.5×IQR)"
                )

            return {
                "factory_name": self.factory_name,
                "latency": final_latency_stats,
                "throughput": final_throughput,
                "throughput_std": throughput_std,
                "num_runs": final_latency_stats["runs"],
            }

        finally:
            await self.cleanup_factory()


class AsynkitImplementationTest(PerformanceTest):
    """Performance test for different asynkit CoroStart implementations."""

    def __init__(self, factory_name: str, corostart_class):
        super().__init__(factory_name, asynkit.eager_task_factory)
        self.corostart_class = corostart_class
        self.corostart_context = None

    async def setup_factory(self):
        """Set up both factory and CoroStart implementation."""
        await super().setup_factory()
        # Set up CoroStart override
        self.corostart_context = corostart_implementation(self.corostart_class)
        self.corostart_context.__enter__()

    async def cleanup_factory(self):
        """Restore both factory and CoroStart implementation."""
        if self.corostart_context:
            self.corostart_context.__exit__(None, None, None)
        await super().cleanup_factory()

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


async def compare_eager_start_parameter():
    """Test Python 3.14's per-task eager_start parameter if available."""

    # Check if eager_start parameter is available by testing it
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    # Test if eager_start actually works (it may be handled via **kwargs)
    try:

        async def test_coro():
            return "test"

        # Try creating a task with eager_start parameter
        task = asyncio.create_task(test_coro(), eager_start=True)
        await task
        eager_start_available = True
    except TypeError:
        eager_start_available = False

    if not eager_start_available:
        print(f"\n=== Python {python_version} eager_start Parameter ===")
        print("  eager_start parameter not available in this Python version")
        print("  (eager_start was added to asyncio.create_task() in Python 3.14)")
        return

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"\n=== Testing Python {python_version} eager_start Parameter ===")

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
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(
        f"Python {python_version} vs asynkit Eager Task Factory Performance Comparison"
    )
    print("=" * 70)
    print("Test configuration:")
    print(f"  Python version: {sys.version}")
    print(f"  Benchmark runs: {NUM_BENCHMARK_RUNS} (+ {WARMUP_RUNS} warmup)")
    print("  Latency test: 1000 iterations per run")
    print(
        f"  Throughput test: {NUM_TASKS} tasks × {NUM_SLEEPS_PER_TASK} sleeps per run"
    )

    # Test configurations
    test_configs = [
        PerformanceTest("Standard asyncio (no eager)", None),
    ]

    # Only test Python's eager_task_factory if it exists (Python 3.12+)
    if hasattr(asyncio, "eager_task_factory"):
        test_configs.append(
            PerformanceTest(
                f"Python {python_version} eager_task_factory",
                asyncio.eager_task_factory,
            )
        )
    else:
        print(
            f"Note: asyncio.eager_task_factory not available in Python {python_version}"
        )
        print("      (asyncio.eager_task_factory was added in Python 3.12)")

    # Add C extension vs Python implementation comparison for asynkit
    if hasattr(asynkit.coroutine, "_PyCoroStart"):
        test_configs.append(
            AsynkitImplementationTest(
                "asynkit (Pure Python)", asynkit.coroutine._PyCoroStart
            )
        )

    if (
        hasattr(asynkit.coroutine, "_CCoroStart")
        and asynkit.coroutine._CCoroStart is not None
    ):
        test_configs.append(
            AsynkitImplementationTest(
                "asynkit (C Extension)", asynkit.coroutine._CCoroStart
            )
        )

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
    print("Note: Non-eager latency adjusted for per-task contribution")
    print("      Non-eager latency shows minimum possible delay (tight creation loop)")
    print("      Real-world non-eager latency increases with work done before await")
    print("      Eager latency remains consistent regardless of intervening work")
    print(
        f"      All values averaged over {NUM_BENCHMARK_RUNS} runs with two-level IQR filtering (±std dev)"
    )

    print("\nLatency to First Yield (microseconds):")
    print(
        f"{'Factory':<30} {'Mean ± Std':<15} {'Median ± Std':<15} {'Min':<10} {'Max':<10}"
    )
    print("-" * 80)
    for result in results:
        lat = result["latency"]
        mean_str = f"{lat['mean']:.1f}±{lat['mean_std']:.1f}"
        median_str = f"{lat['median']:.1f}±{lat['median_std']:.1f}"
        print(
            f"{result['factory_name']:<30} "
            f"{mean_str:<15} "
            f"{median_str:<15} "
            f"{lat['min']:<10.1f} {lat['max']:<10.1f}"
        )

    print("\nThroughput (operations/second):")
    print(f"{'Factory':<30} {'Ops/sec ± Std':<20} {'Relative':<10}")
    print("-" * 60)
    baseline_throughput = results[0]["throughput"]
    for result in results:
        throughput = result["throughput"]
        throughput_std = result["throughput_std"]
        relative = throughput / baseline_throughput
        throughput_str = f"{throughput:.0f}±{throughput_std:.0f}"
        print(f"{result['factory_name']:<30} {throughput_str:<20} {relative:<10.2f}x")

    # Calculate improvements
    print("Performance Analysis:")
    baseline_latency = results[0]["latency"]["mean"]

    # Find Python eager_task_factory result if it exists
    python_eager = None
    for result in results:
        if "eager_task_factory" in result["factory_name"]:
            python_eager = result
            break

    if python_eager:
        python_latency = python_eager["latency"]["mean"]
        print(
            f"  Python {python_version} eager latency improvement: "
            f"{baseline_latency / python_latency:.1f}x"
        )
    else:
        print(
            f"  Python {python_version} eager_task_factory not available for comparison"
        )

        # Show C extension vs Python implementation comparison if available
        c_ext_result = None
        py_result = None
        for result in results:
            if "C Extension" in result["factory_name"]:
                c_ext_result = result
            elif "Pure Python" in result["factory_name"]:
                py_result = result

        if c_ext_result and py_result:
            c_latency = c_ext_result["latency"]["mean"]
            py_latency = py_result["latency"]["mean"]
            c_throughput = c_ext_result["throughput"]
            py_throughput = py_result["throughput"]

            print("\nC Extension vs Pure Python asynkit:")
            print(f"  C extension latency improvement: {py_latency / c_latency:.1f}x")
            print(
                f"  C extension throughput improvement: {c_throughput / py_throughput:.2f}x"
            )
            print(
                f"  Performance consistency (C vs Python std dev): "
                f"{c_ext_result['latency']['std_dev']:.1f}μs vs {py_result['latency']['std_dev']:.1f}μs"
            )


if __name__ == "__main__":
    asyncio.run(main())
