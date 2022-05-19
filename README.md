# asynkit
A toolkit for asyncio

This module provides some handy tools for those wishing to have better control over the
way Python's `asyncio` module does things

## eager

Did you ever wish that your _coroutines_ started right away, and only returned once
they blocked?  Like the way the `async` and `await` keywords work in the __C#__ language?

Well, now they can.  Just decorate your method, or convert your coroutine, with `acyncio.eager`:

```
@asynkit.eager
async def get_slow_remote_data(source):
    remote_url = compuer_url(source)
    result = await execute_remote_request(remote_url)
    return result.important_data

async def my_complex_thing():
    # kick off the source1 request as soon as possible
    future1 = get_slow_remote_data("source1")
    # do some work taking time
    intermediate_result = some_local_info()
    # wait for the result of the request
    return compute_result(intermediate_result, await future)
```

By decorating your function with `asynkit.eager`, the _coroutine_ will start executing __right away__ and
control will return to the calling function as soon as it _blocks_, or returns a result or raises
an exception.  In case it blocks, a _Task_ is created and returned.

What's more, if the called async function blocks, control is returned __directly__ back to the
calling function maintaining synchronous execution.  In effect, conventional code
calling order is maintained as much as possible.

This allows you to prepare and dispatch long running operations __as soon as possible__ while
still being able to asynchronously wait for the result.

`asynckit.eager` can also be used directly on the returned _coroutine_:
```
import asynkio
import asynkit
log = []
async def test():
    log.append(1)
    asyncio.sleep(0)
    log.append(2)

async def caller():
    log.append("a")
    future = asynkit.eager(test())
    log.append("b")
    await future
    assert log == ["a", 1, "b", 2]
asyncio.run(caller())
```

Without using `asynkit.eager`, the `assert` would fail, since `log == ["a", "b", 1, 2]


The alternative to using `eager` is to use `asyncio.create_task()` but in this case

## SchedulingEvengLoop

Tools for advanced asyncio scheduling and "depth-first" execution of async functions
