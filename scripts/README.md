# Development Scripts

This directory contains development and build scripts for the py-asynkit project.

## C Code Formatting

The project includes optional C code formatting using clang-format. These scripts gracefully handle systems where clang-format is not installed.

### Cross-Platform Scripts

- **`format_c.py`** - Python script for C code formatting and style checking
  - `python scripts/format_c.py format` - Format all C files
  - `python scripts/format_c.py check` - Check C code formatting
  - Automatically skips if clang-format is not available

### Platform-Specific Scripts

#### Linux/macOS
- **`format_c.sh`** - Bash script to format C code
- **`check_c_style.sh`** - Bash script to check C code formatting

#### Windows
- **`format_c.bat`** - Batch script to format C code  
- **`check_c_style.bat`** - Batch script to check C code formatting

### Build Scripts

- **`fast_build.sh`** - Quick development build script for C extension

## Usage with poethepoet

The scripts are integrated with poethepoet tasks:

```bash
# Format all code (Python, C, and docs)
uv run poe formatall

# Format just C code
uv run poe format-c

# Check all code style
uv run poe check

# Check just C code style
uv run poe style-c
```

## clang-format Configuration

C code formatting uses `.clang-format` in the project root with:
- 4-space indentation (matching Python style)
- 88-character line limit (matching ruff)
- Linux brace style
- LLVM base style with customizations

## Cross-Platform Notes

- All scripts gracefully handle missing clang-format
- Windows batch files use native Windows commands
- Python script works on all platforms with Python 3.10+
- Exit codes: 0 = success, 1 = formatting needed/error