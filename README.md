# asynkit: a toolkit for coroutines

[![CI](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml/badge.svg)](https://github.com/kristjanvalur/py-asynkit/actions/workflows/ci.yml)

This module provides some handy tools for those wishing to have better control over the
way Python's `asyncio` module does things

## Installation

```bash
$ pip install asynkit
```

## Coroutine Tools

### `eager()` - lower latency IO

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

`eager()` is actually a convenience function, invoking either `coro_eager()` or `async_eager()` (see below) depending on context.
Decorating your function makes sense if you __always__ intend
To _await_ its result at some later point. Otherwise, just apply it at the point
of invocation in each such case. 

### `coro_eager()`, `async_eager()`

`coro_eager()` is the magic coroutine wrapper providing the __eager__ behaviour:

1. It runs `CoroStart.start()` on the coroutine.
2. It returns `CoroStart.as_awaitable()`.

If the coroutine finished in step 1 above, the Future is a plain future and the
result is immediately available. Otherwise, a Task is created continuing from
the point where the coroutine initially suspended. In either case, the result
is an _awaitable_.
The coroutine is executed in its own context, just as would happen if it were
directly turned into a `Task`.

`async_eager()` is a decorator which automatically applies `coro_eager()` to the coroutine returned by an async function.

### `eager_coroutine()`, `eager_callable()`

These helpers can be added to async function calls when they need to be provided to
some `Task` creation APIs.  The target function will be eagerly started, before its
resumption is handed to said API.  For instance:

```python
async def myfunc(a):
    ...
# an api accepting awaitables
t1 = api.start_task(myfunc(a))  # traditional start
t2 = api.start_task(eager_coroutine(myfunc(a)))  # eager start

# an api accepting callables
t3 = api.start_task_function(myfunc, a)  # traditional
t4 = api.start_task_function(eager_callable(myfunc(a)))  # eager
```

### `CoroStart`

This class manages the state of a partially run coroutine and is what what powers the `coro_eager()` function. It has
the following methods:

- `start()` runs the coroutine until it either suspends, returns, or raises an exception. It is usually automatically
  invoked by the class Initializer
- `done()` returns true if the coroutine start resulted in it completing.
- `as_coroutine()` returns an coroutine with the coroutine's results.
- `as_awaitable()` returns an _awaitable_ with the coroutine's results.  If it finished, this is just a plain coroutine,
  otherwise, it is a `Task`.

CoroStart can be provided with a `contextvars.Context` object, in which case the coroutine will run using that
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

This is similar to `contextvars.Context.run()` but works for async functions.

## Event loop tools

Also provided is a mixin for the built-in event loop implementations in python, providing some primitives for advanced
scheduling of tasks.

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

### `task_switch(task, result=None, sleep_pos=None)`

Immediately moves the given task to the head of the ready queue and switches to it, assuming it is runnable.
When this call returns, returns `result`. If `sleep_pos is not None`, the current task will be
put to sleep at that position, using `sleep_insert()`. Otherwise the current task is put at the end
of the ready queue.

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

## Coroutine helpers

A couple of functions are provided to introspect the state of coroutine objects. They
work on both regular __async__ coroutines, __classic__ coroutines (using `yield from`) and
__async generators__.

### `coro_is_new(coro)`

Returns true if the object has just been created and hasn't started executing yet

### `coro_is_suspended(coro)`

Returns true if the object is in a suspended state.

### `coro_is_done(coro)`

Returns true if the object has finished executing, e.g. by returning or raising an exception.

### `coro_get_frame(coro)`

Returns the current frame object of the coroutine, if it has one, or `None`.
