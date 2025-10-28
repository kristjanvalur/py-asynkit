#!/bin/bash
# Format all C files in the asynkit C extension
# Optional - skips gracefully if clang-format is not available

set -e

cd "$(dirname "$0")/.."

# Check if clang-format is available
if ! command -v clang-format >/dev/null 2>&1; then
    echo "⚠️  clang-format not found - skipping C code formatting"
    echo "   Install clang-format for C code formatting support"
    exit 0
fi

echo "✅ Formatting C code with clang-format..."

# Find all C source files in _cext directory
formatted_count=0
find src/asynkit/_cext -name "*.c" -o -name "*.h" 2>/dev/null | while read -r file; do
    if [ -f "$file" ]; then
        echo "  📝 Formatting: $file"
        clang-format -i "$file"
        formatted_count=$((formatted_count + 1))
    fi
done

echo "✅ C code formatting complete!"