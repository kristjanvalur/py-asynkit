from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from weakref import ReferenceType

"""Compatibility routines for earlier asyncio versions"""

__all__ = [
    "InterruptCondition",
    "patch_pytask",
    "enable_eager_tasks",
    "disable_eager_tasks",
]

# Python version checks
PY_311 = sys.version_info >= (3, 11)
PY_312 = sys.version_info >= (3, 12)
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

    def _py_c_swap_current_task(
        loop: AbstractEventLoop, task: _TaskAny
    ) -> _TaskAny | None:
        _orig_py_swap_current_task(loop, task)  # Keep Python bookkeeping in sync
        result = _c__swap_current_task(loop, task)  # type: ignore[misc]
        return result  # type: ignore[no-any-return]  # Use C version's return value

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

    if _orig_py_swap_current_task != _c__swap_current_task:
        _swap_current_task = _py_c_swap_current_task
    else:
        _swap_current_task = _orig_py_swap_current_task

else:

    def patch_pytask() -> None:
        """No-op for Python versions < 3.14."""
        pass


# swap_current_task compatibility
# use the native implementation if available, otherwise
# provide our own using leave and enter task functions
if not hasattr(asyncio.tasks, "_swap_current_task"):

    def swap_current_task(
        loop: asyncio.AbstractEventLoop, task: _TaskAny | None
    ) -> _TaskAny | None:
        """Swap the current task in the event loop.

        Returns the previous current task, or None if there was none.
        """
        old_task = asyncio.current_task()
        if old_task is not None:
            asyncio.tasks._leave_task(loop, old_task)
        if task is not None:
            asyncio.tasks._enter_task(loop, task)
        return old_task

else:
    from asyncio.tasks import (  # type: ignore[attr-defined,no-redef]  # noqa: F401
        _swap_current_task as swap_current_task,
    )

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


# Eager task execution compatibility
# State tracking for monkeypatching
_eager_tasks_enabled = False
_original_create_task: Callable[..., asyncio.Task[Any]] | None = None


def _detect_eager_start_support() -> bool:
    """Detect if native eager_start parameter is available in asyncio.create_task()."""
    import sys

    # eager_start parameter was added in Python 3.14
    return sys.version_info >= (3, 14)


def _detect_native_eager_task_factory() -> bool:
    """Detect if native asyncio.eager_task_factory is available."""
    import sys

    # eager_task_factory and create_eager_task_factory were both added in Python 3.12
    return sys.version_info >= (3, 12)


def enable_eager_tasks() -> None:
    """Enable comprehensive eager task execution across all Python versions.

    This function provides seamless cross-version compatibility by:

    1. **Python < 3.12**: Makes `asyncio.eager_task_factory` and
       `asyncio.create_eager_task_factory()` available using asynkit's implementation
    2. **All versions**: Enhances `asyncio.create_task()` with `eager_start`
       parameter support
    3. **Python 3.12+**: Uses native implementations when available for
       optimal performance

    After calling this function:

    ```python
    import asyncio
    import asynkit.compat

    asynkit.compat.enable_eager_tasks()

    # Now available on all Python versions:
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # Global eager execution

    # Or create custom factory (Python 3.12 API):
    factory = asyncio.create_eager_task_factory(asyncio.Task)
    loop.set_task_factory(factory)

    task = asyncio.create_task(my_coro(), eager_start=True)   # Per-task eager
    task = asyncio.create_task(my_coro(), eager_start=False)  # Standard behavior
    ```

    The implementation automatically chooses the best strategy:
    - Python < 3.12: Uses asynkit's eager implementation
    - Python 3.12+ with native support: Uses Python's native eager features
    - Python 3.12+ without native eager_start: Temporarily swaps task factory

    Can be called multiple times safely - subsequent calls are no-ops.
    """
    global _eager_tasks_enabled, _original_create_task

    if _eager_tasks_enabled:
        return  # Already enabled, nothing to do

    # Import asynkit's eager implementation
    from . import coroutine as _coroutine

    # 1. Make asyncio.eager_task_factory and create_eager_task_factory available on Python < 3.12
    if not _detect_native_eager_task_factory():
        asyncio.eager_task_factory = _coroutine.eager_task_factory  # type: ignore[attr-defined]
        asyncio.create_eager_task_factory = _coroutine.create_eager_task_factory  # type: ignore[attr-defined]

    # 2. Enhanced asyncio.create_task() with eager_start parameter
    _original_create_task = asyncio.create_task

    # Detect capabilities
    has_native_eager_start = _detect_eager_start_support()
    has_native_eager_factory = _detect_native_eager_task_factory()

    if has_native_eager_start:
        # Python 3.12+ with native eager_start support - leave it as-is
        pass  # No wrapping needed, native implementation already supports eager_start

    elif has_native_eager_factory:
        # Python 3.12+ without eager_start - use temporary factory swapping
        def enhanced_create_task(*args: Any, **kwargs: Any) -> asyncio.Task[Any]:
            eager_start = kwargs.pop("eager_start", None)

            if eager_start:
                # Use native eager_task_factory temporarily
                loop = asyncio.get_running_loop()
                old_factory = loop.get_task_factory()
                loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore[attr-defined]
                try:
                    return _original_create_task(*args, **kwargs)
                finally:
                    loop.set_task_factory(old_factory)
            else:
                # Standard behavior (eager_start is falsy or None)
                return _original_create_task(*args, **kwargs)

        # Apply the enhanced create_task
        asyncio.create_task = enhanced_create_task

    else:
        # Python < 3.12 - use our existing asynkit.coroutine.create_task implementation
        # It already supports eager_start parameter
        asyncio.create_task = _coroutine.create_task  # type: ignore[assignment]
    _eager_tasks_enabled = True


def disable_eager_tasks() -> None:
    """Disable eager task execution monkeypatching and restore original behavior.

    Restores `asyncio.create_task()` to its original implementation and removes
    any added `asyncio.eager_task_factory` attribute if it was added by asynkit.

    This is primarily useful for testing or when you need to temporarily disable
    the monkeypatching.
    """
    global _eager_tasks_enabled, _original_create_task

    if not _eager_tasks_enabled:
        return  # Not enabled, nothing to do

    # Restore original create_task only if we wrapped it
    if (
        _original_create_task is not None
        and asyncio.create_task is not _original_create_task
    ):
        asyncio.create_task = _original_create_task
        _original_create_task = None

    # Remove asyncio.eager_task_factory and create_eager_task_factory if we added them
    if not _detect_native_eager_task_factory():
        if hasattr(asyncio, "eager_task_factory"):
            delattr(asyncio, "eager_task_factory")
        if hasattr(asyncio, "create_eager_task_factory"):
            delattr(asyncio, "create_eager_task_factory")

    _eager_tasks_enabled = False
