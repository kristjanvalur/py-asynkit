# asynkit: a toolkit for coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

This module provides some handy tools for those wishing to have better control over the
way Python's `asyncio` module does things.

- Helper tools for controlling coroutine execution, such as `CoroStart` and `Monitor`
- Utility classes such as `GeneratorObject`
- `asyncio` event-loop extensions
- _eager_ execution of Tasks
- Limited support for `anyio` and `trio`.

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

`asynckit.eager` can also be used directly on the returned coroutine:
```python
log = []
async def test():
    log.append(1)
    await asyncio.sleep(0.2) # some long IO
    log.append(2)

async def caller(convert):
    del log[:]
    log.append("a")
    future = convert(test())
    log.append("b")
    await asyncio.sleep(0.1) # some other IO
    log.append("c")
    await future

# do nothing
asyncio.run(caller(lambda c:c))
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
2. If it subsequently is `done()` It returns `CoroStart.as_future()`, ortherwise
   it creates and returns a `Task` (using `asyncio.create_task` by default.)

The result is an _awaitable_ which can be either directly awaited or passed
to `asyncio.gather()`. The coroutine is executed in its own copy of the current context,
just as would happen if it were directly turned into a `Task`.

`func_eager()` is a decorator which automatically applies `coro_eager()` to the coroutine returned by an async function.

## `CoroStart`

This class manages the state of a partially run coroutine and is what what powers the `coro_eager()` function. 
When initialized, it will _start_ the coroutine, running it until it either suspends, returns, or raises
an exception.

Similarly to a `Future`, it has these methods:

- `done()` - returns `True` if the coroutine finished without blocking. In this case, the following two methods may be called to get the result.
- `result()` - Returns the _return value_ of the coroutine or **raises** any _exception_ that it produced.
- `exception()` - Returns any _exception_ raised, or `None` otherwise.

 But more importly it has these:

- `as_coroutine()` - Returns an coroutine encapsulating the original coroutine's _continuation_.
  If it has already finished, awaiting this coroutine is the same as calling `result()`, otherwise it continues the original coroutine's execution.
- `as_future()` - If `done()`, returns a `Future` holding its result, otherwise, a `RuntimeError`
  is raised. This is suitable for using with
  `asyncio.gather()` to avoid wrapping the result of an already completed coroutine into a `Task`.

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
    context=contextvars.copy_context()
    var1.set("bar")
    await asynkit.coro_await(my_method(), context=context)
    # the coroutine didn't modify _our_ context
    assert var1.get() == "bar"
    # ... but it did modify the copied context
    assert context.get(var1) == "foo"
```

This is similar to `contextvars.Context.run()` but works for async functions.  This function is
implemented using `CoroStart`

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
        except OOBData as oob:
            print(oob.data)
```

which will result in the output

```
hello
dolly
done
```

The caller can also pass in data to the coroutine via the `Monitor.aawait(coro, data:None)` method and
it will become the result of the `Monitor.oob()` call inside the monitor.   `Monitor.athrow()` can be
used to raise an exception inside the coroutine.

A Monitor can be used when a coroutine wants to suspend itself, maybe waiting for some extenal
condition, without resorting to the relatively heavy mechanism of creating, managing and synchronizing
`Task` objects.  This can be useful if the coroutine needs to maintain state.

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
        c = readline(m, buffer)
        while True:
            try:
                return await m.aawait(c)
            except OOBData:
                try:
                    buffer.fill(await io.read())
                except Exception as exc:
                    await m.athrow(c, exc)
```

In this example, `readline()` is trivial, but if this were a complicated parser with hierarchical
invocation structure, then this pattern allows the decoupling of IO and the parsing of buffered data, maintaining the state of the parser while _the caller_ fills up the buffer.

## `GeneratorObject`

A GeneratorObject builds on top of the `Monitor` to create an `AsyncGenerator`.  It is in many ways
similar to an _asynchronous generator_ constructed using the _generator function_ syntax.
But wheras those return values using the `yield` keyword,
a GeneratorObject has an `ayield()` method, which means that data can be sent to the generator
by anyone.
It leverages the `Monitor.oob()` method to deliver the yielded data to whomever is iterating over it:

```python
async def generator(gen_obj):
    # yield directly to the generator
    await gen_obj.ayield(1):
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

A GeneratorObject is a flexible way to asynchronously generate results without
resorting to Tasks and Queues.


# Event loop tools

Also provided is a mixin for the built-in event loop implementations in python, providing some primitives for advanced
scheduling of tasks.

## `SchedulingMixin` mixin class

This class adds some handy scheduling functions to the event loop. They primarily
work with the _ready queue_, a queue of callbacks representing tasks ready
to be executed.

- `ready_len(self)` - returns the length of the ready queue
- `ready_pop(self, pos=-1)` - pops an entry off the queue
- `ready_insert(self, pos, element)` - inserts a previously popped element into the queue
- `ready_rotate(self, n)` - rotates the queue
- `call_insert(self, pos, ...)` - schedules a callback at position `pos` in the queue

## Concrete event loop classes

Concrete subclasses of Python's built-in event loop classes are provided.

- `SchedulingSelectorEventLoop` is a subclass of `asyncio.SelectorEventLoop` with the `SchedulingMixin`
- `SchedulingProactorEventLoop` is a subclass of `asyncio.ProactorEventLoop` with the `SchedulingMixin` on those platforms that support it.

## Event Loop Policy

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

## Scheduling functions

A couple of functions are provided making use of these scheduling features.
They require a `SchedulingMixin` event loop to be current.

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
They require a `SchedulingMixin` event loop to be current.

The following identity applies:
```python
asyncio.all_tasks(loop) = asynkit.runnable_tasks(loop) | asynkit.blocked_tasks(loop) | {asyncio.current_task(loop)}
```

### `runnable_tasks(loop=None)`

Returns a set of the tasks that are currently runnable in the given loop

### `blocked_tasks(loop=None)`

Returns a set of the tasks that are currently blocked on some future in the given loop.

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
    task_status->started("world")
    await sleep(0.01)
    print("goodbye")

async def main():

    async with create_eager_task_group() as tg:
        start = tg.start(func)
        print("fine")
        print(await start)
    print ("world")

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
  This is because the syncronization primitives
  are not based on `Future` objects but rather perform `Task`-based actions both before going to sleep
  and upon waking up.  If a `CoroStart` initially blocks on a primitive such as `Event.wait()` or
  `sleep(x)` it will be surprised and throw an error when it wakes up on in a different
  `Task` than when it was in when it fell asleep.

`CoroStart` works by intercepting a `Future` being passed up via the `await` protocol to 
the event loop to perform the task scheduling.  If any part of the task scheduling has happened
before this, and the _continuation_ happens on a different `Task` then things may break
in various ways.   For `asyncio`, the event loop never sees the `Future` object until
`as_coroutine()` has been called and awaited, and so if this happens in a new task, all is good.
