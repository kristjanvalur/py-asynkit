# asyncio.timeout() Incompatibility with Eager Execution

## Problem Summary

When using `eager_task_factory` with Python 3.11+, the `asyncio.timeout()` context manager can cause `CancelledError` to propagate to the wrong coroutines during concurrent operations. This was reported when using Redis 5.0.3 with Python 3.11, where Redis internally uses `asyncio.timeout(0)` for non-blocking socket checks.

## Root Cause Analysis

### How Eager Execution Works

With eager execution:
1. When multiple tasks are created (e.g., via `asyncio.gather()`), each coroutine starts running **immediately** in the parent task's context
2. The coroutines run **sequentially and synchronously** until they hit their first suspension point (await)
3. Only when a coroutine suspends does a real Task get created for it
4. This means during the eager phase, all coroutines share the **same parent task context**

### How asyncio.timeout() Works

The `asyncio.timeout()` context manager (Python 3.11+) works by:
1. Capturing `current_task()` when `__aenter__()` is called
2. Storing this task reference as `self._task`
3. Scheduling a callback to call `self._task.cancel()` when the timeout expires
4. Using `task.uncancel()` in `__aexit__` to verify it's handling its own cancellation

### The Conflict

During eager execution with multiple concurrent operations:
1. Coroutine A runs eagerly, enters `asyncio.timeout()` → captures parent task
2. Coroutine B runs eagerly, enters `asyncio.timeout()` → captures **same** parent task
3. Coroutine C runs eagerly, enters `asyncio.timeout()` → captures **same** parent task
4. When any timeout fires, it cancels the parent task
5. The `CancelledError` propagates to whichever coroutine is currently executing
6. This is **not** the coroutine that owns the timeout!

### Example Failure Case

```python
async def check_socket(name):
    """Similar to Redis's can_read_destructive()"""
    try:
        async with asyncio.timeout(0):  # Non-blocking check
            await asyncio.sleep(0)
    except TimeoutError:
        pass  # Expected
    return f"checked-{name}"

# With eager_task_factory:
results = await asyncio.gather(
    check_socket("A"),
    check_socket("B"),
    check_socket("C")
)
# Result: CancelledError instead of completing successfully
```

### Why This Happens

```
Timeline:
1. gather() creates tasks for A, B, C
2. A runs eagerly (in parent task context):
   - Enters timeout(0) → timeout_A captures parent_task
   - Hits await sleep(0) → suspends, real Task_A created
3. B runs eagerly (still in parent task context):
   - Enters timeout(0) → timeout_B captures parent_task (SAME!)
   - Hits await sleep(0) → suspends, real Task_B created
4. C runs eagerly (still in parent task context):
   - Enters timeout(0) → timeout_C captures parent_task (SAME!)
   - Hits await sleep(0) → suspends, real Task_C created
5. timeout_A fires → calls parent_task.cancel()
6. CancelledError propagates to C (or B, or wherever we are in the event loop)
```

## Attempted Solutions

### Solution 1: Patch asyncio.timeout() with Thread-Local Depth Tracking

**Approach:**
- Track eager execution depth using thread-local storage
- When `asyncio.timeout()` is called during eager execution (depth > 0):
  - Return a wrapper that forces `await asyncio.sleep(0)` before entering the real timeout
  - This forces task creation, ensuring each timeout has its own task reference

**Implementation:**
- Added `_eager_corostart_state = threading.local()` to track depth
- Patched `asyncio.timeout()` to detect eager execution and return `EagerTimeoutWrapper`
- Wrapper calls `await asyncio.sleep(0)` in `__aenter__` to force task switch
- Modified `CoroStartBase._start()` to increment/decrement depth counter

**Status:** Works with Python implementation, but requires C extension updates

**Drawbacks:**
- Adds runtime overhead (thread-local lookups on every CoroStart)
- Requires patching stdlib (`asyncio.timeout`)
- Thread-local variables are a nuisance for testing/debugging
- C extension needs corresponding updates
- Adds complexity to the codebase
- May interact poorly with other async libraries

### Solution 2: Document as Known Limitation

**Approach:**
- Document the incompatibility in README and eager task factory docs
- Recommend workarounds for affected users
- Consider adding a compatibility mode flag in the future

**Workarounds for users:**
1. Don't use `asyncio.timeout()` with eager execution if timeouts may fire during eager phase
2. Use `asyncio.wait_for()` instead (doesn't have same task-capture semantics)
3. Disable eager execution for specific coroutines that use aggressive timeouts
4. Set `ASYNKIT_DISABLE_C_EXT=1` and apply the timeout patch (experimental)

## Reproduction

### Minimal Test Case

```python
import asyncio
import asynkit

async def test():
    async def op(name):
        try:
            async with asyncio.timeout(0):
                await asyncio.sleep(0)
        except TimeoutError:
            pass
        return f"done-{name}"
    
    # Fails with CancelledError:
    return await asyncio.gather(op("A"), op("B"), op("C"))

loop = asyncio.new_event_loop()
loop.set_task_factory(asynkit.eager_task_factory)
loop.run_until_complete(test())
```

### Redis Failure

```python
# Redis 5.0.3 connection pool with eager_task_factory
async def concurrent_redis_ops():
    # Each Redis operation calls can_read_destructive()
    # which uses asyncio.timeout(0)
    results = await asyncio.gather(
        redis.get("key1"),
        redis.get("key2"),
        redis.get("key3")
    )
    # Result: CancelledError / GeneratorExit
```

## Testing

Test script: `test_timeout_fix.py`

Run with Python implementation:
```bash
ASYNKIT_DISABLE_C_EXT=1 python test_timeout_fix.py
```

Expected: All tests pass when using the patched version

## Recommendation

Given the complexity and overhead of the patch solution, we should:

1. **Short term:** Document this as a known limitation
   - Add warning in eager task factory documentation
   - Provide workarounds in docs
   - Consider adding a detection mechanism to warn users

2. **Long term:** Consider options:
   - Implement the patch behind a feature flag (`ASYNKIT_PATCH_TIMEOUT=1`)
   - Wait for Python to provide better eager execution primitives
   - Explore alternative approaches (e.g., detect timeout usage and automatically disable eager)

## References

- Python 3.11 `asyncio.timeout()` source: `Lib/asyncio/timeouts.py`
- Redis issue: Redis 5.0.3 `can_read_destructive()` uses `timeout(0)`
- Related: `asyncio.wait_for()` doesn't have this issue (creates its own task)
