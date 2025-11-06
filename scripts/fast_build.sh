#!/bin/bash
# Fast C extension development script for uv

set -e  # Exit on error

# Force C extension compilation and fail on errors
export ASYNKIT_FORCE_CEXT=1

# Parse command line arguments
BUILD_TYPE="optimized"
if [[ "$1" == "debug" ]]; then
    BUILD_TYPE="debug"
    export ASYNKIT_DEBUG=1
    echo "=== Fast C Extension Build (uv) - DEBUG MODE ==="
elif [[ "$1" == "optimized" || "$1" == "" ]]; then
    BUILD_TYPE="optimized"
    unset ASYNKIT_DEBUG
    echo "=== Fast C Extension Build (uv) - OPTIMIZED MODE ==="
else
    echo "Usage: $0 [debug|optimized]"
    echo "  debug     - Build with -g -O0 -DDEBUG flags"
    echo "  optimized - Build with -O3 -DNDEBUG flags (default)"
    exit 1
fi

# Clean any existing build artifacts
echo "Cleaning build artifacts..."
rm -rf build/
rm -f src/asynkit/_cext*.so

# Rebuild the extension with uv
echo "Building C extension with uv..."
uv sync --reinstall-package asynkit

# Test if it worked
echo "Testing C extension..."
uv run python -c "
try:
    from asynkit._cext import get_build_info, CoroStartBase
    
    # Get build info from C extension
    build_info = get_build_info()
    print(f'✓ C extension loaded successfully')
    print(f'  Build type: {build_info[\"build_type\"]}')
    
    # Quick functional test
    import asyncio
    async def test_coro():
        return 'test'
    
    cs = CoroStartBase(test_coro())
    print(f'✓ CoroStartBase functional test passed')
    
except Exception as e:
    print(f'✗ C extension failed: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
"

echo "=== Build Complete ==="