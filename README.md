# asynkit: A toolkit for Python coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

**asynkit** provides advanced control over Python's `asyncio` module, offering tools for eager execution, fine-grained scheduling, and powerful coroutine manipulation.

- Helper tools for controlling coroutine execution, such as [`CoroStart`](#corostart) and [`Monitor`](#monitor)
- Utility classes such as [`GeneratorObject`](#generatorobject)
- Coroutine helpers such [`coro_iter()`](#coro_iter) and the [`awaitmethod()`](#awaitmethod) decorator
- Helpers to run _async_ code from _non-async_ code, such as `await_sync()` and `aiter_sync()`
- Scheduling helpers for `asyncio`, and extended event-loop implementations
- [`eager_task_factory`](#eager_task_factory-and-create_eager_task_factory---global-eager-execution) support for global eager task execution (Python 3.12 API, backward compatible)
- [`@eager` decorator](#eager---lower-latency-io) for selective eager execution of coroutines
- Experimental support for [Priority Scheduling](#priority-scheduling) of Tasks
- Other experimental features such as [`task_interrupt()`](#task_interrupt)
- Limited support for `anyio` and `trio`.

## Installation

```bash
pip install asynkit
```

**asynkit** has a custom C extension to optimize some primitives. If available for your platform it will be automatically installed. If you want to force compilation from source for your platform use:

```bash
pip install --no-binary=asynkit asynkit
```

**Wheel selection:**

- **Binary wheels** (Windows, macOS, Linux × Python 3.10-3.14): High-performance C extension provides **8% better throughput** and **near-native latency**
- **Source distribution**: For platforms without pre-built wheels, or when using `--no-binary` flag

**Build environment variables:**

- `ASYNKIT_FORCE_CEXT=1`: Force C extension compilation and fail if it cannot be built (ensures no silent fallback to pure Python)
- `ASYNKIT_DISABLE_CEXT=1`: Disable C extension completely, use pure Python implementation
- `ASYNKIT_DEBUG=1`: Build C extension with debug symbols and assertions

Example:

```bash
# Force C extension build (fail if compilation fails)
ASYNKIT_FORCE_CEXT=1 pip install --no-binary=asynkit asynkit

# Build with debug symbols for development
ASYNKIT_DEBUG=1 pip install --no-binary=asynkit asynkit
```

Check your installation:

```python
import asynkit

info = asynkit.get_implementation_info()
print(f"Using: {info['implementation']}")  # "C extension" or "Pure Python"
```

## Features

- 🚀 **[Eager Execution](#eager)**: Start coroutines immediately, not when awaited
- 🏭 **[Eager Task Factory](#eager_task_factory-and-create_eager_task_factory---global-eager-execution)**: Global eager execution for all tasks (Python 3.12 API, backward compatible)
- 🔧 **[Cross-Version Compatibility](#cross-version-compatibility)**: Seamless eager execution across all Python versions with automatic monkeypatching
- ⚡ **[Advanced Scheduling](#scheduling-tools)**: Priority tasks, queue control, task switching
- 🔧 **[Coroutine Control](#coroutine-tools)**: Low-level inspection and manipulation
- 🔬 **[Experimental Features](#experimental-features)**: Task interruption, custom timeouts
- 🔌 **Backend Support**: Full `asyncio` and `anyio` support, limited `trio` support

## Coroutine Tools

### `eager()` - lower latency IO

> ℹ️ **Note:** Python 3.12+ introduced native eager task execution via `asyncio.eager_task_factory`. See [docs/eager_tasks.md](docs/eager_tasks.md) for a detailed comparison of Python's built-in eager tasks and asynkit's `eager()` feature. Performance analysis shows asynkit's C extension achieves near-native latency (0.80μs vs 0.74μs) with 8% better throughput than pure Python.

Did you ever wish that your _coroutines_ started right away, and only returned control to
the caller once they become blocked? Like the way the `async` and `await` keywords work in the __C#__ language?

Now they can. Just decorate or convert them with `acynkit.eager`:

```python
@asynkit.eager
async def get_slow_remote_data():
    result = await execute_remote_request()
    return result.important_data


async def my_complex_thing():
    # kick off the request as soon as possible
    future = get_slow_remote_data()
    # The remote execution may now already be in flight. Do some work taking time
    intermediate_result = await some_local_computation()
    # wait for the result of the request
    return compute_result(intermediate_result, await future)
```

By decorating your function with `eager`, the coroutine will start executing __right away__ and
control will return to the calling function as soon as it _suspends_, _returns_, or _raises_
an exception. In case it is suspended, a _Task_ is created and returned, ready to resume
execution from that point.

Notice how, in either case, control is returned __directly__ back to the
calling function, maintaining synchronous execution. In effect, conventional code
calling order is maintained as much as possible. We call this _depth-first-execution_.

This allows you to prepare and dispatch long running operations __as soon as possible__ while
still being able to asynchronously wait for the result.

`asynkit.eager` can also be used directly on the returned coroutine:

```python
log = []


async def test():
    log.append(1)
    await asyncio.sleep(0.2)  # some long IO
    log.append(2)


async def caller(convert):
    del log[:]
    log.append("a")
    future = convert(test())
    log.append("b")
    await asyncio.sleep(0.1)  # some other IO
    log.append("c")
    await future


# do nothing
asyncio.run(caller(lambda c: c))
assert log == ["a", "b", "c", 1, 2]

# Create a Task
asyncio.run(caller(asyncio.create_task))
assert log == ["a", "b", 1, "c", 2]

# eager
asyncio.run(caller(asynkit.eager))
assert log == ["a", 1, "b", "c", 2]
```

`eager()` is actually a convenience function, invoking either `coro_eager()` or `func_eager()` (see below) depending on context.
Decorating your function makes sense if you __always__ intend
To _await_ its result at some later point. Otherwise, just apply it at the point
of invocation in each such case.

It may be prudent to ensure that the result of `eager()` does not continue running
if it will never be awaited, such as in the case of an error. You can use the `cancelling()`
context manager for this:

```python
with cancelling(eager(my_method())) as v:
    await some_method_which_may_raise()
    await v
```

As a convenience, `eager_ctx()` will perform the above:

```python
with eager_ctx(my_method()) as v:
    await some_method_which_may_raise()
    await v
```

### `coro_eager()`, `func_eager()`

`coro_eager()` is the magic coroutine wrapper providing the __eager__ behaviour:

1. It copies the current _context_
2. It initializes a `CoroStart()` object for the coroutine, starting it in the copied context.
3. If it subsequently is `done()` It returns `CoroStart.as_future()`, otherwise
   it creates and returns a `Task` (using `asyncio.create_task` by default.)

The result is an _awaitable_ which can be either directly awaited or passed
to `asyncio.gather()`. The coroutine is executed in its own copy of the current context,
just as would happen if it were directly turned into a `Task`.

`func_eager()` is a decorator which automatically applies `coro_eager()` to the coroutine returned by an async function.

### `eager_task_factory` and `create_eager_task_factory()` - Global Eager Execution

For applications that want to apply eager execution globally (similar to Python 3.12's `asyncio.eager_task_factory`), asynkit provides task factory functions that make **all** tasks created with `asyncio.create_task()` execute eagerly. This implementation provides the same API as Python 3.12's native factory while being backward compatible with older Python versions.

#### Using the Pre-created Factory

```python
import asyncio
import asynkit

# Set up eager execution for all tasks (Python 3.12 API, works with 3.10+)
loop = asyncio.get_running_loop()
loop.set_task_factory(asynkit.eager_task_factory)


# Now all tasks execute eagerly
async def my_coroutine():
    return "immediate_result"


task = asyncio.create_task(my_coroutine())
# Task starts executing immediately, not when awaited
```

#### Creating Custom Factories

```python
import asyncio
import asynkit


# Create a custom eager factory with a custom Task class
class MyTask(asyncio.Task):
    pass


loop = asyncio.get_running_loop()
eager_factory = asynkit.create_eager_task_factory(MyTask)
loop.set_task_factory(eager_factory)
```

> ℹ️ **Note on `current_task()` behavior:** When using eager task execution, `asyncio.current_task()` returns the parent task or a temporary ghost task before the first blocking call, and the actual task afterwards. This ensures compatibility with framework detection libraries. See [Current Task Behavior](docs/eager_tasks.md#current-task-behavior-during-eager-execution) for details.

#### Python 3.14+ Compatibility

asynkit also provides a `create_task()` function with the same `eager_start` parameter as Python 3.14+:

```python
# Works on all Python versions (3.10+)
task = asynkit.create_task(my_coroutine(), eager_start=True)  # Eager
task = asynkit.create_task(my_coroutine(), eager_start=False)  # Standard
```

#### Performance Benefits

Eager task factories provide **significant performance improvements** for task startup latency:

- **Standard asyncio**: ~2.0 microseconds minimum per-task delay (scales with application complexity)
- **Eager factories**: ~0.6-1.1 microseconds consistent execution time
- **Improvement**: **1.8x faster** minimum latency, much larger improvements in real applications
- **asynkit C extension**: **8% better throughput** than pure Python, achieving **93% of native Python 3.14 performance** with cross-platform compatibility

**Important**: Eager execution provides **predictable performance** - latency remains constant regardless of work done between task creation and await, while non-eager latency scales with application complexity.

See [docs/eager_task_factory_performance.md](docs/eager_task_factory_performance.md) for detailed performance analysis comparing asynkit's implementation with Python 3.14's native `eager_task_factory`.

#### ⚠️ Known Limitations

**`asyncio.timeout()` Incompatibility**: When using eager execution, there is a known incompatibility with `asyncio.timeout()`. The context manager captures the currently
executing task to cancel. But during eager start, the *current* is the parent task. This will cause the timeout to manifest as a `CancelledError` in the parent task.

**Workarounds**:

- **Use `asyncio.wait_for()` instead** (recommended): Works correctly with eager execution
  ```python
  await asyncio.wait_for(operation(), timeout=5)
  ```
- **Add `await asyncio.sleep(0)` before timeout**: Forces task creation before entering timeout context
  ```python
  await asyncio.sleep(0)  # Force task creation
  async with asyncio.timeout(5):
      await operation()
  ```
- Disable eager execution for timeout-sensitive coroutines
- For Python 3.12+, consider using Python's native `asyncio.eager_task_factory` instead

See [docs/asyncio_timeout_incompatibility.md](docs/asyncio_timeout_incompatibility.md) for detailed analysis and additional workarounds.

#### When to Use Task Factories vs. Decorators

| Use Case | Recommendation |
|----------|----------------|
| **Global optimization** | `eager_task_factory` |
| **Legacy code migration** | `eager_task_factory` |
| **Selective optimization** | `@asynkit.eager` decorator |
| **Fine-grained control** | `@asynkit.eager` decorator |
| **Python 3.10/3.11 support** | Either (both work) |
| **Python 3.13+ migration** | `eager_task_factory` (compatible API) |

## Cross-Version Compatibility

### Automatic Eager Execution Monkeypatching

For the **ultimate in cross-version compatibility**, asynkit provides automatic monkeypatching that enables modern eager execution APIs on all Python versions:

```python
import asyncio
import asynkit.compat

# Enable comprehensive eager task execution across all Python versions
asynkit.compat.enable_eager_tasks()

# Now these APIs work identically on Python 3.10-3.14+:

# 1. asyncio.eager_task_factory is available everywhere
loop = asyncio.get_running_loop()
loop.set_task_factory(asyncio.eager_task_factory)  # Global eager execution

# 2. asyncio.create_task() supports eager_start parameter everywhere
task = asyncio.create_task(my_coroutine(), eager_start=True)  # Eager execution
task = asyncio.create_task(my_coroutine(), eager_start=False)  # Standard behavior
```

#### How It Works

The `enable_eager_tasks()` function automatically detects your Python version and applies the optimal implementation:

| Python Version | Implementation Strategy |
|----------------|------------------------|
| **Python < 3.12** | Adds `asyncio.eager_task_factory` using asynkit's implementation, enhances `create_task()` with `eager_start` parameter |
| **Python 3.12-3.13 without native `eager_start`** | Uses native `eager_task_factory` with temporary factory swapping for `eager_start=True` |
| **Python 3.14+ with native `eager_start`** | Uses native Python implementations directly (no monkeypatching needed) |

#### Benefits

- **🔄 Drop-in Compatibility**: Identical APIs across all Python versions
- **⚡ Optimal Performance**: Automatically uses the fastest available implementation
- **🛡️ Future-Proof**: Gracefully adapts to new Python versions
- **🧹 Clean Restoration**: `disable_eager_tasks()` restores original behavior

#### Example: Cross-Version Migration

```python
# This code works identically on Python 3.10, 3.11, 3.12, 3.13, and beyond!
import asyncio
import asynkit.compat


def setup_eager_execution():
    """Set up eager execution using the best available method."""
    asynkit.compat.enable_eager_tasks()

    # Global eager execution
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)


async def main():
    setup_eager_execution()

    # Per-task control works everywhere
    eager_task = asyncio.create_task(fetch_data(), eager_start=True)
    standard_task = asyncio.create_task(fetch_data(), eager_start=False)

    # Both APIs provide identical behavior across Python versions
    results = await asyncio.gather(eager_task, standard_task)
    return results


# Works on any Python 3.10+ installation
asyncio.run(main())
```

This makes asynkit the **definitive solution for eager task execution** across the entire Python ecosystem, providing a smooth migration path from legacy Python versions to the latest releases.

### `await_sync(), aiter_sync()` - Running coroutines synchronously

If you are writing code which should work both synchronously and asynchronously,
you can now write the code fully _async_ and then run it _synchronously_ in the absence
of an event loop. As long as the code doesn't _block_ (await unfinished _futures_) and doesn't try to access the event loop, it can successfully be executed. This helps avoid writing duplicate code.

```python
async def async_get_processed_data(datagetter):
    data = datagetter()  # an optionally async callback
    data = await data if isawaitable(data) else data
    return process_data(data)


# raises SynchronousError if datagetter blocks
def sync_get_processed_data(datagetter):
    return asynkit.await_sync(async_get_processed_data(datagetter))
```

This sort of code might previously have been written thus:

```python
# A hybrid function, _may_ return an _awaitable_
def hybrid_get_processed_data(datagetter):
    data = datagetter()
    if isawaitable(data):
        # return an awaitable helper closure
        async def helper():
            data = await data
            return process_data(data)

        return helper
    return process_data(data)  # duplication


async def async_get_processed_data(datagetter):
    r = hybrid_get_processed_data(datagetter)
    return await r if isawaitable(r) else r


def sync_get_processed_data(datagetter):
    r = hybrid_get_processed_data(datagetter)
    if isawaitable(r):
        raise RuntimeError("callbacks failed to run synchronously")
    return r
```

The above pattern, writing async methods as sync and returning async helpers,
is common in library code which needs to work both in synchronous and asynchronous
context. Needless to say, it is very convoluted, hard to debug and contains a lot
of code duplication where the same logic is repeated inside async helper closures.

Using `await_sync()` it is possible to write the entire logic as `async` methods and
then simply fail if the code tries to invoke any truly async operations.
If the invoked coroutine blocks, a `SynchronousError` is raised _from_ a `SynchronousAbort` exception which
contains a traceback. This makes it easy to pinpoint the location in the code where the
async code blocked. If the code tries to access the event loop, e.g. by creating a `Task`, a `RuntimeError` will be raised.

The `syncfunction()` decorator can be used to automatically wrap an async function
so that it is executed using `await_sync()`:

```pycon
>>> @asynkit.syncfunction
... async def sync_function():
...     async def async_function():
...         return "look, no async!"
...     return await async_function()
...
>>> sync_function()
'look, no async!'
>>>
```

the `asyncfunction()` utility can be used when passing synchronous callbacks to async
code, to make them async. This, along with `syncfunction()` and `await_sync()`,
can be used to integrate synchronous code with async middleware:

```python
@asynkit.syncfunction
async def sync_client(sync_callback):
    middleware = AsyncMiddleware(asynkit.asyncfunction(sync_callback))
    return await middleware.run()
```

Using this pattern, one can write the middleware completely async, make it also work
for synchronous code, while avoiding the hybrid function _antipattern._

#### `aiter_sync()`

A helper function is provided, which turns an `AsyncIterable` into
a generator, leveraging the `await_sync()` method:

```python
async def agen():
    for v in range(3):
        yield v


assert list(aiter_sync(agen())) == [1, 2, 3]
```

This is useful if using patterns such as `GeneratorObject` in a synchronous
application.

### `CoroStart`

This class manages the state of a partially run coroutine and is what what powers the `coro_eager()` and `await_sync()` functions.
When initialized, it will _start_ the coroutine, running it until it either suspends, returns, or raises
an exception. It can subsequently be _awaited_ to retrieve the result.

Similarly to a `Future`, it has these methods:

- `done()` - returns `True` if the coroutine finished without blocking. In this case, the following two methods may be called to get the result.
- `result()` - Returns the _return value_ of the coroutine or __raises__ any _exception_ that it produced.
- `exception()` - Returns any _exception_ raised, or `None` otherwise.

But more importantly it has these:

- `__await__()` - A magic method making it directly _awaitable_. If it has already finished, awaiting this coroutine is the same as calling `result()`, otherwise it awaits the original coroutine's continued execution
- `as_coroutine()` - A helper which returns a proper _coroutine_ object to await the `CoroStart`
- `as_future()` - If `done()`, returns a `Future` holding its result, otherwise, a `RuntimeError`
  is raised.
- `as_awaitable()` - If `done()`, returns `as_future()`, else returns `self`.
  This is a convenience method for use with functions such as `asyncio.gather()`, which would otherwise wrap a completed coroutine in a `Task`.

In addition it has:

- `aclose()` - If `not done()`, will throw a `GeneratorError` into the coroutine and wait for it to finish. Otherwise does nothing.
- `athrow(exc)` - If `not done()`, will throw the given error into the coroutine and wait for it to raise or return a value.
- `close()` and `throw(exc)` - Synchronous versions of the above, will raise `RuntimeError` if the coroutine does not immediately exit.

This means that a context manager such as `aclosing()` can be used to ensure
that the coroutine is cleaned up in case of errors before it is awaited:

```python
# start foo() and run until it blocks
async with aclosing(CoroStart(foo())) as coro:
    ...  # do things, which may result in an error
    return await coro
```

CoroStart can be provided with a `contextvars.Context` object, in which case the coroutine will be run using that
context.

### Context helper

`coro_await()` is a helper function to await a coroutine, optionally with a `contextvars.Context`
object to activate:

```python
var1 = contextvars.ContextVar("myvar")


async def my_method():
    var1.set("foo")


async def main():
    context = contextvars.copy_context()
    var1.set("bar")
    await asynkit.coro_await(my_method(), context=context)
    # the coroutine didn't modify _our_ context
    assert var1.get() == "bar"
    # ... but it did modify the copied context
    assert context.get(var1) == "foo"
```

This is similar to `contextvars.Context.run()` but works for async functions. This function is
implemented using [`CoroStart`](#corostart)

### `awaitmethod()`

This decorator turns the decorated method into a `Generator` as required for
`__await__` methods, which must only return `Iterator` objects.

This makes it simple to make a class instance _awaitable_ by decorating an `async`
`__await__()` method.

```python
class Awaitable:
    def __init__(self, cofunc):
        self.cofunc = cofunc
        self.count = 0

    @asynkit.awaitmethod
    async def __await__(self):
        await self.cofunc()
        return self.count
        self.count += 1


async def main():
    async def sleeper():
        await asyncio.sleep(1)

    a = Awaitable(sleeper)
    assert (await a) == 0  # sleep once
    assert (await a) == 1  # sleep again


asyncio.run(main())
```

Unlike a regular _coroutine_ (the result of calling a _coroutine function_), an object with an `__await__` method can potentially be awaited multiple times.

The method can also be a `classmethod` or `staticmethod:`

```python
class Constructor:
    @staticmethod
    @asynkit.awaitmethod
    async def __await__():
        await asyncio.sleep(0)
        return Constructor()


async def construct():
    return await Constructor
```

### `awaitmethod_iter()`

An alternative way of creating an __await__ method, it uses
the `coro_iter()` method to to create a coroutine iterator. It
is provided for completeness.

### `coro_iter()`

This helper function turns a coroutine function into an iterator. It is primarily
intended to be used by the [`awaitmethod_iter()`](#awaitmethod_iter) function decorator.

### `cancelling()`

This context manager automatically calls the `cancel()`method on its target when the scope
exits. This is convenient to make sure that a task is not left running if it never to
be awaited:

```python
with cancelling(asyncio.Task(foo())) as t:
    function_which_may_fail()
    return await t
```

### Monitors and Generators

#### Monitor

A `Monitor` object can be used to await a coroutine, while listening for _out of band_ messages
from the coroutine. As the coroutine sends messages, it is suspended, until the caller resumes
awaiting for it.

```python
async def coro(monitor):
    await monitor.oob("hello")
    await asyncio.sleep(0)
    await monitor.oob("dolly")
    return "done"


async def runner():
    m = Monitor()
    c = coro(m)
    while True:
        try:
            print(await m.aawait(c))
            break
        except OOBData as oob:
            print(oob.data)
```

which will result in the output

```bash
hello
dolly
done
```

For convenience, the `Monitor` can be _bound_ so that the caller does not have
to keep the coroutine around. Calling the monitor with the coroutine returns a `BoundMonitor`:

```python
async def coro(m):
    await m.oob("foo")
    return "bar"


m = Monitor()
b = m(coro(m))
try:
    await b
except OOBData as oob:
    assert oob.data == "foo"
assert await b == "bar"
```

Notice how the `BoundMonitor` can be _awaited_ directly, which is the same as awaiting
`b.aawait(None)`.

The caller can pass in _data_ to the coroutine via the `aawait(data=None)` method and
it will become the _return value_ of the `Monitor.oob()` call in the coroutine.
`Monitor.athrow()` can similarly be used to raise an exception out of the `Montitor.oob()` call.
Neither data nor an exception can be sent the first time the coroutine is awaited,
only as a response to a previous `OOBData` exception.

A `Monitor` can be used when a coroutine wants to suspend itself, maybe waiting for some external
condition, without resorting to the relatively heavy mechanism of creating, managing and synchronizing
`Task` objects. This can be useful if the coroutine needs to maintain state. Additionally,
this kind of messaging does not require an _event loop_ to be present and can can be driven
using `await_sync()` (see below.)

Consider the following scenario. A _parser_ wants to read a line from a buffer, but fails, signalling
this to the monitor:

```python
async def readline(m, buffer):
    l = buffer.readline()
    while not l.endswith("\n"):
        await m.oob(None)  # ask for more data in the buffer
        l += buffer.readline()
    return l


async def manager(buffer, io):
    m = Monitor()
    a = m(readline(m, buffer))
    while True:
        try:
            return await a
        except OOBData:
            try:
                buffer.fill(await io.read())
            except Exception as exc:
                await a.athrow(exc)
```

In this example, `readline()` is trivial, but if it were a stateful parser with hierarchical
invocation structure, then this pattern allows the decoupling of IO and the parsing of buffered data, maintaining the state of the parser while _the caller_ fills up the buffer.

Any IO exception is sent to the coroutine in this example. This ensures that it cleans
up properly. Alternatively, `aclose()` could have been used:

```python
m = Monitor()
with aclosing(m(readline(m, buffer))) as a:
    # the aclosing context manager ensures that the coroutine is closed
    # with `await a.aclose()`
    # even if we don't finish running it.
    ...
```

A standalone parser can also be simply implemented by two helper methods, `start()` and
`try_await()`.

```python
async def stateful_parser(monitor, input_data):
    while input_short(input_data):
        input_data += await monitor.oob()  # request more
    # continue parsing, maybe requesting more data
    return await parsed_data(monitor, input_data)


m: Monitor[Tuple[Any, bytes]] = Monitor()
initial_data = b""
p = m(stateful_parser(m, b""))
await p.start()  # set the parser running, calling oob()

# feed data until a value is returned
while True:
    parsed = await p.try_await(await get_more_data())
    if parsed is not None:
        break
```

This pattern can even be employed in non-async applications, by using
the `await_sync()` method instead of the `await` keyword to drive the `Monitor`.

For a more complete example, have a look at [example_resp.py](examples/example_resp.py)

#### GeneratorObject

A `GeneratorObject` builds on top of the `Monitor` to create an `AsyncGenerator`. It is in many ways
similar to an _asynchronous generator_ constructed using the _generator function_ syntax.
But whereas those return values using the `yield` _keyword_,
a GeneratorObject has an `ayield()` _method_, which means that data can be sent to the generator
by anyone, and not just by using `yield`, which makes composing such generators much simpler.

The `GeneratorObject` leverages the `Monitor.oob()` method to deliver the _ayielded_ data to whomever is iterating over it:

```python
async def generator(gen_obj):
    # yield directly to the generator
    await gen_obj.ayield(1)

    # have someone else yield to it
    async def helper():
        await gen_obj.ayield(2)

    await asyncio.create_task(helper())


async def runner():
    gen_obj = GeneratorObject()
    values = [val async for val in gen_obj(generator(gen_obj))]
    assert values == [1, 2]
```

The `GeneratorObject`, when called, returns a `GeneratorObjectIterator` which behaves in
the same way as an `AsyncGenerator` object. It can be iterated over and supports the
`asend()`, `athrow()` and `aclose()` methods.

A `GeneratorObject` is a flexible way to asynchronously generate results without
resorting to `Task` and `Queue` objects. What is more, it allows this sort
of generating pattern to be used in non-async programs, via `aiter_sync()`:

```python
def sync_runner():
    gen_obj = GeneratorObject()
    values = [val for val in aiter_sync(gen_obj(generator(gen_obj)))]
    assert values == [1, 2]
```

## Scheduling tools

A set of functions are provided to perform advanced scheduling of `Task` objects
with `asyncio`. They work with the built-in event loop, and also with any event loop
implementing the `AbstractSchedulingLoop` abstract base class, such as the `SchedulingMixin`
class which can be used to extend the built-in event loops.

### Scheduling functions

#### `sleep_insert(pos)`

Similar to `asyncio.sleep()` but sleeps only for `pos` places in the runnable queue.
Whereas `asyncio.sleep(0)` will place the executing task at the end of the queue, which is
appropriate for fair scheduling, in some advanced cases you want to wake up sooner than that, perhaps
after a specific task.

#### `task_reinsert(task, pos)`

Takes a _runnable_ task (for example just created with `asyncio.create_task()` or similar) and
reinserts it at a given position in the queue.
Similarly as for `sleep_insert()`, this can be useful to achieve
certain scheduling goals.

#### `task_switch(task, *, insert_pos=None)`

Immediately moves the given task to the head of the ready queue and switches to it, assuming it is runnable.
If `insert_pos is not None`, the current task will be
put to sleep at that position, using `sleep_insert()`. Otherwise the current task is put at the end
of the ready queue. If `insert_pos == 1` the current task will be inserted directly after the target
task, making it the next to be run. If `insert_pos == 0`, the current task will execute _before_ the target.

#### `task_is_blocked(task)`

Returns True if the task is waiting for some awaitable, such as a Future or another Task, and is thus not
on the ready queue.

#### `task_is_runnable(task)`

Roughly the opposite of `task_is_blocked()`, returns True if the task is neither `done()` nor __blocked__ and
awaits execution.

#### `create_task_descend(coro)`

Implements depth-first task scheduling.

Similar to `asyncio.create_task()` this creates a task but starts it running right away, and positions the caller to be woken
up right after it blocks. The effect is similar to using `asynkit.eager()` but
it achieves its goals solely by modifying the runnable queue. A `Task` is always
created, unlike `eager`, which only creates a task if the target blocks.

### Runnable task helpers

A few functions are added to help working with tasks.

The following identity applies:

```python
asyncio.all_tasks() == (
    asynkit.runnable_tasks() | asynkit.blocked_tasks() | asyncio.current_task()
)
```

#### `runnable_tasks(loop=None)`

Returns a set of the tasks that are currently runnable in the given loop

#### `blocked_tasks(loop=None)`

Returns a set of the tasks that are currently blocked on some future in the given loop.

### Event Loop tools

Also provided is a mixin for the built-in event loop implementations in python, providing some primitives for advanced scheduling of tasks. These primitives are what is used by the
scheduling functions above, and so custom event loop implementations can provide custom
implementations of these methods.

#### `SchedulingMixin` mixin class

This class adds some handy scheduling functions to the event loop. The are intended
to facilitate some scheduling tricks, particularly switching to tasks, which require
finding items in the queue and re-inserting them at an _early_ position. Nothing
is assumed about the underlying implementation of the queue.

- `queue_len()` - returns the length of the ready queue
- `queue_find(self, key, remove)` - finds and optionally removes an element in the queue
- `queue_insert_pos(self, pos, element)` - inserts an element at position `pos` the queue
- `call_pos(self, pos, ...)` - schedules a callback at position `pos` in the queue

#### Concrete event loop classes

Concrete subclasses of Python's built-in event loop classes are provided.

- `SchedulingSelectorEventLoop` is a subclass of `asyncio.SelectorEventLoop` with the `SchedulingMixin`
- `SchedulingProactorEventLoop` is a subclass of `asyncio.ProactorEventLoop` with the `SchedulingMixin` on those platforms that support it.

#### Creating scheduling event loops

The **recommended way** to use scheduling event loops is with the `scheduling_loop_factory()` function (Python 3.13+):

```python
import asyncio
import asynkit

# Modern approach (Python 3.13+)
asyncio.run(main(), loop_factory=asynkit.scheduling_loop_factory)
```

For Python 3.12 and earlier, or when using `asyncio.Runner`:

```python
import asyncio
import asynkit

# Using asyncio.Runner (Python 3.11+)
with asyncio.Runner(loop_factory=asynkit.scheduling_loop_factory) as runner:
    runner.run(main())
```

#### Event Loop Policy (Legacy)

> ⚠️ **Note:** Event loop policies are deprecated as of Python 3.14 and will be removed in Python 3.16.

For compatibility with Python 3.10-3.11, or for code that hasn't migrated away from the policy system, a policy class is provided:

- `SchedulingEventLoopPolicy` is a subclass of `asyncio.DefaultEventLoopPolicy` which instantiates either of the above event loop classes as appropriate.

Use this either directly:

```python
# Legacy approach (Python 3.10-3.11)
asyncio.set_event_loop_policy(asynkit.SchedulingEventLoopPolicy())
asyncio.run(main())
```

or with a context manager:

```python
with asynkit.event_loop_policy():
    asyncio.run(main())
```

## Priority Scheduling

### FIFO scheduling

Since the beginning, _scheduling_ of Tasks in `asyncio` has always been _FIFO_, meaning "first-in, first-out". This is a design principle which provides a certain _fairness_ to tasks, ensuring that all tasks run and a certain predictability is achieved with execution. FIFO is maintained in the following places:

- In the _Event Loop_, where tasks are executed in the order in which they become _runnable_
- In locking primitives (such as `asyncio.Lock` or `asyncio.Condition`) where tasks are able to _acquire_ the lock or get notified in the order
  in which they arrive.

All tasks are treated equally.

### The `asynkit.experimental.priority` module

> 🧪 **Note:** This is currently an experimental feature.

In pre-emptive system, such as scheduling of `threads` or `processes` there is usually some sort of `priority` involved too,
to allow designating some tasks as more important than others, thus requiring more rapid servicing, and others as having
lower priority and thus be relegated to background tasks where other more important work is not pending.

The `asynkit.experimental.priority` module now allows us to do something similar.

You can define the `priority` of Task objects. A task defining the `effective_priority()` method returning
a `float` will get priority treatment in the following areas:

- When awaiting a `PriorityLock` or `PriorityCondition`
- When waiting in to be executed by a `PrioritySelectorEventLoop` or a `PriorityProactorEventLoop`.

The floating point _priority value_ returned by `effective_priority()` is used to determine the task's priority, with _lower
values_ giving _higher priority_ (in the same way that low values are _sorted before_ high values).
If this method is missing, the default priority of `0.0` is assumed. The `Priority` enum class can be
used for some basic priority values, defining `Priority.HIGH` as -10.0 and `Priority.LOW` as 10.0.
In case of identical priority values, FIFO order is respected.

The locking primitives provided are fully compatible with the standard
locks in `asyncio` and also fully support the experimental [task interruption](#task-interruption) feature.

#### `PriorityTask`

This is an `asyncio.Task` subclass which implements the `effective_priority()` method. It can be constructed with a `priority` keyword
or a `priority_value` attribute. It also participates in [Priority Inheritance](#priority-inheritance).

#### `PriorityLock`

This is a `asyncio.Lock` subclass which respects the priorities of any `Task` objects attempting to acquire it. It also participates in [Priority Inheritance](#priority-inheritance).

#### `PriorityCondition`

This is an `asyncio.Condition` subclass which respects the priorities of any `Task` objects awaiting to be woken up. Its default
`lock` is of type `PriorityLock`.

#### `DefaultPriorityEventLoop`

This is an `asyncio.AbstractEventLoop` subclass which respects the priorities of any Task objects waiting to be executed. It also
provides all the scheduling extensions from `AbstractSchedulingLoop`. It also participates in [Priority Inheritance](#priority-inheritance).

This is either a `PrioritySelectorEventLoop` or a `PriorityProactorEventLoop`, both instances of the `PrioritySchedulingMixin` class.

### Priority Inversion

A well known problem with priority scheduling is the so-called [Priority Inversion](https://en.wikipedia.org/wiki/Priority_inversion)
problem. This implementation addresses that by two different means:

#### Priority Inheritance

A `PriorityTask` keeps track of all the `PriorityLock` objects it has acquired, and a `PriorityLock` keeps track of all the `asyncio.Task` objects waiting to acquire it. A `PriorityTask`'s `effective_priority()` method will be the highest _effective_priority_ of any
task waiting to acquire a lock held by it. Thus, a high priority-task which starts waiting for a lock which is held by a
low-priority task, will temporarily _propagate_ its priority to that task, so that ultimately, the `PrioritySchedulingMixin` event
loop with ensure that the previously low-priority task is now executed with the higher priority.

This mechanism requires the co-operation of both the tasks, locks and the event-loop to properly function.

#### Priority Boosting

The `PrioritySchedulingMixin` will regularly do "queue maintenance" and will identify Tasks that have sat around in the queue for
many cycles without being executed. It will randomly "boost" the priority of these tasks in the queue, so that they have a chance
to run.

This mechanism does not require the co-operation of locks and tasks to work, and is in place as a safety mechanism in applications
where it is not feasible to replace all instances of `Lock`s and `Task`s with their _priority_inheritance_-aware counterparts.

### How to use Priority Scheduling

To make use of Priority scheduling, you need to use either the priority scheduling event loop (e.g.
`DefaultPriorityEventLoop`) or a priority-aware synchronization primitive, i.e. `PriorityLock` or `PriorityCondition`. In addition, you need `Task` objects which support the `effective_priority()`
method, such as `PriorityTask`

It is possible to get priority behaviour from locks without having a priority event loop, and
vice versa. But when using the priority event loop, it is recommended to use the accompanying
lock and task classes which co-operate to provide _priority inheritance_.

A good first step, in your application, is to identify tasks
that perform background work, such as housekeeping tasks, and assign to them the `Priority.LOW` priority.

Subsequently you may want to identify areas of your application that require more attention than others. For a web-application's URL handler may elect to temporarily raise the priority (change `PriorityTask.priority_value`) for certain endpoints to give them better response.

This is new territory and it remains to be seen how having priority scheduling in a ``` co-operative`` environment such as  ```asyncio\` actually works in practice.

## Coroutine helpers

A couple of functions are provided to introspect the state of coroutine objects. They
work on both regular __async__ coroutines, __classic__ coroutines (using `yield from`) and
__async generators__.

- `coro_is_new(coro)` -
  Returns true if the object has just been created and hasn't started executing yet

- `coro_is_suspended(coro)` - Returns true if the object is in a suspended state.

- `coro_is_done(coro)` - Returns true if the object has finished executing, e.g. by returning or raising an exception.

- `coro_get_frame(coro)` - Returns the current frame object of the coroutine, if it has one, or `None`.

## `anyio` support

The library has been tested to work with `anyio` 4.11.0+ on Python 3.10-3.13, including the `trio` backend (trio 0.31.0+).
However, not all features are supported on the `trio` backend.
**For full asynkit functionality, use the `asyncio` backend.**

### Backend Compatibility

| Feature | asyncio backend | trio backend |
|---------|----------------|--------------|
| Basic `anyio` integration | ✅ Full support | ✅ Full support |
| `create_eager_task_group()` (non-blocking) | ✅ Full support | ✅ Full support |
| `create_eager_task_group()` (with blocking) | ✅ Full support | ❌ Not supported |
| Event loop extensions | ✅ Full support | ❌ Not supported |
| `CoroStart` with Tasks | ✅ Full support | ❌ Not supported |

### Using with asyncio backend

When using the asyncio backend, the module `asynkit.experimental.anyio` can be used to provide "eager"-like
behaviour to task creation. It will return an `EagerTaskGroup` context manager:

```python
from asynkit.experimental.anyio import create_eager_task_group
from anyio import run, sleep


async def func(task_status):
    print("hello")
    task_status.started("world")
    await sleep(0.01)
    print("goodbye")


async def main():
    async with create_eager_task_group() as tg:
        start = tg.start(func)
        print("fine")
        print(await start)
    print("world")


run(main, backend="asyncio")
```

This will result in the following output:

```bash
hello
fine
world
goodbye
world
```

The first part of the function `func` is run even before calling `await` on the result from `EagerTaskGroup.start()`

Similarly, `EagerTaskGroup.start_soon()` will run the provided coroutine up to its first blocking point before
returning.

### Why trio has limitations

`trio` differs significantly from `asyncio` in its architectural approach, which limits asynkit compatibility:

**Different Task models:**

- **asyncio** uses a `Future`-based model where task scheduling is performed by the event loop
- **trio** uses a Task-centric model where scheduling happens inside synchronization primitives

**Impact on eager execution:**

When `CoroStart` is used with Tasks (such as in `EagerTaskGroup`), it works by intercepting a `Future`
being passed up via the `await` protocol __before__ it reaches the event loop. This allows asynkit to
schedule the continuation in a new Task context.

This approach works perfectly with **asyncio** because:

- The event loop never sees the `Future` until `as_coroutine()` has been called and awaited
- All task scheduling happens at the event loop level
- Resuming in a different Task context works seamlessly

However, **trio** performs Task-based validation both before sleeping and upon waking:

- Synchronization primitives like `Event.wait()` or `sleep()` record which Task called them
- Upon waking, trio validates that the same Task is resuming
- If eager execution causes the continuation to run in a different Task, trio detects this and raises errors

**Cancel scope corruption:**

Additionally, trio's cancel scopes track Task identity. When eager execution crosses Task boundaries,
cancel scopes may become corrupted, leading to assertion errors.

**Recommendation:** Use the `asyncio` backend with `anyio` to access asynkit's eager execution features.
The non-eager features of asynkit work with both backends.

## Experimental features

Some features are currently available experimentally. They may work only on some platforms or be experimental in nature, not stable or mature enough to be officially part of the library.

### Task Interruption

**See [docs/task_interruption.md](docs/task_interruption.md) for detailed documentation.**

> ⚠️ **Note:** Task interruption with `_PyTask` objects on Python 3.14.0 requires the `patch_pytask()`
> compatibility function due to separated C and Python asyncio implementations. This function is
> automatically called by `create_pytask()` to synchronize both implementations for proper
> `current_task()` behavior. C Tasks (from `asyncio.create_task()`) have limited interrupt support.

Methods are provided to raise exceptions on a `Task`. This is somewhat similar to
`task.cancel()` but different:

- The caller specifies the exception instance to be raised on the task.
- The target task is made to run *immediately*, precluding interference with other operations.
- The exception does not propagate into awaited objects. In particular, if the target task
  is _awaiting_ another task, the wait is interrupted, but that other task is not otherwise
  affected.

A task which is blocked, waiting for a future, is immediately freed and scheduled to run.
If the task is already scheduled to run, i.e. it is _new_, or the future has triggered but
the task hasn't become active yet, it is still awoken with an exception.

Please note the following cases:

1. The Python `asyncio` library in places assumes that the only exception that can be
   raised out of awaitables is `CancelledError`. In particular, there are edge cases
   in `asyncio.Lock`, `asyncio.Semaphore` and `asyncio.Condition` where raising something
   else when acquiring these primitives will leave them in an incorrect state.

   Therefore, we provide a base class, `InterruptError`, deriving from `CancelledError` which
   should be used for interrupts in general.

   However, `asyncio.Condition` in Python 3.13 and earlier has a buggy implementation that will not
   correctly pass on such subclasses during `wait()` in all cases. The finally block that re-acquires
   the lock only catches `CancelledError`, not its subclasses. This was fixed in Python 3.13+ with
   improved exception handling that properly catches `CancelledError` and subclasses
   ([CPython PR #112201](https://github.com/python/cpython/pull/112201)).

   For compatibility with older Python versions, a safer `InterruptCondition` class is provided that
   handles `CancelledError` subclasses correctly. On Python 3.13+, `InterruptCondition` is simply
   an alias to the standard `asyncio.Condition` for optimal performance.

2. Even subclasses of `CancelledError` will be converted to a new `CancelledError`
   instance when not handled in a task, and awaited.

3. These functions currently are only work __reliably__ with `Task` object implemented in Python.
   Modern implementation often have a native "C" implementation of `Task` objects and they contain inaccessible code which cannot be used by the library. In particular, the
   `Task.__step` method cannot be explicitly scheduled to the event loop. For that reason,
   a special `create_pytask()` helper is provided to create a suitable python `Task` instance.

4. __However:__ This library does go through extra hoops to make it usable with C Tasks.
   It almost works, but with two caveats:

   - CTasks which have plain `TaskStepMethWrapper` callbacks scheduled cannot be interrupted.
     These are typically tasks executing `await asyncio.sleep(0)` or freshly created
     tasks that haven't started executing.
   - The CTask's `_fut_waiting` member _cannot_ be cleared from our code, so there exists a time
     where it can point to a valid, not-done, Future, even though the Task is about
     to wake up. This will make methods such as `task_is_blocked()` return incorrect
     values. It __will__ get cleared when the interrupted task starts executing, however. All the more reason to use `task_interrupt()` over `task_throw()` since
     the former allows no space for code to see the task in such an intermediate state.

#### `task_throw()`

```python
def task_throw(task: Task, exc: BaseException):
    pass
```

This method will make the target `Task` immediately runnable with the given exception
pending.

- If the Task was runnable due to a _previous_ call to `task_throw()`, this will override
  that call and its exception.

- Because of that, this method should probably not be used directly. It is better to ensure that the
  target _takes delivery_ of the exception right away, because there is no way to
  queue pending exceptions and they do not add up in any meaningful way.
  Prefer to use `task_interrupt()` below.

- This method will __fail__ if the target task has a pending _cancellation_, that is,
  it is in the process of waking up with a pending `CancelledError`. Cancellation is
  currently asynchronous, while throwing exceptions is intended to be synchronous.

#### `task_interrupt()`

```python
async def task_interrupt(task: Task, exc: BaseException):
    pass
```

An `async` version of `task_throw()`. When awaited, `task_interrupt()` is called,
followed by a `task_switch()` to the target. Once awaited, the exception
**has been raised** on the target task.

By ensuring that the target task runs immediately, it is possible to reason about task
execution without having to rely on external synchronization primitives and the cooperation
of the target task. An interrupt is never _pending_ on the task (as a _cancellation_ can
be) and therefore it cannot cause collisions with other interrupts.

```python
async def test():
    async def task():
        await asyncio.sleep(1)

    create_pytask(task)
    await asyncio.sleep(0)
    assert task_is_blocked(task)
    await task_interrupt(task, InterruptException())
    assert task.done()  # the error has already been raised.
    try:
        await task
    except CancelledError:  # original error is substituted
        pass
    else:
        assert False, "never happens"
```

#### `create_pytask()`

Similar to `asyncio.create_task()` but will create a pure __Python__ `Task` which can safely
be used as the target for `task_throw()`and `task_interrupt()`. Because of implementation
issues, regular __C__ `Task` objects, as returned by `asyncio.create_task()`, cannot
be interrupted in all cases, in particular when doing an `await asyncio.sleep(0)` or
directly after having been created.

### `task_timeout()`

This is a context manager providing a timeout functionality, similar to `asyncio.timeout()`.
By leveraging `task_throw()` and a custom `BaseException` subclass, `TimeoutInterrupt`,
the logic becomes very simple and there is no unintended interaction with regular
task cancellation().
