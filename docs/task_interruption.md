# Task Interruption

The `asynkit.experimental.interrupt` module provides immediate task interruption capabilities for asyncio, enabling precise exception injection and synchronous-style timeout handling.

## Overview

Standard `asyncio.Task.cancel()` is asynchronous - it marks a task for cancellation but the `CancelledError` is only raised the next time the task yields control. Task interruption provides **immediate execution control**: inject any exception into a task and have it execute right away, before other pending tasks run.

This enables patterns like:

- Synchronous-style timeouts that execute immediately
- Priority-based preemption of running tasks
- Emergency shutdown of misbehaving tasks
- Precise exception injection for testing and debugging

## Key Features

### Immediate Interruption

Inject exceptions that execute right away, not at the next yield point.

### Custom Exceptions

Use any `BaseException`, not just `CancelledError`.

### Non-Intrusive

The future a task is waiting on continues running - only the wait is interrupted.

### Synchronous Reasoning

When `await task_interrupt()` returns, the exception has already been raised on the target.

## Why Synchronous Interrupts?

With `task_interrupt()`, it's possible to reason about program flow in ways that asynchronous exception delivery cannot support. We know that:

1. **No intermediate tasks run** - No other tasks execute between calling `task_interrupt()` and the exception being raised on the target
2. **Deterministic delivery** - Control only returns after the exception has been raised
3. **No ambiguous state** - The task never exists in a state of "waiting to wake up with an exception"

This eliminates several classes of bugs:

**Multiple exceptions cannot collide**: Since `task_interrupt()` doesn't return until delivery is complete, you cannot accidentally send a second exception while the first is pending. The task is never in an unclear state where sending another interrupt has undefined behavior.

**Simpler error handling logic**: Knowing that `task_interrupt()` only returns after the exception has been raised allows for much simpler and less error-prone code. This is illustrated by the simplicity of the `task_timeout()` context manager - it can inject a timeout exception and know definitively that the timeout has been delivered, requiring no complex state tracking or coordination.

**Proven approach**: A similar synchronous error delivery mechanism has been available in **Stackless Python** since its inception and has proven invaluable for building reliable concurrent systems. The ability to send exceptions synchronously and reason about their delivery deterministically is a powerful tool for task coordination.

Without synchronous delivery, you must track:

- Has the exception been delivered yet?
- Can I safely send another exception?
- What happens if the task state changes before delivery?
- How do I coordinate multiple interrupt sources?

Synchronous interrupts eliminate these concerns entirely.

## Core API

### Creating Interruptible Tasks

```python
from asynkit.experimental import create_pytask

# Create a Python task that can be reliably interrupted
task = create_pytask(my_coroutine(), name="worker")
```

**Why needed**: Python tasks expose the internal methods required for precise interruption. C tasks (from `asyncio.create_task()`) have limited interrupt support.

**Limitation (Python 3.14)**: Due to an upstream bug in Python 3.14.0, `create_pytask()` is affected by `asyncio.current_task()` not properly tracking tasks from custom factories. Use Python 3.10-3.13 for full interrupt support.

### Interrupting Tasks

#### Low-Level: `task_throw()`

```python
from asynkit.experimental import task_throw

# Inject exception and schedule task to run
task_throw(task, MyException("interrupt!"))
```

Injects an exception into a task and schedules it to run immediately. The exception will be delivered when the task next executes, which happens "soon" but not necessarily before your current code continues.

**Use with caution**: If you call `task_throw()` twice before the task runs, the second exception overwrites the first. Prefer `task_interrupt()` below.

#### High-Level: `task_interrupt()`

```python
from asynkit.experimental import task_interrupt

# Interrupt and wait for exception delivery
await task_interrupt(task, MyException("stop now"))

# When we reach here, the exception has been raised on the task
assert task.done()
```

An async function that injects the exception and immediately switches to the target task. When the `await` completes, you know the exception has been delivered.

**Benefits**:

- Synchronous reasoning: know exactly when interruption occurred
- No collision between multiple interrupts
- Target task executes before caller resumes

### Timeout Context Manager

