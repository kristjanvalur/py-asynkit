# Eager Task Factory Performance Analysis

This document presents comprehensive performance analysis comparing asynkit's eager task factory implementation with Python 3.12's native `eager_task_factory`.

## Executive Summary

Both eager task factory implementations provide **massive performance improvements** over standard asyncio task creation:

- **Python 3.12 eager_task_factory**: **2,447x faster** startup latency
- **asynkit eager_task_factory**: **1,493x faster** startup latency

While Python's native implementation has a performance edge, asynkit's implementation is competitive and provides the same fundamental benefits across Python 3.10+ versions.

## Test Methodology

### Environment

- **Python Version**: 3.12.11
- **Platform**: Windows
- **Test Date**: October 2025

### Test Design

The benchmark measures two key metrics:

1. **Latency to First Yield**: Time from `create_task()` call until the coroutine reaches its first `await` point
1. **Throughput**: Operations per second for tasks that repeatedly call `asyncio.sleep(0)`

#### Latency Test Coroutine

```python
async def latency_test_coro(creation_time: float) -> str:
    # Record when execution starts (immediately with eager)
    start_execution_time = time.perf_counter()

    # Calculate latency from task creation to execution
    latency = start_execution_time - creation_time
    latency_measurements.append(latency)

    # Some immediate work before yielding
    result = "immediate_work_done"
    await asyncio.sleep(0)  # First yield point
    return result
```

#### Throughput Test

- **100 tasks** each performing **100 sleep operations**
- Total: **10,000 operations** per test run
- Measures complete end-to-end execution time

## Performance Results

### Latency to First Yield (Microseconds)

| Implementation | Mean | Median | Min | Max | Std Dev |
|----------------|------|--------|-----|-----|---------|
| Standard asyncio | **2,263.02** | 2,163.00 | 1,837.30 | 3,124.00 | 364.75 |
| Python 3.12 eager | **0.92** | 0.80 | 0.70 | 25.50 | 1.37 |
| asynkit eager | **1.52** | 0.90 | 0.80 | 366.20 | 11.70 |

### Throughput (Operations/Second)

| Implementation | Ops/sec | Relative Performance |
|----------------|---------|---------------------|
| Standard asyncio | 802,910 | 1.00x (baseline) |
| Python 3.12 eager | 812,896 | 1.01x |
| asynkit eager | 715,707 | 0.89x |

## Key Insights

### 1. Dramatic Latency Reduction

The most significant finding is the **enormous reduction in task startup latency**:

- **Standard asyncio**: ~2.3 milliseconds (due to event loop scheduling)
- **Eager implementations**: \<2 microseconds (immediate execution)

This represents a **three orders of magnitude improvement** for task startup time.

### 2. Competitive Performance

While Python's native implementation is faster, the difference is relatively small:

- **Latency difference**: 0.6 microseconds (1.52 vs 0.92 μs)
- **Throughput difference**: ~12% lower for asynkit

### 3. Consistency Analysis

- **Python 3.12**: More consistent latency (lower standard deviation: 1.37 μs)
- **asynkit**: Slightly more variable latency (std dev: 11.70 μs)
- Both have similar minimum latencies (~0.8 μs)

### 4. When Eager Execution Matters

Eager execution provides the most benefit for:

- **Cache lookups** that might complete immediately
- **Short computation paths** before I/O
- **Microservices** with high task creation rates
- **Real-time applications** sensitive to latency

## Implementation Comparison

### Python 3.12 eager_task_factory

**Advantages:**

- Native C implementation provides optimal performance
- More consistent latency characteristics
- Integrated with asyncio internals
- Global application via `loop.set_task_factory()`

**Limitations:**

- Requires Python 3.12+
- All-or-nothing approach (affects all tasks)

### asynkit eager_task_factory

**Advantages:**

- **Cross-version compatibility** (Python 3.10+)
- **Selective application** possible
- **TaskLikeFuture optimization** for synchronous completion
- **Same API** as Python 3.12 for easy migration

**Tradeoffs:**

- Pure Python implementation overhead
- Slightly higher latency variance
- ~65% slower than native (but still 1,493x faster than standard)

## Usage Recommendations

### Use Python 3.12 eager_task_factory When:

- Running Python 3.12+ exclusively
- Seeking maximum performance
- Applying eager execution globally
- Working with high-frequency task creation

### Use asynkit eager_task_factory When:

- Supporting Python 3.10 or 3.11
- Needing selective eager execution
- Wanting TaskLikeFuture optimizations
- Migrating gradually to eager execution

### Code Examples

#### Python 3.12 Setup

```python
import asyncio

# Global eager execution
loop = asyncio.get_running_loop()
loop.set_task_factory(asyncio.eager_task_factory)

# All tasks now start eagerly
task = asyncio.create_task(my_coroutine())
```

#### asynkit Setup

```python
import asyncio
import asynkit

# Option 1: Global eager execution (compatible API)
loop = asyncio.get_running_loop()
loop.set_task_factory(asynkit.eager_task_factory)

# Option 2: Selective eager execution
task = asynkit.create_task(my_coroutine(), eager_start=True)
```

## Performance Test Execution

To reproduce these results:

```bash
# Switch to Python 3.12
uv sync --python 3.12

# Run the benchmark
uv run python tests/misc/eager_task_factory_benchmark.py
```

The benchmark includes:

- Multiple factory comparisons
- Statistical analysis (mean, median, std dev)
- Throughput measurements
- Per-task eager_start parameter testing (if available)

## Conclusions

1. **Eager execution provides massive benefits** for task startup latency (1,000x+ improvement)

1. **Both implementations are highly effective** at eliminating event loop scheduling delays

1. **asynkit provides excellent cross-version compatibility** while maintaining competitive performance

1. **The choice depends on your constraints**: Use Python 3.12 native for maximum performance, or asynkit for broader compatibility and selective application

1. **Real-world impact**: For applications creating many short-lived tasks, eager execution can significantly reduce overall latency and improve responsiveness

## Future Considerations

- Monitor Python's continued development of eager execution features
- Consider hybrid approaches using both implementations where appropriate
- Evaluate performance impacts in production workloads
- Track improvements in asynkit's implementation efficiency

______________________________________________________________________

*Performance data collected October 2025 using Python 3.12.11 on Windows. Results may vary across platforms and Python versions.*
