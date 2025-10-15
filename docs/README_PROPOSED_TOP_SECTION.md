# Proposed README Top Section

This document shows what the top of README.md could look like with the recommended improvements.

---

# asynkit: A toolkit for Python coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

**asynkit** provides advanced control over Python's `asyncio` module, offering tools for eager execution, fine-grained scheduling, and powerful coroutine manipulation.

## Key Features

### 🚀 Eager Execution
**Lower latency by starting coroutines immediately, not when awaited**

```python
@asynkit.eager
async def fetch_data():
    result = await remote_call()  # Starts immediately
    return result

# Execution begins right away, not when awaited
future = fetch_data()
```

- [`eager()`](#eager) decorator and function for immediate coroutine execution
- Works with Python 3.10+ (complements Python 3.12+ built-in eager tasks)
- [Detailed comparison with Python 3.12+](docs/eager_tasks.md)

### ⚡ Advanced Task Scheduling  
**Fine-grained control over task execution order**

- **Priority scheduling**: [`PriorityTask`](#priority-scheduling), [`PriorityLock`](#prioritylock) for importance-based execution
- **Queue control**: [`sleep_insert()`](#sleep_insert), [`task_reinsert()`](#task_reinsert) for precise positioning
- **Task switching**: [`task_switch()`](#task_switch) for immediate task activation
- **Introspection**: [`runnable_tasks()`](#runnable_tasks), [`blocked_tasks()`](#blocked_tasks)

### 🔧 Coroutine Control & Introspection
**Low-level coroutine manipulation for advanced use cases**

- **[`CoroStart`](#corostart)**: Start and inspect coroutines before awaiting
- **[`Monitor`](#monitor)**: Out-of-band communication with suspended coroutines
- **[`await_sync()`](#await_sync)**: Run async code synchronously when it doesn't block
- **[`GeneratorObject`](#generatorobject)**: Create async generators with method-based yields

### 🔬 Experimental Features
**Cutting-edge capabilities (may be platform-dependent)**

- **Task interruption**: [`task_interrupt()`](#task_interrupt) for raising exceptions in running tasks
- **Custom timeouts**: [`task_timeout()`](#task_timeout) with interrupt-based cancellation
- See [Experimental Features](#experimental-features) for details and limitations

### 🔌 Backend Support

| Backend | Support Level | Notes |
|---------|---------------|-------|
| `asyncio` | ✅ Full support | All features available |
| `anyio` (asyncio) | ✅ Full support | Includes eager task groups |
| `anyio` (trio) | ⚠️ Limited | Basic features only |

## Installation

```bash
pip install asynkit
```

## Quick Example

```python
import asynkit
import asyncio

@asynkit.eager
async def process_item(item):
    # This starts executing immediately
    result = await expensive_io(item)
    return result

async def main():
    # All three requests start immediately, running in parallel
    futures = [process_item(i) for i in range(3)]
    
    # Do other work while they run
    local_result = compute_something()
    
    # Collect results
    results = await asyncio.gather(*futures)
    return combine(local_result, results)

asyncio.run(main())
```

## Table of Contents

- [Coroutine Tools](#coroutine-tools)
  - [Eager Execution](#eager)
  - [Running Async from Sync](#await_sync-aiter_sync)
  - [CoroStart](#corostart)
  - [Monitor & Generators](#monitors-and-generators)
  - [Coroutine Helpers](#coroutine-helpers)
- [Scheduling Tools](#scheduling-tools)
  - [Scheduling Functions](#scheduling-functions)
  - [Event Loop Extensions](#event-loop-tools)
- [Priority Scheduling](#priority-scheduling)
- [anyio Support](#anyio-support)
- [Experimental Features](#experimental-features)
  - [Task Interruption](#task-interruption)
  - [Task Timeout](#task_timeout)

---

## Coroutine Tools

### `eager()` - Eager Execution {#eager}

> ℹ️ **Note:** Python 3.12+ introduced native eager task execution via `asyncio.eager_task_factory`. 
> See [docs/eager_tasks.md](docs/eager_tasks.md) for a detailed comparison of Python's built-in eager tasks and asynkit's `eager()` feature.

Did you ever wish that your _coroutines_ started right away, and only returned control to
the caller once they become blocked? Like the way the `async` and `await` keywords work in the __C#__ language?

[...rest of the existing content continues...]

---

## Alternative: Even More Concise Top Section

If you prefer something shorter:

---

# asynkit: A toolkit for Python coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

**Advanced control over Python's asyncio with eager execution, fine-grained scheduling, and powerful coroutine manipulation.**

## Key Features

- 🚀 **[Eager Execution](#eager)**: Start coroutines immediately, not when awaited
- ⚡ **[Advanced Scheduling](#scheduling-tools)**: Priority tasks, queue control, task switching
- 🔧 **[Coroutine Control](#coroutine-tools)**: Low-level inspection and manipulation
- 🔬 **[Experimental Features](#experimental-features)**: Task interruption, custom timeouts
- 🔌 **Backend Support**: Full `asyncio` and `anyio` support, limited `trio` support

## Installation

```bash
pip install asynkit
```

## Quick Example

```python
import asynkit
import asyncio

@asynkit.eager
async def fetch_data():
    return await remote_call()  # Starts immediately!

async def main():
    # Execution begins right away, not when awaited
    future = fetch_data()
    local_result = compute_something()
    return combine(local_result, await future)
```

## Documentation

Full documentation organized by topic:

- **[Coroutine Tools](#coroutine-tools)** - `eager()`, `CoroStart`, `Monitor`, `await_sync()`
- **[Scheduling Tools](#scheduling-tools)** - Queue control, task switching, introspection
- **[Priority Scheduling](#priority-scheduling)** - Importance-based task execution
- **[anyio Support](#anyio-support)** - Integration with anyio backends
- **[Experimental Features](#experimental-features)** - Task interruption, custom timeouts

---

[Detailed sections follow with existing content...]

---

## Notes on Both Versions

### First version (Detailed)
- **Pros**: Gives readers immediate understanding of capabilities
- **Pros**: Code examples provide quick "aha" moments
- **Cons**: Makes README longer before reaching detailed docs
- **Best for**: Projects where users need convincing/education

### Second version (Concise)
- **Pros**: Gets to the point quickly
- **Pros**: Maintains professional, clean look
- **Cons**: Less immediate detail
- **Best for**: Projects with established user base

### My Recommendation

I suggest a **hybrid approach**:
1. Use the concise feature list (second version)
2. Keep the detailed table of contents
3. Add the emojis to existing Note blocks throughout
4. Current detailed sections stay as-is

This gives you:
- ✅ Quick scanning at the top
- ✅ Easy navigation via TOC
- ✅ Improved readability with emojis
- ✅ Minimal disruption to existing structure

Would you like me to implement this hybrid approach?
