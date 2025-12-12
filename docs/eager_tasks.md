# Eager Task Execution: Python 3.12+ vs asynkit

In version 3.12, Python introduced native eager task execution. Here's how it compares with asynkit's eager execution features, which have been solving this problem since 2022.

## Timeline and History

**asynkit's eager execution** was developed and released in **2022**, predating Python's native support by more than a year. It was designed to address the latency issues in asyncio by allowing coroutines to start executing immediately.

**Python 3.12's eager_task_factory** was released in **October 2023**, providing native support for eager task execution. This feature was developed based on similar concepts and the success of libraries like asynkit that demonstrated the value of eager execution.

## Overview

Both Python's `asyncio.eager_task_factory` and asynkit's `eager()` address the same fundamental problem: reducing latency by starting coroutines immediately rather than deferring execution to the next event loop iteration. However, they take different approaches and offer different levels of control.

### Key Philosophical Difference

- **Python's approach is Task-centric**: Eager execution is implemented at the Task level. Whether using `set_task_factory(eager_task_factory)` or the `eager_start` parameter, the focus is on making Task objects execute eagerly.

- **asynkit's approach is coroutine-centric**: Eager execution happens at the coroutine level. The `eager()` function starts a coroutine immediately and only creates a Task if the coroutine blocks. If the coroutine completes synchronously, no Task is created at all.

## Python's Built-in Eager Tasks (Python 3.12+)

### Introduction

Python 3.12 introduced native support for eager task execution through the `asyncio.eager_task_factory`. This feature was developed to optimize asyncio performance and improve the predictability of task scheduling.

### References

