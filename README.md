# asynkit: A toolkit for Python coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

This module provides some handy tools for those wishing to have better control over the
way Python's `asyncio` module does things.

- Helper tools for controlling coroutine execution, such as [`CoroStart`](#corostart) and [`Monitor`](#monitor)
- Utility classes such as [`GeneratorObject`](#generatorbject)
- Coroutine helpers such [`coro_iter()`](#coro_iter) and the [`awaitmethod()`](#awaitmethod) decorator
- Helpers to run _async_ code from _non-async_ code, such as `await_sync()` and `aiter_sync()` 
- Scheduling helpers for `asyncio`, and extended event-loop implementations
- _eager_ execution of Tasks
- Limited support for `anyio` and `trio`.
- Experimental features such as [`task_interrupt()`](#task_interrupt)

# Installation

```bash
$ pip install asynkit
```

# Coroutine Tools

## `eager()` - lower latency IO

Did you ever wish that your _coroutines_ started right away, and only returned control to
the caller once they become blocked?  Like the way the `async` and `await` keywords work in the __C#__ language?

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

## `coro_eager()`, `func_eager()`

`coro_eager()` is the magic coroutine wrapper providing the __eager__ behaviour:

1. It copies the current _context_
1. It initializes a `CoroStart()` object for the coroutine, starting it in the copied context.
2. If it subsequently is `done()` It returns `CoroStart.as_future()`, otherwise
   it creates and returns a `Task` (using `asyncio.create_task` by default.)

The result is an _awaitable_ which can be either directly awaited or passed
to `asyncio.gather()`. The coroutine is executed in its own copy of the current context,
just as would happen if it were directly turned into a `Task`.

`func_eager()` is a decorator which automatically applies `coro_eager()` to the coroutine returned by an async function.

## `await_sync(), aiter_sync()` - Running coroutines synchronously

If you are writing code which should work both synchronously and asynchronously,
you can now write the code fully _async_ and then run it _synchronously_ in the absence
of an event loop.  As long as the code doesn't _block_ (await unfinished _futures_) and doesn't try to access the event loop, it can successfully be executed.  This helps avoid writing duplicate code.

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
context.  Needless to say, it is very convoluted, hard to debug and contains a lot
of code duplication where the same logic is repeated inside async helper closures.

Using `await_sync()` it is possible to write the entire logic as `async` methods and
then simply fail if the code tries to invoke any truly async operations.
If the invoked coroutine blocks, a `SynchronousError` is raised _from_ a `SynchronousAbort` exception which
contains a traceback.  This makes it easy to pinpoint the location in the code where the
async code blocked.  If the code tries to access the event loop, e.g. by creating a `Task`, a `RuntimeError` will be raised.  

The `syncfunction()` decorator can be used to automatically wrap an async function
so that it is executed using `await_sync()`:

```python
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
code, to make them async.  This, along with `syncfunction()` and `await_sync()`,
can be used to integrate synchronous code with async middleware:

```python
@asynkit.syncfunction
async def sync_client(sync_callback):
    middleware = AsyncMiddleware(asynkit.asyncfunction(sync_callback))
    return await middleware.run()
```

Using this pattern, one can write the middleware completely async, make it also work
for synchronous code, while avoiding the hybrid function _antipattern._

### `aiter_sync()`

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

## `CoroStart`

This class manages the state of a partially run coroutine and is what what powers the `coro_eager()` and `await_sync()` functions. 
When initialized, it will _start_ the coroutine, running it until it either suspends, returns, or raises
an exception.  It can subsequently be _awaited_ to retrieve the result.

Similarly to a `Future`, it has these methods:

- `done()` - returns `True` if the coroutine finished without blocking. In this case, the following two methods may be called to get the result.
- `result()` - Returns the _return value_ of the coroutine or **raises** any _exception_ that it produced.
- `exception()` - Returns any _exception_ raised, or `None` otherwise.

 But more importantly it has these:

- `__await__()` - A magic method making it directly _awaitable_. If it has already finished, awaiting this coroutine is the same as calling `result()`, otherwise it awaits the original coroutine's continued execution
- `as_coroutine()` - A helper which returns a proper _coroutine_ object to await the `CoroStart`
- `as_future()` - If `done()`, returns a `Future` holding its result, otherwise, a `RuntimeError`
  is raised.
- `as_awaitable()` - If `done()`, returns `as_future()`, else returns `self`.
  This is a convenience method for use with functions such as `asyncio.gather()`, which would otherwise wrap a completed coroutine in a `Task`.

In addition it has:

- `aclose()` - If `not done()`, will throw a `GeneratorError` into the coroutine and wait for it to finish.  Otherwise does nothing.
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

## Context helper

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

This is similar to `contextvars.Context.run()` but works for async functions.  This function is
implemented using [`CoroStart`](#corostart)

## `coro_iter()`

This helper function turns a coroutine function into an iterator.  It is primarily
intended to be used by the [`awaitmethod()`](#awaitmethod) function decorator.

## `awaitmethod()`

This decorator turns the decorated method into a `Generator` as required for
`__await__` methods, which must only return `Iterator` objects.
It does so by invoking the `coro_iter()` helper.

This makes it simple to make a class _awaitable_ by decorating an `async`
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

## `Monitor`

A `Monitor` object can be used to await a coroutine, while listening for _out of band_ messages
from the coroutine.  As the coroutine sends messages, it is suspended, until the caller resumes
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

```
hello
dolly
done
```

For convenience, the `Monitor` can be _bound_ so that the caller does not have
to keep the coroutine around.  Calling the monitor with the coroutine returns a `BoundMonitor`:

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
`Task` objects.  This can be useful if the coroutine needs to maintain state.  Additionally,
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

Any IO exception is sent to the coroutine in this example.  This ensures that it cleans
up properly.  Alternatively, `aclose()` could have been used:

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
    # continue parsing, maye requesting more data
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

## `GeneratorObject`

A `GeneratorObject` builds on top of the `Monitor` to create an `AsyncGenerator`.  It is in many ways
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
the same way as an `AsyncGenerator` object.  It can be iterated over and supports the
`asend()`, `athrow()` and `aclose()` methods.

A `GeneratorObject` is a flexible way to asynchronously generate results without
resorting to `Task` and `Queue` objects.  What is more, it allows this sort
of generating pattern to be used in non-async programs, via `aiter_sync()`:

```python
def sync_runner():
    gen_obj = GeneratorObject()
    values = [val for val in aiter_sync(gen_obj(generator(gen_obj)))]
    assert values == [1, 2]
```

# Scheduling tools

A set of functions are provided to perform advanced scheduling of `Task` objects
with `asyncio`.  They work with the built-in event loop, and also with any eventloop
implementing the `AbstractSchedulingLoop` abstract base class, such as the `SchedulingMixin`
class which can be used to extend the built-in event loops.

## Scheduling functions

### `sleep_insert(pos)`

Similar to `asyncio.sleep()` but sleeps only for `pos` places in the runnable queue.
Whereas `asyncio.sleep(0)` will place the executing task at the end of the queue, which is
appropriate for fair scheduling, in some advanced cases you want to wake up sooner than that, perhaps
after a specific task.

### `task_reinsert(task, pos)`

Takes a _runnable_ task (for example just created with `asyncio.create_task()` or similar) and
reinserts it at a given position in the queue. 
Similarly as for `sleep_insert()`, this can be useful to achieve
certain scheduling goals.

### `task_switch(task, *, insert_pos=None)`

Immediately moves the given task to the head of the ready queue and switches to it, assuming it is runnable.
If `insert_pos is not None`, the current task will be
put to sleep at that position, using `sleep_insert()`. Otherwise the current task is put at the end
of the ready queue.  If `insert_pos == 1` the current task will be inserted directly after the target
task, making it the next to be run.  If `insert_pos == 0`, the current task will execute _before_ the target.

### `task_is_blocked(task)`

Returns True if the task is waiting for some awaitable, such as a Future or another Task, and is thus not
on the ready queue.

### `task_is_runnable(task)`

Roughly the opposite of `task_is_blocked()`, returns True if the task is neither `done()` nor __blocked__ and
awaits execution.

### `create_task_descend(coro)`

Implements depth-first task scheduling.

Similar to `asyncio.create_task()` this creates a task but starts it running right away, and positions the caller to be woken
up right after it blocks. The effect is similar to using `asynkit.eager()` but
it achieves its goals solely by modifying the runnable queue. A `Task` is always
created, unlike `eager`, which only creates a task if the target blocks.

## Runnable task helpers

A few functions are added to help working with tasks.

The following identity applies:
```python
asyncio.all_tasks() = (
    asynkit.runnable_tasks() | asynkit.blocked_tasks() | asyncio.current_task()
)
```

### `runnable_tasks(loop=None)`

Returns a set of the tasks that are currently runnable in the given loop

### `blocked_tasks(loop=None)`

Returns a set of the tasks that are currently blocked on some future in the given loop.

## Event Loop tools

Also provided is a mixin for the built-in event loop implementations in python, providing some primitives for advanced scheduling of tasks.  These primitives are what is used by the
scheduling functions above, and so custom event loop implementations can provide custom
implementations of these methods.

### `SchedulingMixin` mixin class

This class adds some handy scheduling functions to the event loop. They primarily
work with the _ready queue_, a queue of callbacks representing tasks ready
to be executed.

- `ready_len(self)` - returns the length of the ready queue
- `ready_pop(self, pos=-1)` - pops an entry off the queue
- `ready_insert(self, pos, element)` - inserts a previously popped element into the queue
- `ready_rotate(self, n)` - rotates the queue
- `call_insert(self, pos, ...)` - schedules a callback at position `pos` in the queue

### Concrete event loop classes

Concrete subclasses of Python's built-in event loop classes are provided.

- `SchedulingSelectorEventLoop` is a subclass of `asyncio.SelectorEventLoop` with the `SchedulingMixin`
- `SchedulingProactorEventLoop` is a subclass of `asyncio.ProactorEventLoop` with the `SchedulingMixin` on those platforms that support it.

### Event Loop Policy

A policy class is provided to automatically create the appropriate event loops.

- `SchedulingEventLoopPolicy` is a subclass of `asyncio.DefaultEventLoopPolicy` which instantiates either of the above event loop classes as appropriate.

Use this either directly:

```python
asyncio.set_event_loop_policy(asynkit.SchedulingEventLoopPolicy())
asyncio.run(myprogram())
```

or with a context manager:

```python
with asynkit.event_loop_policy():
    asyncio.run(myprogram())
```

# Coroutine helpers

A couple of functions are provided to introspect the state of coroutine objects. They
work on both regular __async__ coroutines, __classic__ coroutines (using `yield from`) and
__async generators__.

- `coro_is_new(coro)` -
  Returns true if the object has just been created and hasn't started executing yet

- `coro_is_suspended(coro)` - Returns true if the object is in a suspended state.

- `coro_is_done(coro)` - Returns true if the object has finished executing, e.g. by returning or raising an exception.

- `coro_get_frame(coro)` - Returns the current frame object of the coroutine, if it has one, or `None`.

# `anyio` support

The library has been tested to work with the `anyio`.  However, not everything is supported on the `trio` backend.
Currently only the `asyncio` backend can be assumed to work reliably.

When using the asyncio backend, the module `asynkit.experimental.anyio` can be used, to provide "eager"-like
behaviour to task creation.  It will return an `EagerTaskGroup` context manager:

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

```
hello
fine
world
goodbye
world
```

The first part of the function `func` is run even before calling `await` on the result from `EagerTaskGroup.start()`

Similarly, `EagerTaskGroup.start_soon()` will run the provided coroutine up to its first blocking point before
returning.

## `trio` limitations

`trio` differs significantly from `asyncio` and therefore enjoys only limited support.

- The event loop is completely different and proprietary and so the event loop extensions don't work
  for `trio`.

- `CoroStart` when used with `Task` objects, such as by using `EagerTaskGroup`,
  does not work reliably with `trio`.
  This is because the synchronization primitives
  are not based on `Future` objects but rather perform `Task`-based actions both before going to sleep
  and upon waking up.  If a `CoroStart` initially blocks on a primitive such as `Event.wait()` or
  `sleep(x)` it will be surprised and throw an error when it wakes up on in a different
  `Task` than when it was in when it fell asleep.

`CoroStart` works by intercepting a `Future` being passed up via the `await` protocol to 
the event loop to perform the task scheduling.  If any part of the task scheduling has happened
before this, and the _continuation_ happens on a different `Task` then things may break
in various ways.   For `asyncio`, the event loop never sees the `Future` object until
`as_coroutine()` has been called and awaited, and so if this happens in a new task, all is good.

# Experimental features

Some features are currently available experimentally.  They may work only on some platforms or be experimental in nature, not stable or mature enough to be officially part of the library

## Task Interruption

Methods are provided to raise exceptions on a `Task`.  This is somewhat similar to
`task.cancel()` but different:

- The caller specifies the exception instance to be raised on the task.
- The target task made to run immediately, precluding interference with other operations.
- The exception does not propagate into awaited objects.  In particular, if the task
  is _awaiting_ another task, the wait is interrupted, but that other task is not otherwise
  affected.
  
A task which is blocked, waiting for a future, is immediately freed and scheduled to run.
If the task is already scheduled to run, i.e. it is _new_, or the future has triggered but
the task hasn't become active yet, it is still awoken with an exception.

- __Note:__ These functions currently are only work **reliably** with `Task` object implemented in Python.
  Modern implementation often have a native "C" implementation of `Task` objects and they contain inaccessible code which cannot be used by the library.  In particular, the
  `Task.__step` method cannot be explicitly scheduled to the event loop.  For that reason,
  a special `create_pytask()` helper is provided to create a suitable python `Task` instance.
- __However:__ This library does go through extra hoops to make it usable with C Tasks.
  It almost works, but with two caveats:

  - CTasks which have plain `TaskStepMethWrapper` callbacks scheduled cannot be interrupted.
    These are typically tasks executing `await asyncio.sleep(0)` or freshly created
    tasks that haven't started executing.
  - The CTask's `_fut_waiting` member _cannot_ be cleared from our code, so there exists a time
    where it can point to a valid, not-done, Future, even though the Task is about
    to wake up.  This will make methods such as `task_is_blocked()` return incorrect
    values.  It __will__ get cleared when the interrupted task starts executing, however. All the more reason to use `task_interrupt()` over `task_throw()` since
    the former allows no space for code to see the task in such an intermediate state.

### `task_throw()`

```python
def task_throw(task: Task, exc: BaseException):
    pass
```

This method will make the target `Task` immediately runnable with the given exception
pending.

- If the Task was runnable due to a _previous_ call to `task_throw()`, this will override
  that call and its exception.

- Because of that, this method should probably not be used directly.  It is better to ensure that the
  target _takes delivery_ of the exception right away, because there is no way to
  queue pending exceptions and they do not add up in any meaningful way.
  Prefer to use `task_interrupt()` below.

- This method will **fail** if the target task has a pending _cancellation_, that is,
  it is in the process of waking up with a pending `CancelledError`.  Cancellation is
  currently asynchronous, while throwing exceptions is intended to be synchronous.

### `task_interrupt()`

```python
async def task_interrupt(task: Task, exc: BaseException):
    pass
```
An `async` version of `task_throw()`.  When awaited, `task_interrupt()` is called,
followed by a `task_switch()` to the target.  Once awaited, the exception
**has been raised** on the target task.

By ensuring that the target task runs immediately, it is possible to reason about task
execution without having to rely on external synchronization primitives and the cooperation
of the target task.  An interrupt is never _pending_ on the task (as a _cancellation_ can
be) and therefore it cannot cause collisions with other interrupts.

```python
async def test():
    async def task():
        await asyncio.sleep(1)
    create_pytask(task)
    await asyncio.sleep(0)
    assert task_is_blocked(task)
    await task_interrupt(task, ZeroDivisionError())
    assert task.done()  # the error has already been raised.
    try:
        await task
    except ZeroDivisionError:
        pass
    else:
        assert False, "never happens"

```

### `create_pytask()`

Similar to `asyncio.create_task()` but will create a pure **Python** `Task` which can safely
be used as the target for `task_throw()`and `task_interrupt()`.  Because of implementation
issues, regular **C** `Task` objects, as returned by `asyncio.create_task()`, cannot
be interrupted in all cases, in particular when doing an `await asyncio.sleep(0)` or
directly after having been created.

## `task_timeout()`

This is a context manager providing a timeout functionality, similar to `asyncio.timeout()`.
By leveraging `task_throw()` and a custom `BaseException` subclass, `TimeoutInterrupt`, 
the logic becomes very simple and there is no unintended interaction with regular
task cancellation().
