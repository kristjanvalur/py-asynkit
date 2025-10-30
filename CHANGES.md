# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Performance Improvements

- **C Extension Optimization**: Implemented major performance enhancements for coroutine operations
  - Added PyIter_Send API optimization providing 4.66x direct performance improvement over Python method calls
  - Integrated PyContext_Enter/Exit direct C API calls for context handling optimization
  - C extension now delivers 5.52x speedup compared to baseline Python implementation
  - Performance within 13% of Python 3.12 native asyncio implementation

### Build System Enhancements

- **Comprehensive Build Configuration**: Enhanced setup.py with environment-controlled optimization
  - Added debug/optimized build modes via ASYNKIT_DEBUG environment variable
  - Optimized builds use -O3 -DNDEBUG flags, debug builds use -g -O0 -DDEBUG
  - Added get_build_info() C function for runtime build configuration detection
  - Custom OptionalBuildExt class provides graceful compilation failure handling with platform-specific guidance

### Distribution and Packaging

- **Multi-Platform Wheel Strategy**: Implemented comprehensive wheel building pipeline
  - Automated wheel building for Windows/macOS/Linux across Python 3.10-3.14 using cibuildwheel
  - Added pure Python wheel (py3-none-any) for universal platform compatibility
  - Maintains source distribution for custom compilation scenarios
  - Enhanced installation documentation with clear wheel selection priority
  - Users get optimal performance automatically: binary wheel → pure Python wheel → source compilation

### Developer Experience

- **Runtime Implementation Detection**: Added get_implementation_info() function for transparency
  - Users can check which implementation (C extension vs Pure Python) is active
  - Provides performance information and build details at runtime
  - Accessible via `asynkit.get_implementation_info()`
  - Clear documentation of 4-5x performance benefits from C extension

### Documentation

- **Installation Guide**: Enhanced README with comprehensive installation instructions
  - Explains automatic C extension detection and platform compatibility
  - Documents manual compilation option with `pip install --no-binary=asynkit asynkit`
  - Provides runtime verification examples
  - Created detailed optional C extension strategy documentation in docs/

## [0.14.2] - 2025-10-30

### Bug Fixes

- **Context Truthiness Bug**: Fixed critical performance inconsistency in Python `CoroStart` implementation
  - The Python implementation was incorrectly using `if self.context:` instead of `if self.context is not None:`
  - Empty contexts (which evaluate to `False`) would bypass `context.run()` calls in Python but not in C extension
  - This caused performance discrepancies between C and Python implementations
  - Fixed in `_start()`, `__await__()`, and `athrow()` methods of `CoroStart` class
  - Ensures consistent context handling behavior across both implementations

## [0.14.1] - 2025-10-25

### New Features

- **Cross-Version Eager Task Compatibility**: Added comprehensive monkeypatching support for eager task execution across Python 3.10-3.14+
  - `asynkit.compat.enable_eager_tasks()` function provides seamless `asyncio.create_task(eager_start=True)` support on all Python versions
  - `asynkit.compat.disable_eager_tasks()` function for clean restoration of original asyncio behavior
  - Version-aware strategy selection automatically chooses optimal implementation:
    - Python 3.10-3.11: Direct delegation to `asynkit.coroutine.create_task`
    - Python 3.12-3.13: Temporary factory swapping with native `eager_task_factory`
    - Python 3.14+: No wrapping needed (native `eager_start` support detected)
  - Makes `asyncio.eager_task_factory` available across all Python versions
  - Future-proof design automatically adapts to new Python releases
  - Comprehensive test suite with 17 tests covering all scenarios and edge cases

### Compatibility Improvements

- **Python 3.14 Support**: First library to detect and leverage Python 3.14's native `eager_start` parameter support
  - Confirmed `eager_start` parameter availability in Python 3.14.0rc2
  - Automatic detection avoids unnecessary wrapping when native support exists
  - Version-based detection using `sys.version_info` for optimal performance
  - Maintains backward compatibility while preparing for future Python versions

### Documentation

