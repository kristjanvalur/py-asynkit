# asynkit
A toolkit for asyncio

This module provides some handy tools for those wishing to have better control over the
way Python's `asyncio` module does things

## Coroutine Tools

### `eager()` - lower latency IO

Did you ever wish that your _coroutines_ started right away, and only returned control to
the caller once they become blocked?  Like the way the `async` and `await` keywords work in the __C#__ language?

Now they can.  Just decorate or convert them with `acyncio.eager`:

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

By decorating your function with `asynkit.eager`, the _coroutine_ will start executing __right away__ and
control will return to the calling function as soon as it _blocks_, or returns a result or raises
an exception.  In case it blocks, a _Task_ is created and returned. 

What's more, if the called async function blocks, control is returned __directly__ back to the
calling function maintaining synchronous execution.  In effect, conventional code
calling order is maintained as much as possible.  We call this _depth-first-execution_.

This allows you to prepare and dispatch long running operations __as soon as possible__ while
still being able to asynchronously wait for the result.

`asynckit.eager` can also be used directly on the returned _coroutine_:
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

`coro()` is actually a convenience function, invoking either `coro_eager()` or `async_eager()` (see below) depending on context.

### `coro_eager()`, `async_eager()`

`coro_eager()` is the magic coroutine wrapper providing the __eager__ behaviour:

1. It runs `coro_start()` on the coroutine.
2. If `coro_is_blocked()` returns `False`, it returns `coro_continue()`
3. Otherwise, it creates a `Task` and invokes `coro_contine()` in the task.  Returns the task _awaitable_.

`async_eager()` is a decorator which automatically applies `coro_eager()` to the _coroutine_ returned by an async function.

### `coro_start()`, `coro_is_blocked()`, `coro_continue()`

These methods are helpers to perform coroutine execution and are what what power the `eager()` method.

- `coro_start()` runs the coroutine until it either blocks, returns, or raises an exception.  It returns a special tuple reflecting the coroutine's
  state.
- `coro_is_blocked()` returns true if the coroutine is in a blocked state
- `coro_continue()` is an async function which continues the execution of the coroutine from the initial state.

These functions are what allow `coro_eager()` to do its job.

## Event loop tools

Also provided is a mixin for the built-in event loop implementations in python, providing some primitives for advanced
scheduling of tasks.
