"""
Test script to understand context behavior in Python 3.10
"""

import asyncio
import contextvars

var = contextvars.ContextVar("test_var")


async def test_context_inheritance():
    """Test how contexts work in Python 3.10 without context parameter"""

    var.set("original")
    print(f"Main: {var.get()}")

    async def task1():
        print(f"Task1 start: {var.get()}")
        var.set("modified_in_task1")
        print(f"Task1 after set: {var.get()}")
        await asyncio.sleep(0)
        print(f"Task1 after sleep: {var.get()}")
        return "task1_result"

    async def task2():
        print(f"Task2 start: {var.get()}")
        var.set("modified_in_task2")
        print(f"Task2 after set: {var.get()}")
        return "task2_result"

    # Create tasks in Python 3.10 (no context parameter)
    t1 = asyncio.create_task(task1())
    t2 = asyncio.create_task(task2())

    print(f"After creating tasks: {var.get()}")

    r1, r2 = await asyncio.gather(t1, t2)

    print(f"After tasks complete: {var.get()}")
    print(f"Results: {r1}, {r2}")


async def test_with_different_context():
    """Test running tasks in different context"""

    var.set("main_context")
    print(f"\nMain context: {var.get()}")

    # Create a new context
    ctx = contextvars.copy_context()
    ctx.run(var.set, "new_context_value")

    async def context_aware_task():
        print(f"Context task start: {var.get()}")
        var.set("modified_in_context_task")
        print(f"Context task after set: {var.get()}")
        await asyncio.sleep(0)
        print(f"Context task after sleep: {var.get()}")
        return "context_task_result"

    # In Python 3.10, we can't pass context to create_task
    # But we can run the coroutine creation in a context
    def create_in_context():
        return asyncio.create_task(context_aware_task())

    task = ctx.run(create_in_context)

    print(f"After creating context task: {var.get()}")

    result = await task

    print(f"After context task complete: {var.get()}")
    print(f"Context task result: {result}")


if __name__ == "__main__":
    asyncio.run(test_context_inheritance())
    asyncio.run(test_with_different_context())
