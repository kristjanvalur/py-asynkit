import contextlib
from typing import Any, AsyncIterator, Callable, Coroutine, Optional, Type
from types import TracebackType

import pytest
from anyio import create_task_group
from anyio.abc import TaskGroup, TaskStatus

from asynkit import CoroStart

pytestmark = pytest.mark.anyio


class TaskStatusForwarder(TaskStatus):
    """
    A helper class for `EagerTaskGroup.start()` which forwards the actual
    `started()` call into an inner TaskGroup
    """

    __slots__ = ["forward", "done", "value"]

    def __init__(self) -> None:
        self.forward: Optional[TaskStatus] = None
        self.done: bool = False
        self.value: object = None

    def started(self, value: object = None) -> None:
        assert not self.done
        if self.forward:
            self.forward.started(value)
        else:
            self.value = value
        self.done = True

    def set_forward(self, forward: TaskStatus) -> None:
        assert not self.forward
        self.forward = forward
        if self.done:
            forward.started(self.value)

    def get_value(self) -> Any:
        if not self.done:
            raise RuntimeError("Child exited without calling task_status.started()")
        return self.value


class EagerTaskGroup(TaskGroup):
    """
    This class wraps a `TaskGroup` and provides helper functions which start
    coroutines eagerly using `CoroStart`
    """

    __slots__ = ["_task_group"]

    def __init__(self, tg: TaskGroup):
        self._task_group = tg
        self.cancel_scope = tg.cancel_scope

    def start(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: object,
        name: Optional[object] = None
    ) -> Coroutine[Any, Any, Any]:
        ts = TaskStatusForwarder()
        cs = CoroStart(func(*args, task_status=ts))
        if cs.done():
            # if started() was called, but there is an exception,
            # we must return the started value, but leave the exception
            # to be raised by a thread.
            if ts.done:
                if cs.exception():
                    # return the value, start task to raise error
                    async def task_helper(*, task_status: TaskStatus) -> Any:
                        task_status.started(ts.get_value())
                        cs.result()

                    result = self._task_group.start(task_helper, name=name)
                else:
                    # return the value or raise missing-value exception
                    async def helper() -> Any:
                        return ts.get_value()

                    result = helper()
            else:
                # we are finished, without calling Done.  We need to raise,
                # either any exception which occurred, or the
                # "started() not called" thing.
                async def helper() -> Any:
                    cs.result()
                    ts.get_value()

                result = helper()

        else:

            def task_helper(*, task_status: TaskStatus) -> Coroutine[Any, Any, Any]:
                ts.set_forward(task_status)
                return cs.as_coroutine()

            result = self._task_group.start(task_helper, name=name)
        return result

    def start_soon(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: object,
        name: Optional[object] = None
    ) -> Any:
        cs = CoroStart(func(*args))
        if cs.done():
            cs.result()
        else:
            return self._task_group.start_soon(lambda: cs.as_coroutine(), name=name)

    async def __aenter__(self) -> "TaskGroup":
        """Enter the task group context and allow starting new tasks."""
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        """Exit the task group context waiting for all tasks to finish."""
        return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)


@contextlib.asynccontextmanager
async def create_eager_task_group() -> AsyncIterator[EagerTaskGroup]:
    async with create_task_group() as tg:
        yield EagerTaskGroup(tg)
