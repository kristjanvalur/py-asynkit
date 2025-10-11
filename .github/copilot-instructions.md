# GitHub Copilot Instructions for py-asynkit

## Interaction Style

Address the user as "boss" (they are the DI - Detective Chief Inspector). Style responses as a DS (Detective Sergeant) reporting findings:
- Professional and respectful
- Clear, direct updates on investigation progress
- "Right, boss" or "Yes, boss" acknowledgments
- Report findings methodically
- Ask clarifying questions when needed
- Summarize what's been accomplished

## Project Overview

**asynkit** is a toolkit for Python coroutines that provides advanced control over Python's `asyncio` module. It offers low-level coroutine manipulation, custom event loop implementations, and scheduling helpers.

### Key Features
- Helper tools for controlling coroutine execution (`CoroStart`, `Monitor`)
- Utility classes like `GeneratorObject` 
- Coroutine helpers including `coro_iter()` and `awaitmethod()` decorator
- Running async code from non-async code (`await_sync()`, `aiter_sync()`)
- Scheduling helpers and custom event-loop implementations
- Eager execution of Tasks (similar to C# async/await behavior)
- Experimental priority scheduling of Tasks
- Limited support for `anyio` and `trio` backends

## Project Structure

```
py-asynkit/
├── src/asynkit/
│   ├── coroutine.py       # Core coroutine manipulation tools (CoroStart, eager, await_sync)
│   ├── monitor.py         # Monitor class for suspending/resuming coroutines
│   ├── scheduling.py      # Task scheduling utilities (task_switch, sleep_insert)
│   ├── tools.py           # Helper utilities (cancelling context, create_task)
│   ├── loop/              # Custom event loop implementations
│   │   ├── eventloop.py   # Extended event loop base
│   │   ├── schedulingloop.py  # Custom scheduling loop
│   │   ├── extensions.py  # Event loop introspection tools
│   │   └── types.py       # Type aliases for compatibility
│   └── experimental/      # Experimental features
│       ├── interrupt.py   # Task interruption support
│       ├── priority.py    # Priority scheduling
│       └── anyio.py       # anyio backend integration
├── tests/                 # Unit tests mirroring src structure
├── examples/              # Example code demonstrating features
└── pyproject.toml         # Poetry configuration
```

## Development Setup

### Prerequisites
- Python 3.10+
- uv for dependency management

### Installation
```bash
uv sync
```

### Common Tasks (using poethepoet)
- `uv run poe test` - Run tests
- `uv run poe cov` - Run tests with coverage
- `uv run poe lint` - Run ruff linter
- `uv run poe format` - Format code with ruff
- `uv run poe typing` - Run mypy type checking
- `uv run poe check` - Run all checks (style, lint, typing, coverage)

## Important: Low-Level Implementation Details

**asynkit fundamentally works by accessing internal, undocumented implementation details of Python's asyncio module.** This includes:

- Direct manipulation of coroutine internals (`cr_frame`, `cr_await`, `gi_frame`)
- Calling low-level coroutine methods like `throw()`, `send()`, `close()`
- Manipulating event loop internals and the ready queue
- Accessing private asyncio attributes and methods
- Working with frame objects and execution state

**Implications for Type Checking:**
- Strict mypy type checking is **not always possible** for this codebase
- The Python type system doesn't expose these internal APIs properly
- `type: ignore` comments are sometimes **necessary and acceptable** when working with these low-level details
- Some type errors cannot be resolved without sacrificing functionality
- Focus on type safety for public APIs; internal implementation may need type bypasses

When adding type ignores for low-level operations, add a comment explaining why the bypass is necessary (e.g., "accessing internal asyncio implementation detail").

## Coding Conventions

### Style Guide
- **Formatting**: Ruff format (line length 88)
- **Imports**: Organized with ruff (isort-style)
- **Linting**: Ruff with E, F, I rules enabled
- **Type Checking**: Mypy for `asynkit.*` modules (strict where possible, pragmatic type ignores when needed for low-level operations)
- **Docstrings**: Triple-quoted strings for public APIs

### Type Annotations
- All public APIs must have complete type annotations
- Use `TypeVar`, `Generic`, `Protocol` for flexible typing
- Use `typing_extensions` for compatibility (ParamSpec, TypeAlias)
- Covariant/contravariant type vars where appropriate (`T_co`, `T_contra`)

### Naming Conventions
- **Public APIs**: Listed in `__all__` exports
- **Private functions**: Prefixed with underscore (e.g., `_coro_getattr`)
- **Async functions**: Clear `async def` signature
- **Coroutines**: Often named with `coro_*` prefix
- **Monitor methods**: Prefixed with `a` for async versions (e.g., `aawait`, `athrow`)

### Import Organization
1. Standard library imports
2. Third-party imports (asyncio, typing_extensions)
3. Local imports (relative from `.`)

## Prose Style Guidelines

When writing documentation, changelog entries, docstrings, or comments, follow this style:

### General Principles
- **Clear and technical**: Write in a clear, direct style that assumes technical competence
- **Conversational yet precise**: Use a friendly, approachable tone while maintaining technical accuracy
- **Explain motivation**: Don't just state what something does—explain why it's useful or what problem it solves
- **Use examples liberally**: Concrete code examples clarify abstract concepts
- **Emphasize with formatting**: Use **bold** for emphasis, _italics_ for terms, and `backticks` for code

### Documentation Style (README, Guides)
- **Lead with the problem**: Start sections by describing the pain point or use case
  - Example: "Did you ever wish that your _coroutines_ started right away...?"
- **Use rhetorical questions**: Engage readers by posing questions they might have
  - Example: "Now they can. Just decorate or convert them with..."
- **Show before-and-after**: When introducing improvements, contrast old approaches with new ones
- **Casual connectives**: Use phrases like "Notice how...", "Needless to say...", "In effect..."
- **Code speaks**: Let code examples carry the narrative, with brief explanatory text
- **Highlight key points**: Use phrases like "__right away__", "__directly__", "__as soon as possible__"

### Changelog Style (CHANGES.md)
- **Structured and scannable**: Use clear section headers (Breaking Changes, Build System, Code Modernization)
- **Lead with impact**: State user-facing changes first, then technical details
- **Bullet hierarchy**: Use sub-bullets to provide context and rationale under main points
- **Specific and concrete**: Name exact tools, versions, and what changed
  - Example: "Migrated from Poetry to uv (0.14.0)" not just "Changed build system"
- **Explain reasoning**: Add brief context for why changes were made
  - Example: "Python 3.8 reached end-of-life in October 2024"
- **Quantify when relevant**: Include numbers that show impact
  - Example: "10-100x speedup", "Removed 79 lines of redundant code"

### Code Comments Style
- **Lowercase, conversational**: Comments are lowercase and read naturally
  - Example: `# we can just merge them and don't need to heapify`
- **Explain algorithms**: Describe the reasoning behind implementation choices
  - Example: `# reversed is a heuristic because we are more likely to be looking for`
- **Note tradeoffs**: Mention alternative approaches and why they weren't chosen
  - Example: `# could mark the old entry as removed and re-add a new entry, that will be O(logn) instead of O(n) but lets not worry.`
- **Implementation rationale**: Explain why code is structured a particular way
  - Example: `# use only the __lt__ operator to determine if priority has changed since that is the one used to define priority for the heap`

### Docstrings Style
- **Start with action**: Begin with what the function/class does
  - Example: "Returns True if the coroutine has finished execution"
- **Brief first line**: First line is a concise summary (no "This function..." or "This method...")
- **Add context when needed**: Follow with detailed explanation if the behavior is subtle
- **Keep it minimal**: Don't over-document obvious behavior

### Technical Writing Patterns
- Use "Now they can" rather than "This can now be done"
- Prefer "allows you to" over "enables" or "permits"
- Say "right away" rather than "immediately" for emphasis
- Use "just" to make things sound simple: "just decorate", "just apply it"
- Employ contrast words: "Instead", "Unlike", "Needless to say"
- Phrase improvements as discoveries: "Did you ever wish...", "Now they can"

### Formatting Conventions
- **Bold**: For emphasis and key concepts
- _Italics_: For technical terms on first use, or for subtle emphasis
- `Backticks`: For all code elements (functions, classes, variables, types)
- __Double underscores__: For strong emphasis in Markdown
- Capitalize proper nouns: Python, C#, asyncio (lowercase), Task (when referring to asyncio.Task)

### What to Avoid
- Passive voice: Not "can be done" but "you can do"
- Overly formal: Not "utilizes" but "uses"
- Redundancy: Don't say "mypy type checking" (just "mypy")
- Qualification overkill: Trust the reader's intelligence
- Apologetic tone: Be confident about design decisions

## Key Concepts and Patterns

### CoroStart - Starting Coroutines Eagerly
`CoroStart` allows starting a coroutine and determining if it completed synchronously:
```python
start = CoroStart(my_coroutine())
if start.done():
    result = start.result()  # Get result synchronously
else:
    result = await start  # Await if still pending
```

### Monitor - Out-of-Band Communication
The `Monitor` class enables pausing coroutines and sending data out-of-band:
```python
m = Monitor()
coro = monitored_function(m, arg)
initial_data = await m.start(coro)  # Start and get initial OOB data
result = await m.aawait(coro, data)  # Resume with data
```

Key Monitor methods:
- `start()` - Start coroutine, catch first OOB data
- `aawait()` - Resume coroutine with data
- `athrow()` - Throw exception into coroutine
- `aclose()` - Close coroutine gracefully
- `oob()` - Send out-of-band data from within monitored coroutine

### GeneratorObject - Async Generator Protocol
Wraps coroutines to behave like async generators with `asend()` and `athrow()` methods.

### Eager Execution
The `@eager` decorator makes coroutines execute immediately until they block:
```python
@asynkit.eager
async def fetch_data():
    # Executes immediately, not when awaited
    return await remote_call()
```

### Scheduling Helpers
- `task_switch()` - Yield control to other tasks
- `sleep_insert(pos)` - Resume at specific position in ready queue
- `task_reinsert(task, pos)` - Place task at position in queue
- `runnable_tasks()` / `blocked_tasks()` - Introspect event loop state

### Running Async from Sync
- `await_sync(coro)` - Run coroutine synchronously (must not block)
- `aiter_sync(aiterable)` - Iterate async iterator synchronously

## Testing Guidelines

### Test Structure
- Tests mirror source structure in `tests/` directory
- Use pytest with anyio for async testing
- Mark async tests with `pytestmark = pytest.mark.anyio`

### Fixtures
- `anyio_backend` fixture can specify event loop type:
  - `"asyncio"` - Standard asyncio (default)
  - `("asyncio", {"policy": CustomPolicy()})` - Custom policy

### Common Test Patterns
```python
pytestmark = pytest.mark.anyio

async def test_feature():
    # Test async functionality
    result = await my_async_function()
    assert result == expected

def test_sync_feature():
    # Test synchronous wrapper
    result = await_sync(my_async_function())
    assert result == expected
```

### Coverage
- Aim for high coverage (`pytest --cov=asynkit`)
- Use `pragma: no cover` for version-specific branches
- Exclude lines: `pragma: no cover`, `@overload`, `@abstractmethod`, `assert False`, `TYPE_CHECKING`

## Working with Low-Level Coroutine APIs

### Coroutine Introspection
- `coro_is_new(coro)` - Check if coroutine hasn't started
- `coro_is_suspended(coro)` - Check if coroutine is paused
- `coro_is_finished(coro)` - Check if coroutine completed
- `coro_get_frame(coro)` - Get coroutine frame object

### Generator-based Coroutines
Use `@types.coroutine` decorator for generator-based coroutines that can be awaited.

### Exception Handling
- `SynchronousError` - Raised when async operation doesn't complete synchronously
- `SynchronousAbort` - BaseException for aborting synchronous execution
- `OOBData` - Exception carrying out-of-band data in Monitor protocol

## Compatibility Notes

### Python Version Support
- Minimum: Python 3.10
- Tested on: 3.10, 3.11, 3.12, PyPy 3.10
- Type hints: Use built-in generics (`list[int]`, `dict[str, int]`)
- Union syntax: Can use `X | Y` and `X | None` (Python 3.10+ feature)
- Generic syntax: Use old-style `Generic[T]` base class, not PEP 695 syntax (requires 3.12+)

### Platform Support
- Primary: Linux (Ubuntu)
- Tested: Windows (limited matrix)
- Event loops: Selector loop (all platforms), Proactor loop (Windows)

### Backend Support
- **asyncio**: Full support (primary backend)
- **anyio**: Supported with asyncio backend
- **trio**: Limited support via anyio

## Common Patterns to Follow

### Creating Tasks
Use `asynkit.tools.create_task()` for compatibility:
```python
from asynkit.tools import create_task
task = create_task(my_coroutine())
```

### Cancellation Context
Use `cancelling()` context manager for cancellation detection:
```python
async with cancelling() as c:
    await some_operation()
    if c.cancelled():
        # Handle cancellation
```

### Context Variables
Use `coro_await()` to run coroutines with specific context:
```python
context = contextvars.copy_context()
result = await coro_await(my_coro(), context=context)
```

### Custom Event Loops
Extend `AbstractSchedulingLoop` or use provided implementations:
- `SchedulingEventLoop` - With task introspection
- `PriorityEventLoop` - With priority scheduling (experimental)

## Documentation

### Docstring Style
- First line: Brief summary
- Empty line
- Detailed description
- Parameters/Returns documented inline when non-obvious
- Examples in docstrings for complex APIs

### README Examples
The README.md contains extensive examples - keep it in sync when adding features.

## Experimental Features

Features in `asynkit.experimental` are:
- Not guaranteed stable
- May be platform-specific
- Subject to change without deprecation
- Use with caution in production

Current experimental features:
- `task_interrupt()` - Interrupt running tasks
- `task_timeout()` - Timeout with interruption
- Priority scheduling
- anyio eager task groups

## Performance Considerations

- Eager execution reduces latency for IO-bound operations
- Direct coroutine manipulation has overhead - use judiciously
- Monitor adds overhead for OOB communication
- Custom event loops may impact throughput

## Common Pitfalls

1. **Forgetting to await Monitor operations**: `aawait()`, `athrow()`, `aclose()` must be awaited
2. **Mixing sync and async incorrectly**: `await_sync()` only works if coroutine doesn't actually suspend
3. **Not handling OOBData**: Monitor coroutines must catch and handle `OOBData` exceptions
4. **Event loop assumptions**: Custom loops may not support all asyncio features
5. **Generator vs Coroutine**: Use `@types.coroutine` when needed for generator-based coroutines

## Contributing Guidelines

When adding new features:
1. Add comprehensive type annotations
2. Update `__all__` exports
3. Add tests mirroring the module structure
4. Update README.md with examples
5. Run full check: `uv run poe check`
6. Consider backward compatibility (Python 3.10+)
7. Mark experimental features clearly

## Related Documentation

- Python asyncio docs: https://docs.python.org/3/library/asyncio.html
- PEP 492 (async/await): https://peps.python.org/pep-0492/
- anyio docs: https://anyio.readthedocs.io/
- Repository: https://github.com/kristjanvalur/py-asynkit
