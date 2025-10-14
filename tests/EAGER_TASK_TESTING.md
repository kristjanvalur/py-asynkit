# Testing with Python 3.12+ Eager Task Factory

This document describes how asynkit tests are parametrized to run with Python's native `eager_task_factory` introduced in Python 3.12.

## Overview

Python 3.12 introduced `asyncio.eager_task_factory`, which causes tasks to start executing synchronously when created, rather than deferring execution to the next event loop iteration. This can reveal different behavior patterns and edge cases in async code.

## What's Been Parametrized

### TestCoroAwait (tests/test_coro.py)

The `TestCoroAwait` class tests the behavior of coroutines wrapped with `coro_await()`. This class has been parametrized to run with both:
- **Regular mode**: Standard asyncio event loop (lazy task execution)
- **Eager mode**: Event loop with `asyncio.eager_task_factory` (Python 3.12+)

**Tests that pass in both modes:**
- `test_return_nb`: Tests basic return values
- `test_exception_nb`: Tests exception propagation

**Tests that skip in eager mode:**
- `test_coro_cancel`: Relies on task not completing before cancellation
- `test_coro_handle_cancel`: Relies on specific cancellation timing

These tests are skipped in eager mode because with eager execution, `await sleep(0)` completes synchronously, so the task finishes before the test can cancel it.

## Why Limited Scope?

Most asynkit tests are **incompatible** with `eager_task_factory` for these reasons:

1. **Custom Scheduling Loops**: Many tests use `SchedulingEventLoop` which directly manipulates the ready queue. This conflicts with eager task execution and causes `AttributeError: 'NoneType' object has no attribute '_cancelled'`.

2. **Low-Level Queue Manipulation**: Tests that use `ready_find()`, `ready_insert()`, `ready_remove()` etc. fundamentally depend on specific queue behavior that eager tasks bypass.

3. **Timing Assumptions**: Tests that assume lazy task scheduling break when tasks complete synchronously.

4. **Library Focus**: asynkit's value is in providing coroutine-level control that works *below* the task abstraction. Most tests focus on these low-level features which are orthogonal to task creation modes.

## Running Tests

Run all tests including eager mode:
```bash
pytest tests/
```

Run only eager mode tests:
```bash
pytest -m eager_tasks tests/
```

Run specific test with both modes:
```bash
pytest tests/test_coro.py::TestCoroAwait::test_return_nb -v
```

## Markers

- `@pytest.mark.eager_tasks`: Automatically applied to parametrized tests running in eager mode
- Used by test code to detect eager mode: `request.node.iter_markers()`

## Future Considerations

Additional test classes could be parametrized if they:
1. Use the default asyncio event loop (not custom scheduling loops)
2. Create tasks with `asyncio.create_task()`
3. Don't manipulate the ready queue directly
4. Don't rely on specific task scheduling timing

However, most asynkit features are designed to work at the coroutine level, making eager task factory testing less relevant for the library's core functionality.