- **Cross-Version Compatibility Guide**: Added comprehensive documentation in README.md
  - Usage examples and migration scenarios
  - Implementation strategy table showing approach per Python version
  - Benefits and performance considerations
  - Complete API reference for new compatibility functions

## [0.14.0] - 2025

### New Features

- **Eager Task Factory**: Added comprehensive eager task factory implementation with Python 3.12 API compatibility
  - `create_eager_factory()` function for creating custom eager task factories
  - `eager_task_factory` module-level instance ready for immediate use
  - Provides the same API as Python 3.12's native `asyncio.eager_task_factory` while supporting Python 3.10+
  - Version-aware context parameter support (Python 3.11+ only)
  - Enhanced `TaskLikeFuture` constructor accepting name and context parameters
  - Performance improvements: 1,000x+ reduction in task startup latency
  - Comprehensive documentation and performance analysis in `docs/eager_task_factory_performance.md`
  - Usage: `loop.set_task_factory(asynkit.eager_task_factory)` enables global eager execution

### Performance Improvements

- **Massive task startup optimization**: Benchmarking shows dramatic latency improvements
  - Python 3.12 eager_task_factory: 2,447x faster than standard asyncio (0.92 μs vs 2,263 μs)
  - asynkit eager_task_factory: 1,493x faster than standard asyncio (1.52 μs vs 2,263 μs)

### Bug Fixes

- **Fixed mypy unused-ignore warnings**: Added `tests.test_anyio` to modules with disabled unused-ignore warnings
  - Resolves version-specific import issues with `exceptiongroup` module across Python versions

## [0.13.1] - 2025

### Bug Fixes

- **Fixed Python 3.14 PyTask compatibility**: Added `patch_pytask()` function to synchronize C and Python asyncio implementations
  - Python 3.14 separates C (`_c_*`) and Python (`_py_*`) implementations of core asyncio functions
  - PyTasks require both implementations synchronized for proper `current_task()` behavior
  - `patch_pytask()` is automatically called by `create_pytask()` when needed
  - Removes the Python 3.14 limitation from the experimental interrupt module
  - All 30 pytask tests now pass on Python 3.14.0rc2

### Code Modernization

- **Improved import organization**: Moved `patch_pytask` import to module level in interrupt.py
- **Enhanced type annotations**: Added proper type ignore comments for Python 3.14-specific asyncio attributes

### Performance Optimizations

- **Optimized InterruptCondition for Python 3.13+**: Moved `InterruptCondition` to `compat` module with version-specific implementation
  - On Python 3.13+: `InterruptCondition` is now an alias to `asyncio.Condition` for optimal performance
  - On Python < 3.13: Uses custom class with enhanced exception handling for `CancelledError` subclasses
  - Python 3.13+ fixed the bug where `asyncio.Condition.wait()` didn't properly handle `CancelledError` subclasses ([CPython PR #112201](https://github.com/python/cpython/pull/112201))
  - Maintains full backward compatibility while improving performance on newer Python versions

### Testing

- **Added Python 3.12+ eager task factory testing support**:
  - Parametrized `TestCoroAwait` class to run with both standard and eager task execution modes
  - Tests verify that `coro_await()` wrapper works correctly with `asyncio.eager_task_factory`
  - Automatically skips eager mode tests on Python < 3.12
  - Added `eager_tasks` pytest marker for test identification
  - Documentation in `tests/EAGER_TASK_TESTING.md` explains scope and limitations

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
- **Added Python 3.14 support**: Python 3.14.0 is now fully supported
  - Updated `task_factory` signature to accept `**kwargs` parameter (new in Python 3.14)
  - All core features work correctly on Python 3.14
  - **Previous Known Issue (Now Resolved)**: Experimental `interrupt` module initially had limited functionality on Python 3.14.0
    - Issue was due to separated C and Python asyncio implementations requiring synchronization
    - **Fixed in v0.13.1**: Added `patch_pytask()` compatibility function for full PyTask support
    - C Task interruption has the same partial support as all Python versions
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
