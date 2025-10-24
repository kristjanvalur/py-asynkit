from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from weakref import ReferenceType

"""Compatibility routines for earlier asyncio versions"""

__all__ = ["InterruptCondition", "patch_pytask"]

# Python version checks
PY_311 = sys.version_info >= (3, 11)
PY_314 = sys.version_info >= (3, 14)

T = TypeVar("T")

# The following is needed because some generic types (like asyncio.Task and
# weakref.ReferenceType) cannot be subscripted at runtime, even in Python 3.10+.
# We use TYPE_CHECKING to provide subscripted types for mypy while using
# unsubscripted types at runtime to avoid TypeError.
if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
    FutureBool = asyncio.Future[bool]
    ReferenceTypeTaskAny = ReferenceType[_TaskAny]
else:
    _TaskAny = asyncio.Task
    FutureBool = asyncio.Future
    ReferenceTypeTaskAny = ReferenceType


# PyTask compatibility patches for Python 3.14+
# In Python 3.14, asyncio separates C and Python implementations of key functions.
# PyTasks need both implementations synchronized for proper current_task() behavior.

if PY_314:
    from asyncio import AbstractEventLoop
    from asyncio.events import _get_running_loop as _c__get_running_loop
    from asyncio.events import (  # type: ignore[attr-defined]
        _py__get_running_loop,
        _py__set_running_loop,
    )
    from asyncio.events import _set_running_loop as _c__set_running_loop
    from asyncio.tasks import _enter_task as _c__enter_task
    from asyncio.tasks import _leave_task as _c__leave_task
    from asyncio.tasks import (  # type: ignore[attr-defined]
        _py_enter_task,
        _py_leave_task,
        _py_swap_current_task,
    )

    try:
        # _swap_current_task only exists in Python 3.14+
        from asyncio.tasks import (  # type: ignore[attr-defined,import-not-found]
            _swap_current_task as _c__swap_current_task,
        )
    except ImportError:
        # Fallback for Python < 3.14
        _c__swap_current_task = None  # type: ignore[assignment]

    if _c__get_running_loop is _py__get_running_loop:  # pragma: no cover
        _c__get_running_loop = None  # type: ignore[assignment]
        _c__set_running_loop = None  # type: ignore[assignment]
        _c__swap_current_task = None  # type: ignore[assignment]
        _c__enter_task = None  # type: ignore[assignment]
        _c__leave_task = None  # type: ignore[assignment]

    # Store original functions to avoid recursion
    _orig_py__get_running_loop = _py__get_running_loop
    _orig_py__set_running_loop = _py__set_running_loop
    _orig_py_swap_current_task = _py_swap_current_task
    _orig_py_enter_task = _py_enter_task
    _orig_py_leave_task = _py_leave_task

    # Combined functions that call both Python and C implementations

    def _py_c_set_running_loop(loop: AbstractEventLoop) -> None:
        _orig_py__set_running_loop(loop)
        _c__set_running_loop(loop)  # type: ignore[misc]

    def _py_c_get_running_loop() -> AbstractEventLoop:
        return _c__get_running_loop()  # type: ignore[misc]

    def _py_c_swap_current_task(task: _TaskAny) -> _TaskAny | None:
        prev = _orig_py_swap_current_task(task)
        _c__swap_current_task(task)  # type: ignore[misc]
        return prev  # type: ignore[no-any-return]

    def _py_c_enter_task(loop: AbstractEventLoop, task: _TaskAny) -> None:
        _orig_py_enter_task(loop, task)
        _c__enter_task(loop, task)  # type: ignore[misc]

    def _py_c_leave_task(loop: AbstractEventLoop, task: _TaskAny) -> None:
        _orig_py_leave_task(loop, task)
        _c__leave_task(loop, task)  # type: ignore[misc]

    def patch_pytask() -> None:
        """Patch asyncio to synchronize Python and C implementations for PyTask.

        This is needed for Python 3.14+ where asyncio separates C and Python
        implementations of key functions. PyTasks require both synchronized for
        proper current_task().
        """
        if _c__get_running_loop is None:
            return  # no C implementation available, skip patching
        if asyncio.events._get_running_loop is _py_c_get_running_loop:  # type: ignore[comparison-overlap]
            return  # already patched
        asyncio.events._get_running_loop = _py_c_get_running_loop  # type: ignore[assignment]
        asyncio.events._set_running_loop = _py_c_set_running_loop  # type: ignore[assignment]
        # patch the _py_* variants that PyTask.__step calls directly
        asyncio.tasks._py_enter_task = _py_c_enter_task  # type: ignore[assignment,attr-defined]
        asyncio.tasks._py_leave_task = _py_c_leave_task  # type: ignore[assignment,attr-defined]
        asyncio.tasks._py_swap_current_task = _py_c_swap_current_task  # type: ignore[assignment,attr-defined]

else:

    def patch_pytask() -> None:
        """No-op for Python versions < 3.14."""
        pass


# InterruptCondition compatibility
# Python 3.13+ handles CancelledError subclasses properly in Condition.wait()
if sys.version_info >= (3, 13):
    InterruptCondition = asyncio.Condition
else:

    class InterruptCondition(asyncio.Condition):
        """
        A class which fixes the lack of support in asyncio.Condition for arbitrary
        exceptions being raised during the lock.acquire() call in wait().
        """

        LockType = asyncio.Lock

        def __init__(self, lock: Any = None) -> None:
            if lock is None:  # pragma: no branch
                lock = self.LockType()
            super().__init__(lock)

        async def wait(self) -> Literal[True]:  # pragma: no cover
            """Wait until notified.

            If the calling coroutine has not acquired the lock when this
            method is called, a RuntimeError is raised.

            This method releases the underlying lock, and then blocks
            until it is awakened by a notify() or notify_all() call for
            the same condition variable in another coroutine.  Once
            awakened, it re-acquires the lock and returns True.
            """
            if not self.locked():
                raise RuntimeError("cannot wait on un-acquired lock")

            self.release()
            try:
                # _get_loop() is available from asyncio.Condition's _LoopBoundMixin base
                fut = self._get_loop().create_future()  # type: ignore[attr-defined]
                self._waiters.append(fut)  # type: ignore[attr-defined]
                try:
                    await fut
                    return True
                finally:
                    self._waiters.remove(fut)  # type: ignore[attr-defined]

            finally:
                # Must reacquire lock even if wait is cancelled.  We only
                # catch CancelledError (and subclasses) so that we don't get in the way
                # of KeyboardInterrupts or SystemExits or other serious errors.
                err = None
                while True:
                    try:
                        await self.acquire()
                        break
                    except asyncio.CancelledError as e:
                        err = e

                if err is not None:
                    try:
                        # re-raise the actual error caught
                        raise err
                    finally:
                        err = None  # break ref cycle
