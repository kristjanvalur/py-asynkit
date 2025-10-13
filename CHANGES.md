# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2025

### Breaking Changes

- **Dropped Python 3.8 and 3.9 support**: Minimum Python version is now 3.10
  - Python 3.8 reached end-of-life in October 2024
  - Python 3.9 reaches end-of-life in October 2025
  - Modern Python 3.10+ syntax and features are now available throughout
- **Added Python 3.13 support**: Fully tested and working on Python 3.13
  - Updated anyio from 3.6.2 → 4.11.0
  - Updated trio from 0.21.0 → 0.31.0 (now supports Python 3.13+)
  - All 537 tests passing on Python 3.13.8
- **Added Python 3.14 support (with limitations)**: Python 3.14.0 is now supported with known limitations
  - Updated `task_factory` signature to accept `**kwargs` parameter (new in Python 3.14)
  - All core features work correctly on Python 3.14
  - **Known Issue**: Experimental `interrupt` module has limited functionality on Python 3.14.0
    - `create_pytask()` function affected by a bug in `asyncio.current_task()`
    - Python 3.14.0's `current_task()` does not recognize tasks created by custom task factories
    - Tests for `_PyTask` interruption are marked as xfail on Python 3.14
    - C Task interruption still has the same partial support as before
    - Bug has been reported to Python core team with minimal reproduction test case
    - Users requiring full interrupt functionality should use Python 3.10-3.13
- **Added PyPy 3.11 support**: Upgraded PyPy testing from 3.10 to 3.11
- **Added GraalPy 3.12 support**: GraalPy is now tested in CI to verify compatibility

### Dependencies

- **Upgraded anyio**: 3.6.2 → 4.11.0
  - Updated type annotations for `TaskStatus[Any]` compatibility
  - Updated exception handling for `ExceptionGroup` vs `BaseExceptionGroup`
  - Added `loop_factory` support for Python 3.12+ event loop creation
  - Removed redundant `exceptiongroup` dependency (now provided by anyio)
- **Upgraded trio**: 0.21.0 → 0.31.0
  - Now fully supports Python 3.13+ (trio 0.31.0 released September 2025)
  - Removed Python version restriction from dependency specification
  - All trio backend tests now run on Python 3.13

### API Improvements

- **Updated interrupt module for Python 3.14 compatibility**:
  - Modified `task_factory()` signature to accept `**kwargs` parameter
  - Python 3.14 changed task factory signature from `(loop, coro)` to `(loop, coro, **kwargs)`
  - Maintains backward compatibility with Python 3.10-3.13
- **Simplified Monitor API**: Removed legacy 3-argument exception signature from `Monitor.athrow()`
  - Old: `athrow(coro, type, value, traceback)` (deprecated since Python 3.12)
  - New: `athrow(coro, exc)` (single exception argument)
  - Removed redundant exception instantiation (coroutine.throw() handles both classes and instances)
  - Updated all internal uses in `coroutine.py` and `monitor.py`
- **Fixed Python 3.12+ deprecation warnings**: Updated all uses of `throw()` to modern single-argument form
  - Changed from `coro.throw(type(value), value)` to `coro.throw(value)`
  - Eliminated all deprecation warnings in test suite

### Build System & Tooling

- **Migrated from Poetry to uv**: Package management now uses `uv` (0.14.0)
  - 10-100x faster dependency resolution and installation
  - `pyproject.toml` converted to PEP 621 format
  - Build backend switched from `poetry-core` to `hatchling`
  - CI/CD workflows updated throughout
- **Replaced Black with Ruff**: Formatting and linting consolidated into a single tool
  - Configured with `target-version = "py310"` to enforce modern Python idioms
  - UP (pyupgrade) rules enabled to automatically modernize code patterns
- **Replaced blacken-docs with mdformat**: Documentation formatting uses `mdformat` with `mdformat-ruff`
- **Updated mypy configuration**: Set `python_version = "3.10"` for correct semantics

### Code Modernization

- **Applied Python 3.10+ type syntax** throughout:
  - `Optional[X]` → `X | None`
  - `Union[X, Y]` → `X | Y`
  - `List[int]` → `list[int]` (built-in generics)
  - 114 automatic fixes applied via pyupgrade
- **Added `from __future__ import annotations`** to all source files for consistency
- **Updated imports to `collections.abc`**: Moved `AsyncIterator`, `Callable`, `Coroutine`, `Generator`, etc. from `typing`
- **Cleaned up `compat.py`**: 79 lines of redundant compatibility code removed
  - `create_task()` wrapper removed (available in Python 3.10+)
  - `call_soon()` wrapper removed
  - `LoopBoundMixin` class removed
  - `LockHelper` class removed
  - Only Python 3.11+ version checks remain
- **Removed version-specific comments** that are no longer needed
- **Simplified `experimental.interrupt.InterruptCondition`**: Now inherits only from `asyncio.Condition`
- **Simplified `experimental.priority` classes**: `LockHelper` removed from base classes

## [0.12.0]

- Add `asynkit.experimental.priority` module for priority-based task scheduling

## [0.11.2]

- Add `InterruptException` and `InterruptCondition` to handle interruptions other than `CancelledError`

## [0.11.0]

- Remove `Deque` assumption in `AbstractSchedulingLoop`
- Remove frivolous "rotate" feature

## [0.10.5]

- Remove the "immediate" keyword from `task_throw()`

## [0.10.4]

- Allow C Tasks to be interrupted in most cases

## [0.10.3]

- Various minor fixes to `task_interrupt` and comments

## [0.10.2]

- Add the experimental `task_throw` and `task_interrupt` methods

## [0.10.1]

- Add the `aiter_sync()` function

## [0.10.0]

- Rename `coro_sync` to `await_sync`
- Add `Monitor.start()` and `Monitor.try_await()` methods
- Add support for PyPy
- Drop support for EOL Python 3.7
- Rename `MonitorAwaitable` to `BoundMonitor`, add convenience
- `BoundMonitor` is returned by calling `Monitor` with coroutine
- Add `aclose()` to `Monitor` and `BoundMonitor`

## [0.9.2]

- Rename `ensure_corofunc` to `asyncfunction`, add `syncfunction`

## [0.9.1]

- Add `ensure_corofunc`

## [0.9.0]

- Add `coro_sync`
- Add `CoroStart.aclose()` and related methods

## [0.8.0]

- Refactor, support scheduling functions for vanilla asyncio loop

## [0.7.0]

- Add `CoroStart.as_awaitable()` method
- Add `Monitor.awaitable()` method and `MonitorAwaitable` class
- Add the `coro_iter()` helper

## [0.6.0]

- Move Task creation out of the `CoroStart` class and into `coro_eager()` helper
- Add `Monitor` class and `GeneratorObject`
- Add anyio support for testing
- Add `asynkit.experimental.anyio` module

## [0.5.0]

- Make `CoroStart()` _awaitable_
- Simplify and make more robust
- Remove `auto_start`
- Add support for context variables in `CoroStart()`
