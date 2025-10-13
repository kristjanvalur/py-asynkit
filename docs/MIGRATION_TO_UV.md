# Migration from Poetry to uv

This project has been successfully migrated from Poetry to uv. This document explains the changes and how to use the new tooling.

## What Changed

### Build System
- **Before**: Poetry (`poetry-core`)
- **After**: Hatchling with PEP 621 metadata in `pyproject.toml`

### Dependency Management
- **Before**: Poetry with `poetry.lock`
- **After**: uv with `uv.lock`

### Project Metadata
- **Before**: `[tool.poetry]` section
- **After**: `[project]` section (PEP 621 standard)

## Installation

### Installing uv
```bash
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Setting up the development environment
```bash
# Sync all dependencies (including dev dependencies)
uv sync --all-extras

# Or just sync without dev dependencies
uv sync
```

## Usage

### Running Commands

#### Poetry commands → uv equivalents

| Poetry | uv | Description |
|--------|-----|-------------|
| `poetry install` | `uv sync --all-extras` | Install dependencies |
| `poetry add <package>` | `uv add <package>` | Add a dependency |
| `poetry add -D <package>` | `uv add --dev <package>` | Add a dev dependency |
| `poetry remove <package>` | `uv remove <package>` | Remove a dependency |
| `poetry run <cmd>` | `uv run <cmd>` | Run a command in the virtual environment |
| `poetry shell` | N/A (uv handles this automatically) | Activate virtual environment |
| `poetry build` | `uv build` | Build distribution packages |
| `poetry publish` | N/A (use twine or similar) | Publish to PyPI |

### Running Tests and Tools

All poethepoet tasks still work the same way:

```bash
# Run tests
uv run poe test

# Run tests with coverage
uv run poe cov

# Run linter
uv run poe lint

# Format code
uv run poe format

# Check code style without modifying
uv run poe style

# Format markdown documentation
uv run poe format-docs

# Check docs formatting without modifying
uv run poe style-docs

# Run type checking
uv run poe typing

# Run all checks (includes style, style-docs, lint, typing, cov)
uv run poe check
```

Or run tools directly:

```bash
uv run pytest tests examples
uv run mypy -p asynkit
uv run ruff format .
uv run ruff check .
```

## Key Changes in pyproject.toml

### Project Metadata
```toml
# Old (Poetry)
[tool.poetry]
name = "asynkit"
version = "0.12.0"
authors = ["Kristján Valur Jónsson <sweskman@gmail.com>"]

# New (PEP 621)
[project]
name = "asynkit"
version = "0.12.0"
authors = [
    {name = "Kristján Valur Jónsson", email = "sweskman@gmail.com"}
]
```

### Dependencies
```toml
# Old (Poetry)
[tool.poetry.dependencies]
python = "^3.9"
typing-extensions = "^4.4.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.1.1"

# New (PEP 621)
[project]
requires-python = ">=3.9"
dependencies = [
    "typing-extensions>=4.4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.1.1",
]
```

### Build System
```toml
# Old (Poetry)
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"

# New (Hatchling)
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Poethepoet Configuration
Added executor configuration to use simple mode instead of Poetry mode:

```toml
[tool.poe]
executor = {type = "simple"}
```

## CI/CD Changes

The `.github/workflows/ci.yml` has been updated to use uv:

- Replaced `actions-poetry@v2` with `astral-sh/setup-uv@v4`
- Changed `poetry install` to `uv sync --all-extras`
- Changed `poetry run` to `uv run`
- Changed `poetry build` to `uv build`

## Benefits of uv

1. **Speed**: uv is 10-100x faster than pip and Poetry
2. **Standards**: Uses PEP 621 standard metadata format
3. **Simplicity**: Single tool for Python version management, virtual environments, and dependencies
4. **Modern**: Built with Rust, actively maintained by Astral (creators of Ruff)
5. **Compatible**: Works with standard Python packaging tools

## Ruff as Single Linter and Formatter

The project now uses **Ruff** for both linting and formatting, replacing Black:

### Why Ruff Format?

