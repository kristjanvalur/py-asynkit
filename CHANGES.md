# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2025

### Breaking Changes

- **Dropped Python 3.8 and 3.9 support**: Minimum Python version is now 3.10
  - Python 3.8 reached end-of-life in October 2024
  - Python 3.9 reaches end-of-life in October 2025
  - Modern Python 3.10+ syntax and features are now available throughout

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
