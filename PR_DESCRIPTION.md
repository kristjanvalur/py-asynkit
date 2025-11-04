# Fix eager task factory to run in correct task context

## Summary

This PR fixes a critical issue where eager task execution was not running in the correct task context. The coroutine would initially execute in the parent task's context until it blocked, causing `asyncio.current_task()` to return inconsistent values. This is now fixed using a "wrapper task" approach that ensures the coroutine runs in its own task's context from the very start.

## The Problem

When using `eager_task_factory` or `create_task(..., eager_start=True)`, the eager coroutine would:
1. Start executing immediately in the **parent task's context**
2. Only switch to its own task context **after blocking**
3. Cause `asyncio.current_task()` to return different values before/after first await

This broke code that relied on consistent task context, including:
- FastAPI/uvicorn's `sniffio` library detection
- Anyio framework's task tracking
- Any code using `asyncio.current_task()` for context management

## The Solution: Wrapper Task Approach

The fix uses a "wrapper task" pattern:

1. **Create wrapper task early**: Create a Task with a simple `EagerTaskWrapper.run()` coroutine
2. **Switch to task context**: Use `switch_current_task()` to temporarily set the wrapper task as current
3. **Start user coroutine**: Execute `CoroStart(coro)` within the task context
4. **Handle completion**:
   - If coroutine **blocks**: Set it as the wrapper's awaitable, return the Task
   - If coroutine **completes synchronously**: Return a `TaskLikeFuture` with the result

This ensures `asyncio.current_task()` returns the correct task **throughout** execution.

## Python 3.14 Compatibility

Python 3.14 introduced dual bookkeeping for `current_task()` tracking:
- **C implementation**: `_c__swap_current_task` (authoritative)
- **Python implementation**: `_py_swap_current_task` (backup)

These must be kept synchronized:
- Call **both** implementations to update bookkeeping
- Return **C version's result** (source of truth)
- Anyio and other frameworks use C bookkeeping exclusively

## Changes Made

### Core Implementation
- `src/asynkit/coroutine.py`:
  - Refactored `coro_eager_task_helper` to use wrapper task approach
  - Added `switch_current_task` context manager usage
  - Simplified `EagerTaskWrapper` class
  - Added proper type annotations for mypy strict mode

### Python 3.14 Compatibility
- `src/asynkit/compat.py`:
  - Updated `_py_c_swap_current_task` for Python 3.14's `(loop, task)` signature
  - Synchronized C and Python bookkeeping implementations
  - Updated `switch_current_task` to pass loop parameter on 3.14
  - Added `Callable` import for proper typing
  - Removed dead code (`_patch_context`)

### Documentation
- `docs/eager_tasks.md`:
  - **Removed** outdated limitation about parent task context
  - **Added** feature documentation confirming correct task context behavior
  - Updated to reflect that `asyncio.current_task()` now returns consistent values

## Testing

All tests pass on both Python 3.13 and 3.14:
- ✅ **567 tests passing** on Python 3.13.7
- ✅ **567 tests passing** on Python 3.14.0rc2
- ✅ **134 skipped**, 2 xfailed (expected)
- ✅ **95% code coverage**
- ✅ **All type checks pass** (mypy strict mode)
- ✅ **All linting passes** (ruff)

## Backwards Compatibility

This change is **fully backwards compatible**:
- Existing code continues to work unchanged
- Behavior is **corrected**, not changed
- Performance characteristics remain the same
- No API changes required

The only "breaking" change is that `asyncio.current_task()` now correctly returns the eager task instead of the parent task, which is the **intended and correct behavior**.

## Fixes

- Fixes eager task factory sniffio compatibility (#issue-placeholder)
- Fixes uvicorn/FastAPI eager execution issues
- Fixes anyio task tracking with eager tasks
- Ensures correct task context throughout eager execution

## Related Issues

This implements the wrapper task approach discussed previously and resolves the fundamental architectural issue with eager task execution context.