- **Single tool**: One tool for both linting and formatting (no need for separate Black)
- **Speed**: 10-100x faster than Black
- **Compatible**: Ruff format is designed to be a drop-in replacement for Black
- **Unified**: Same configuration file, same execution model
- **Modern**: Actively developed by Astral

### Formatting Commands

```bash
# Format code
uv run poe format
# or directly:
uv run ruff format .

# Check formatting without modifying
uv run poe style
# or directly:
uv run ruff format . --check --diff

# Format markdown documentation (using mdformat with ruff)
uv run poe format-docs
# or directly:
uv run mdformat --number README.md

# Format everything (code + docs)
uv run poe formatall
```

**Note**: The `--number` flag applies consecutive numbering (1, 2, 3...) to ordered lists instead of normalizing them all to `1.`

### Migration Notes

- Ruff format output is nearly identical to Black (intentionally compatible)
- All existing Black-formatted code works with Ruff format
- Line length and other style settings are preserved
- **mdformat-ruff** replaces blacken-docs for formatting code in markdown files
- Black has been completely removed from dependencies

## Testing with Different Python Versions

uv makes it easy to test your code with different Python versions without having to install them system-wide.

### Installing Python Versions

uv can automatically download and manage Python versions:

```bash
# Install a specific Python version
uv python install 3.10
uv python install 3.11
uv python install 3.12

# List installed Python versions
uv python list

# Install all supported versions for this project
uv python install 3.10 3.11 3.12
```

### Creating Virtual Environments with Specific Python Versions

```bash
# Create a virtual environment with Python 3.10
uv venv --python 3.10 .venv-3.10

# Create a virtual environment with Python 3.11
uv venv --python 3.11 .venv-3.11

# Create a virtual environment with Python 3.12
uv venv --python 3.12 .venv-3.12
```

### Running Tests with a Specific Python Version

Once you've created a virtual environment for a specific Python version:

```bash
# Sync dependencies for that environment
uv sync --python 3.10

# Run tests with Python 3.10
uv run --python 3.10 poe test

# Or run pytest directly
uv run --python 3.10 pytest tests examples

# Run full test suite with coverage
uv run --python 3.10 poe cov
```

### Quick Test Across All Versions

You can test across multiple Python versions without creating separate virtual environments:

```bash
# Test with Python 3.10
uv run --python 3.10 pytest tests

# Test with Python 3.11
uv run --python 3.11 pytest tests

# Test with Python 3.12
uv run --python 3.12 pytest tests
```

### Testing with PyPy

PyPy is also supported:

```bash
# Install PyPy
uv python install pypy@3.10

# Run tests with PyPy
uv run --python pypy@3.10 pytest tests
```

### Testing with GraalPy

GraalPy is also supported:

```bash
# Install GraalPy
uv python install graalpy-24.1

# Run tests with GraalPy
uv run --python graalpy-24.1 pytest tests
```

### Automated Multi-Version Testing

For CI/CD-like testing locally, you can create a simple script:

```powershell
# test-all-versions.ps1
$versions = @("3.10", "3.11", "3.12")
foreach ($version in $versions) {
    Write-Host "Testing with Python $version"
    uv run --python $version pytest tests
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Tests failed for Python $version"
        exit $LASTEXITCODE
    }
}
Write-Host "All tests passed!"
```

Or on Unix-like systems:

```bash
# test-all-versions.sh
for version in 3.10 3.11 3.12; do
    echo "Testing with Python $version"
    uv run --python $version pytest tests || exit 1
done
echo "All tests passed!"
```

## Troubleshooting

### "Package not found"
Make sure you've run `uv sync --all-extras` to install all dependencies.

### "Command not found: uv"
Install uv using the installation instructions above.

### poethepoet tasks fail
Make sure the `[tool.poe]` section has `executor = {type = "simple"}` in `pyproject.toml`.

## More Information

- [uv Documentation](https://docs.astral.sh/uv/)
- [PEP 621 (Project Metadata)](https://peps.python.org/pep-0621/)
- [Hatchling Documentation](https://hatch.pypa.io/latest/config/build/)
