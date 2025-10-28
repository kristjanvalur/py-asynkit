#!/bin/bash
# Check C code formatting with clang-format
# Optional - skips gracefully if clang-format is not available

set -e

cd "$(dirname "$0")/.."

# Check if clang-format is available
if ! command -v clang-format >/dev/null 2>&1; then
    echo "⚠️  clang-format not found - skipping C code style check"
    echo "   Install clang-format for C code style validation"
    exit 0
fi

echo "✅ Checking C code formatting..."

# Find all C source files and check formatting
exit_code=0
checked_count=0

find src/asynkit/_cext -name "*.c" -o -name "*.h" 2>/dev/null | while read -r file; do
    if [ -f "$file" ]; then
        echo "  🔍 Checking: $file"
        if clang-format --dry-run --Werror "$file" >/dev/null 2>&1; then
            echo "    ✅ $file is properly formatted"
        else
            echo "    ❌ $file is not properly formatted"
            # Show first few formatting issues
            clang-format --dry-run --Werror "$file" 2>&1 | head -n 5
            exit_code=1
        fi
        checked_count=$((checked_count + 1))
    fi
done

if [ $checked_count -eq 0 ]; then
    echo "ℹ️  No C files found to check"
    exit 0
fi

if [ $exit_code -eq 0 ]; then
    echo "✅ All $checked_count C files are properly formatted!"
else
    echo "❌ Some C files need formatting. Run: uv run poe format-c"
    exit 1
fi