```python
from asynkit.experimental import task_timeout
import asyncio


async def my_operation():
    try:
        async with task_timeout(1.0):
            await slow_network_call()
            await another_slow_call()
    except asyncio.TimeoutError:
        print("Operation timed out")
```

A context manager that interrupts the current task after a timeout. The timeout exception is raised immediately when the timeout fires, not at the next yield point.

**How it differs from `asyncio.timeout()`**:

- Uses task interruption for immediate delivery
- Clean separation from standard cancellation
- Allows nested timeouts with different exception instances

## Exception Hierarchy

```python
# Base class for interrupt exceptions
class InterruptException(asyncio.CancelledError):
    pass


# Specific timeout exception
class TimeoutInterrupt(InterruptException):
    pass
```

Interrupt exceptions inherit from `CancelledError` because asyncio synchronization primitives (Lock, Semaphore, Condition) have special handling for `CancelledError` that ensures proper resource cleanup.

**Important**: Unhandled `CancelledError` subclasses are converted to plain `CancelledError` by asyncio's task machinery.

## Fixed Synchronization Primitives

### InterruptCondition

Standard `asyncio.Condition` doesn't properly handle exceptions other than `CancelledError` during lock re-acquisition. Use `InterruptCondition` when working with interrupts:

```python
from asynkit.experimental import InterruptCondition

condition = InterruptCondition()

async with condition:
    await condition.wait()  # Properly handles InterruptException
```

## How It Works

Task interruption manipulates asyncio's internal task state machine:

### Task States

Tasks exist in one of several states:

- **Blocked**: Waiting on a future (`_fut_waiter` set to an incomplete future)
- **Runnable**: In the event loop's ready queue (`__step` or `__wakeup` scheduled)
- **Running**: Currently executing (the current task)
- **Cancelled**: Marked for cancellation
- **Done**: Completed with result or exception

### Interruption Algorithm

1. **Locate the task**: Find it in the ready queue or in a future's callback list
2. **Unhook**: Remove from ready queue or future callbacks
3. **Inject**: Schedule the task with the exception as argument
4. **Execute**: For `task_interrupt()`, immediately switch to the task

For blocked tasks:

- Remove the task's `__wakeup` callback from the future
- The future continues running, but the task stops waiting for it
- Schedule the task with the exception

For runnable tasks:

- Remove the task's handle from the event loop's ready queue
- Schedule it again with the exception

### Python Tasks vs C Tasks

**Python tasks** (`_PyTask`): Full support for interruption. Methods like `__step` and `__wakeup` are accessible.

**C tasks** (`_CTask`): Partial support. Can interrupt tasks blocked on futures, but cannot interrupt tasks in the ready queue due to `TaskStepMethWrapper` limitations.

## Limitations and Caveats

### Cannot Interrupt

- **Self**: A task cannot interrupt itself (raises `RuntimeError`)
- **Done tasks**: Already completed (raises `RuntimeError`)
- **Cancelled tasks**: Already in cancellation process (raises `RuntimeError`)
- **C tasks in ready queue**: Technical limitation of TaskStepMethWrapper

### Python 3.14 Compatibility

Python 3.14.0 has a bug where `asyncio.current_task()` returns `None` for tasks created by custom task factories. This affects `create_pytask()` and breaks interrupt safety checks.

**Workaround**: Use Python 3.10-3.13 for full interrupt functionality.

**Status**: Bug reported to Python core team with minimal reproduction.

### Experimental Status

This module is marked experimental because:

- Relies on private asyncio APIs (`_fut_waiter`, `__step`, `__wakeup`)
- Directly manipulates event loop internals
- Implementation details may change across Python versions
- Platform-specific behavior with C tasks

Use with understanding that future Python versions may require updates.

## Advanced Usage

### Custom Interrupt Exceptions

```python
class ShutdownInterrupt(InterruptException):
    """Graceful shutdown request"""

    pass


class EmergencyStop(InterruptException):
    """Immediate halt required"""

    pass


async def worker():
    try:
        while True:
            await process_item()
    except ShutdownInterrupt:
        await cleanup_gracefully()
    except EmergencyStop:
        # Minimal cleanup only
        pass


# Elsewhere:
await task_interrupt(worker_task, ShutdownInterrupt())
```

