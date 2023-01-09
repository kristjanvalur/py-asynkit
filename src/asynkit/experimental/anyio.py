import contextlib
from typing import Any, AsyncIterator, Callable, Coroutine, Optional, Type
from types import TracebackType

import pytest
from anyio import create_task_group
from anyio.abc import TaskGroup, TaskStatus, CancelScope

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
            raise RuntimeError("started() wasn't called")
        return self.value


class EagerTaskGroup(TaskGroup):
    """
    This class wraps a `TaskGroup` and provides helper functions which start
    coroutines eagerly using `CoroStart`
    """

    __slots__ = ["_task_group"]

    def __init__(self, tg: TaskGroup):
        self._task_group = tg

    @property
    def cancel_scope(self) -> CancelScope:
        return self._task_group.cancel_scope

    async def start(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: object,
        name: Optional[object] = None
    ) -> Any:
        ts = TaskStatusForwarder()
        cs = CoroStart(func(*args, task_status=ts))
        if cs.done():
            cs.result()
            return ts.get_value()
        else:

            def helper(task_status: TaskStatus) -> Coroutine[Any, Any, Any]:
                ts.set_forward(task_status)
                return cs.as_coroutine()

            return self._task_group.start(helper, name=name)

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