- **GitHub Issue**: [#97696 - Add eager task creation API to asyncio](https://github.com/python/cpython/issues/97696)
- **Performance Discussion**: [#104144 - Leverage eager tasks to optimize asyncio gather & TaskGroups](https://github.com/python/cpython/issues/104144)
- **Official Documentation**: [asyncio.eager_task_factory](https://docs.python.org/3/library/asyncio-task.html)

### How It Works

Python's eager task factory modifies how tasks are created at the event loop level:

```python
import asyncio

# Enable eager task execution globally
asyncio.get_event_loop().set_task_factory(asyncio.eager_task_factory)


async def my_coroutine():
    print("Starting immediately!")
    await asyncio.sleep(1)
    return "done"


async def main():
    # With eager_task_factory, this task starts immediately
    task = asyncio.create_task(my_coroutine())
    print("Task created")
    await task


asyncio.run(main())
```

**Behavior**:

- Tasks begin executing **synchronously** during `create_task()` call
- Execution continues until the coroutine **yields control** (e.g., awaits a pending future)
- Only at that point is the task scheduled onto the event loop
- If the coroutine completes without blocking, no event loop scheduling occurs

**Performance Impact**: Tests have shown up to 50% performance improvements in async-heavy workloads, primarily by eliminating the overhead of unnecessary event loop scheduling for short-lived coroutines.

### Two Approaches to Enable Eager Execution

Python 3.12 provides two ways to enable eager task execution:

**1. Global Task Factory** - Enables eager execution for all tasks in the event loop:

```python
import asyncio

# Set the eager task factory globally
asyncio.get_event_loop().set_task_factory(asyncio.eager_task_factory)


async def my_coroutine():
    print("Starting immediately!")
    await asyncio.sleep(1)
    return "done"


async def main():
    # All tasks now start eagerly
    task = asyncio.create_task(my_coroutine())
    await task


asyncio.run(main())
```

Use this when you want to optimize the execution model wholesale, enabling eager execution for all tasks throughout your application.

**2. Per-Task eager_start Parameter** - Selective eager execution for specific tasks:

```python
import asyncio


async def my_coroutine():
    print("Starting immediately!")
    await asyncio.sleep(1)
    return "done"


async def main():
    # Only this specific task starts eagerly
    task = asyncio.create_task(my_coroutine(), eager_start=True)
    print("Task created")
    await task


asyncio.run(main())
```

Use this for fine-grained control, selectively making specific tasks eager while keeping others lazy, without changing the global task factory.

### Limitations

1. **Both approaches always create a Task object**: Even if the coroutine completes synchronously, a Task is created
2. **Compatibility**: May break code that relies on deferred task execution semantics
3. **Python 3.12+ Only**: Not available in earlier Python versions
4. **`asyncio.timeout()` incompatibility**: Python's native eager execution (3.12+) may also experience issues with `asyncio.timeout()` when the timeout fires during eager execution, as the context manager captures the parent task reference instead of the actual task.

## asynkit's Eager Execution

### Introduction

asynkit provides eager execution through the `eager()` function, which has been available since the library's initial release in 2022 and originally worked with Python 3.8+. It offers more granular control and additional features beyond Python's built-in support.

**Note**: As of version 0.13.0, asynkit requires Python 3.10+, but the eager execution feature has been available since the beginning with backward compatibility.

### How It Works

asynkit's approach uses the `CoroStart` class to start coroutines immediately and handle the result:

```python
import asynkit
import asyncio


@asynkit.eager
async def get_slow_remote_data():
    result = await execute_remote_request()
    return result.important_data


async def my_complex_thing():
    # Starts executing immediately, returns Task if it blocks
    future = get_slow_remote_data()

    # Do other work while remote request is in flight
    intermediate_result = await some_local_computation()

    # Wait for the result
    return compute_result(intermediate_result, await future)
```

**Behavior**:

- Coroutine starts executing **immediately** when wrapped with `eager()`
- If it **completes without blocking**: Returns a ready future (no Task created)
- If it **blocks**: Creates a Task and returns it
- Maintains **depth-first execution** order

### Key Features

1. **Selective Application**: Apply eager execution to specific coroutines or functions
2. **Decorator Support**: Use `@asynkit.eager` to make functions always eager
3. **No Task When Not Needed**: If coroutine completes synchronously, returns a lightweight future instead of a Task
4. **Context Management**: `eager_ctx()` for automatic cancellation on error
5. **Python 3.10+ Support**: Works on older Python versions
6. **Correct Task Context**: When using `eager_task_factory` or `create_task(..., eager_start=True)`, execution runs in the new task's context from the start, ensuring `asyncio.current_task()` returns consistent values throughout

## Detailed Comparison

### Execution Model

| Aspect | Python 3.12 eager_task_factory | asynkit.eager |
|--------|-------------------------------|---------------|
| **Trigger** | During `create_task()` | During `eager()` call or decorated function invocation |
| **Scope** | All tasks in event loop | Selected coroutines only |
| **Return Type** | Always a Task | Task if blocked, Future if completed |
| **Task Creation** | Always creates Task | Only creates Task if coroutine blocks |
| **Execution Style** | Synchronous until first await | Synchronous until first await |

### Usage Patterns

**Python 3.12 eager_task_factory:**

```python
import asyncio

# Global configuration
loop = asyncio.get_event_loop()
loop.set_task_factory(asyncio.eager_task_factory)


async def worker():
    # This runs immediately when create_task is called
    result = await fetch_data()
    return process(result)


async def main():
    # All tasks start immediately with eager factory
    tasks = [asyncio.create_task(worker()) for _ in range(10)]
    await asyncio.gather(*tasks)
```

**asynkit.eager:**

```python
import asynkit
import asyncio


# Option 1: Decorator
@asynkit.eager
async def worker():
    result = await fetch_data()
    return process(result)


# Option 2: Direct application
async def worker_plain():
    result = await fetch_data()
    return process(result)


async def main():
    # Only these specific calls use eager execution
    tasks = [worker() for _ in range(5)]  # Eager via decorator
    more_tasks = [asynkit.eager(worker_plain()) for _ in range(5)]  # Eager via wrapper

    await asyncio.gather(*tasks, *more_tasks)
```

### Performance Characteristics

**Python 3.12 eager_task_factory:**

- **Benefit**: Eliminates event loop overhead for all task creation
- **Trade-off**: May start too many tasks immediately, potentially increasing stack depth
- **Best for**: Workloads where most tasks are short-lived or CPU-bound initially

**asynkit.eager:**

- **Benefit**: Reduces latency for selected I/O operations
- **Optimization**: Avoids Task creation entirely for synchronously-completing coroutines
- **Best for**: Scenarios where you want immediate execution for specific operations (e.g., cache hits, fast paths)

### Example: Cache Lookup Pattern

A common pattern where eager execution shines is cache lookups that might complete synchronously:

**With Python 3.12 eager_task_factory:**

```python
import asyncio

asyncio.get_event_loop().set_task_factory(asyncio.eager_task_factory)

cache = {}


async def get_data(key):
    if key in cache:
        return cache[key]  # Completes immediately

    # Fetch from remote
    result = await fetch_from_remote(key)
    cache[key] = result
    return result


async def main():
    # All tasks start immediately, but Task object is still created
    task = asyncio.create_task(get_data("cached_key"))
    result = await task
```

**With asynkit.eager:**

```python
import asynkit
import asyncio

cache = {}


@asynkit.eager
async def get_data(key):
    if key in cache:
        return cache[key]  # Completes immediately - no Task created!

    # Fetch from remote
    result = await fetch_from_remote(key)
    cache[key] = result
    return result


async def main():
    # Returns a ready Future if cached, Task only if remote fetch needed
    future = get_data("cached_key")
    result = await future
```

In this example, asynkit's approach is more efficient for cache hits because it avoids creating a Task object entirely.

## Depth-First Execution

Both Python's eager tasks and asynkit's `eager()` provide **depth-first execution** - maintaining synchronous execution order as much as possible. This is a key benefit of eager execution in general:

```python
import asynkit
import asyncio

log = []


async def test():
    log.append(1)
    await asyncio.sleep(0.2)
    log.append(2)


async def caller(convert):
    log.clear()
    log.append("a")
    future = convert(test())
    log.append("b")
    await asyncio.sleep(0.1)
    log.append("c")
    await future


# Without eager (lazy task creation)
asyncio.run(caller(lambda c: c))
# log == ["a", "b", "c", 1, 2]

# With regular create_task
asyncio.run(caller(asyncio.create_task))
# log == ["a", "b", 1, "c", 2]

# With asynkit.eager (depth-first)
asyncio.run(caller(asynkit.eager))
# log == ["a", 1, "b", "c", 2]

# With Python's eager_task_factory (also depth-first)
loop = asyncio.new_event_loop()
loop.set_task_factory(asyncio.eager_task_factory)
asyncio.set_event_loop(loop)
asyncio.run(caller(asyncio.create_task))
# log == ["a", 1, "b", "c", 2]
```

Notice how both eager approaches (`asynkit.eager` and Python's `eager_task_factory`) maintain the natural execution order - `test()` starts immediately and runs until it blocks, then control returns to the caller. This depth-first behavior is what makes eager execution valuable for reducing latency.

## When to Use Each

### Use Python's eager_task_factory When:

- ✅ You're using **Python 3.12+**
- ✅ Your workload creates **many tasks** that benefit from eager execution
- ✅ You want a **global optimization** without code changes
- ✅ You can **test thoroughly** for compatibility issues
- ✅ Your code doesn't rely on deferred execution semantics

### Use asynkit.eager When:

- ✅ You need to support **Python 3.10 or 3.11**
- ✅ You want **selective** eager execution for specific operations
- ✅ You want to **avoid Task creation** for synchronously-completing coroutines
- ✅ You need **fine-grained control** over execution behavior
- ✅ You're optimizing specific **hot paths** (e.g., cache lookups, fast paths)
- ✅ You want to maintain **explicit control** over which coroutines execute eagerly

### Use Both:

You can combine both approaches for maximum benefit:

```python
import asyncio
import asynkit

# Set eager task factory for all tasks
asyncio.get_event_loop().set_task_factory(asyncio.eager_task_factory)


# Still use asynkit.eager for its additional features
@asynkit.eager
async def optimized_operation():
    # Benefits from both:
    # - Eager execution even if wrapped in create_task elsewhere
    # - No Task creation if completes synchronously
    result = await fast_path()
    return result
```

## Migration Considerations

### From Standard asyncio to Python 3.12 eager_task_factory

```python
# Before (Python < 3.12)
async def main():
    task = asyncio.create_task(my_coroutine())
    await task


# After (Python 3.12+)
loop = asyncio.get_event_loop()
loop.set_task_factory(asyncio.eager_task_factory)


async def main():
    # Same code, but task starts immediately
    task = asyncio.create_task(my_coroutine())
    await task
```

**Risks**:

- Code expecting tasks to start on next event loop iteration may break
- Increased recursion depth in some scenarios
- Different cancellation timing

### From Standard asyncio to asynkit.eager

```python
# Before
async def fetch_data():
    return await remote_call()


async def main():
    task = asyncio.create_task(fetch_data())
    await task


# After
@asynkit.eager
async def fetch_data():
    return await remote_call()


async def main():
    # No create_task needed - eager() handles it
    future = fetch_data()
    await future
```

**Benefits**:

- More explicit about eager execution
- Can optimize specific functions without affecting others
- Backward compatible - works with older Python versions

## Implementation Details

### Python's eager_task_factory

Python's implementation modifies the task factory to call a new `eager_start` parameter on Task objects. When set, the task's `__step()` method is invoked immediately during construction rather than being scheduled.

Key implementation aspects:

- Adds `eager_start` parameter to `Task.__init__()`
- Calls `__step()` synchronously if `eager_start=True`
- Only schedules to event loop if coroutine yields

### asynkit's eager

asynkit uses the `CoroStart` class to manage coroutine execution:

1. **Starts coroutine immediately** using `CoroStart`
2. **Checks if completed**: If `done()`, returns a completed Future
3. **Creates Task if needed**: Only if coroutine blocked

Key implementation aspects:

- Uses `CoroStart` to manage partial coroutine execution
- Returns different types based on completion state
- Supports custom task factories via `create_task` parameter

## Advanced: Context Preservation

Both approaches preserve execution context correctly:

**Python 3.12:**

```python
import asyncio
import contextvars

var = contextvars.ContextVar("var")


async def main():
    var.set("value")
    task = asyncio.create_task(check_var())  # Context preserved
    await task


async def check_var():
    assert var.get() == "value"  # Works correctly
```

**asynkit:**

```python
import asynkit
import contextvars

var = contextvars.ContextVar("var")


async def main():
    var.set("value")
    future = asynkit.eager(check_var())  # Context preserved
    await future


@asynkit.eager
async def check_var():
    assert var.get() == "value"  # Works correctly
```

## Current Task Behavior During Eager Execution

### Understanding `asyncio.current_task()` with Eager Execution

When using asynkit's eager task execution (either via `@eager` decorator, `eager_task_factory`, or `create_task(..., eager_start=True)`), the behavior of `asyncio.current_task()` differs from standard task creation:

**Before the first blocking call:**

- If called from within an existing task: `current_task()` returns the **parent task**
- If called outside a task context (e.g., from callbacks or synchronous code): `current_task()` returns a temporary **ghost task**

**After the first blocking call:**

- `current_task()` returns the **actual task** as expected

### Why This Happens

Eager execution starts the coroutine **immediately** during the `eager()` or `create_task()` call, before the new task's context is fully established. To provide task context during this initial execution phase:

1. **Parent task case**: If already executing within a task, the coroutine runs in that task's context until it blocks
2. **Ghost task case**: If there's no current task (e.g., called from a callback or synchronous code), asynkit temporarily swaps in a reusable internal "ghost task" to provide task context

Once the coroutine blocks and a real Task is created, that Task becomes the current task for subsequent execution.

### The Ghost Task Pattern

The ghost task is a **reusable internal task** that serves as a placeholder during eager execution. Key characteristics:

- **Reusable**: A single ghost task instance is reused across multiple eager executions
- **Temporary**: Only active during the initial synchronous execution phase
- **Transparent**: Automatically swapped in and out as needed
- **Context provider**: Ensures `current_task()` never returns `None`, maintaining compatibility

### Why This Design?

This design enables:

1. **Framework compatibility**: Libraries like `anyio` and `sniffio` detect async frameworks by calling `asyncio.current_task()`. The ghost task ensures they get a valid task, not `None`
2. **Performance**: Reusing a single ghost task is much more efficient than creating wrapper tasks
3. **Correctness**: After the first blocking call, the real task context is established and used throughout

### Practical Impact

In **most cases**, this behavior is completely transparent. However, code that relies on **exact task identity** before any blocking calls should be aware of this:

**Potentially affected code:**

```python
@asynkit.eager
async def check_task_identity():
    # This may return the parent task or ghost task
    task1 = asyncio.current_task()

    await asyncio.sleep(0)  # First blocking call

    # This returns the actual task
    task2 = asyncio.current_task()

    # These may be different objects!
    assert task1 is task2  # May fail!
```

**Robust code pattern:**

```python
@asynkit.eager
async def robust_pattern():
    # Don't rely on task identity before blocking
    await asyncio.sleep(0)  # Ensure actual task is established

    # Now safe to use current_task() for identity checks
    my_task = asyncio.current_task()
    # ... use my_task ...
```

### Comparison with Python 3.12+

**Python's native eager tasks** (when using `asyncio.eager_task_factory` or `eager_start=True`) create the Task object **before** starting execution, so `current_task()` always returns the actual task, even during initial execution.

**asynkit's approach** defers Task creation until the coroutine blocks, which provides better performance (no Task creation for synchronous completion) but requires the ghost task pattern for framework compatibility.

### Framework Compatibility

Despite the difference in `current_task()` behavior, asynkit maintains full compatibility with framework detection libraries:

```python
import asynkit
import sniffio
import asyncio


@asynkit.eager
async def detect_framework():
    # Works correctly even with ghost task
    framework = sniffio.current_async_library()
    assert framework == "asyncio"  # Succeeds!

    await asyncio.sleep(0)

    # Still works with actual task
    framework = sniffio.current_async_library()
    assert framework == "asyncio"  # Succeeds!
```

This works because `sniffio` only needs to know that **some** task is current, not the specific task identity.

## Known Issues and Limitations

### `asyncio.timeout()` Incompatibility

**Both** Python's native eager execution and asynkit's eager execution have a known incompatibility with `asyncio.timeout()` context managers (Python 3.11+) and `asyncio.wait_for()` (all Python versions).

#### The Problem

When a coroutine executes eagerly, it runs in the parent task's context before its own Task is created and becomes the current task. If the coroutine enters an `asyncio.timeout()` context during the eager phase:

1. The timeout captures the **parent task** reference (not the coroutine's task)
2. When the timeout fires, it cancels the parent task
3. `CancelledError` propagates to the parent, not the coroutine that owns the timeout

This affects **both single tasks and concurrent scenarios**. With multiple eager coroutines (e.g., `asyncio.gather()`), all timeouts capture the same parent task reference, making the problem worse.

#### Example Failure

```python
import asyncio
import asynkit

async def check_socket(name):
    """Similar pattern to Redis's can_read_destructive()"""
    try:
        async with asyncio.timeout(0):  # Non-blocking timeout check
            await asyncio.sleep(0)
    except TimeoutError:
        pass  # Expected
    return f"checked-{name}"

# With eager execution enabled:
loop.set_task_factory(asynkit.eager_task_factory)
results = await asyncio.gather(
    check_socket("A"),
    check_socket("B"),
    check_socket("C")
)
# May raise CancelledError instead of completing successfully
```

#### Workarounds

1. **Add `await asyncio.sleep(0)` before timeout** (simplest):
   ```python
   async def check_socket(name):
       await asyncio.sleep(0)  # Force task creation
       async with asyncio.timeout(0):  # Now safe
           await asyncio.sleep(0)
   ```
   This forces task creation before entering the timeout context, ensuring each timeout has its own task reference.

2. **Disable eager execution for timeout-sensitive code**:
   ```python
   # Don't use @asynkit.eager on functions that use timeout(0)
   async def check_socket(name):
       async with asyncio.timeout(0):
           ...
   ```

3. **For Python 3.12+, use native eager execution**: Python's native `asyncio.eager_task_factory` creates Tasks before eager execution, which may handle timeouts differently (though the same fundamental issue can occur).

See [docs/asyncio_timeout_incompatibility.md](asyncio_timeout_incompatibility.md) for detailed analysis, reproduction cases, and experimental patches.

## Conclusion

Python 3.12's `eager_task_factory` and asynkit's `eager()` both provide valuable optimizations for async code, but serve different use cases:

- **Python's eager_task_factory**: Global optimization, best for Python 3.12+ applications with many short-lived tasks. The `eager_start` parameter offers selective control.
- **asynkit's eager()**: Targeted optimization, originally supported Python 3.8+ (now requires Python 3.10+ as of v0.13.0), provides finer control and avoids Task creation overhead

Choose based on your Python version requirements, performance goals, and whether you need global or selective eager execution. In many cases, using both together can provide the best results.

## See Also

- [Python asyncio documentation](https://docs.python.org/3/library/asyncio-task.html)
- [GitHub Issue #97696 - Add eager task creation API](https://github.com/python/cpython/issues/97696)
- [GitHub Issue #104144 - Leverage eager tasks to optimize asyncio gather](https://github.com/python/cpython/issues/104144)
- [asynkit README.md](../README.md) - Main documentation for asynkit
- [CoroStart documentation](../README.md#corostart) - Understanding the underlying mechanism