### Nested Timeouts

```python
async def outer():
    try:
        async with task_timeout(5.0):
            await inner()
    except asyncio.TimeoutError:
        print("Outer timeout")


async def inner():
    try:
        async with task_timeout(1.0):
            await slow_operation()
    except asyncio.TimeoutError:
        print("Inner timeout")
```

Each timeout context creates its own `TimeoutInterrupt` instance, allowing the code to distinguish which timeout fired.

### Task Supervision

```python
async def supervisor(task):
    """Monitor a task and interrupt if it misbehaves"""
    start = time.time()

    while not task.done():
        await asyncio.sleep(0.1)

        if time.time() - start > MAX_EXECUTION_TIME:
            await task_interrupt(task, TimeoutError("exceeded limit"))
            break
```

## Comparison with Standard Cancellation

| Feature | `task.cancel()` | `task_interrupt()` |
|---------|-----------------|-------------------|
| Execution | Asynchronous | Synchronous (with await) |
| Exception | Always `CancelledError` | Any `BaseException` |
| Awaitable | No | Yes |
| Target future | Cancelled | Left running |
| Delivery | At next yield | Immediate |
| Multiple calls | Counts cancellation requests | Last call wins with `task_throw` |
| Use case | Normal shutdown | Immediate control, timeouts |

## Best Practices

### Use Python Tasks

Create tasks with `create_pytask()` to ensure reliable interruption:

```python
# Good - full interrupt support
task = create_pytask(worker())

# Limited - C task has partial support
task = asyncio.create_task(worker())
```

### Prefer task_interrupt() over task_throw()

```python
# Good - guarantees delivery
await task_interrupt(task, exc)

# Risky - multiple throws can collide
task_throw(task, exc1)
task_throw(task, exc2)  # Overwrites exc1
```

### Use InterruptCondition

```python
# Good - handles interrupts correctly
condition = InterruptCondition()

# Limited - only handles plain CancelledError
condition = asyncio.Condition()
```

### Handle Specific Exceptions

```python
# Good - distinguish interrupt types
try:
    await operation()
except ShutdownInterrupt:
    await graceful_cleanup()
except TimeoutInterrupt:
    await timeout_handling()

# Too broad
except InterruptException:
    # Which type was it?
    pass
```

## Examples

### Simple Timeout

```python
from asynkit.experimental import task_timeout
import asyncio


async def main():
    try:
        async with task_timeout(2.0):
            await asyncio.sleep(10)  # Will be interrupted
    except asyncio.TimeoutError:
        print("Timed out after 2 seconds")


asyncio.run(main())
```

### Worker Interruption

```python
from asynkit.experimental import create_pytask, task_interrupt, InterruptException


class StopWorking(InterruptException):
    pass


async def worker():
    try:
        for i in range(100):
            await process_item(i)
    except StopWorking:
        print(f"Interrupted at item {i}")
        return i


async def main():
    task = create_pytask(worker())
    await asyncio.sleep(0.5)  # Let it work a bit

    result = await task_interrupt(task, StopWorking())
    # Worker has already stopped by this point

    print(f"Worker stopped, processed {await task} items")
```

### Priority Preemption

```python
from asynkit.experimental import create_pytask, task_interrupt


class PreemptException(InterruptException):
    pass


async def low_priority_work():
    try:
        while True:
            await do_background_task()
    except PreemptException:
        # Save state and yield to high priority task
        await save_checkpoint()


async def main():
    background = create_pytask(low_priority_work())

    # High priority work arrives
    await task_interrupt(background, PreemptException())

    # Background task has yielded, do high priority work
    await urgent_processing()
```

## See Also

- `asynkit.scheduling` - Task scheduling helpers
- `asynkit.experimental.priority` - Priority-based scheduling
- [asyncio documentation](https://docs.python.org/3/library/asyncio.html) - Standard asyncio APIs
