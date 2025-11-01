#!/bin/bash
# Fast C extension development script for uv

set -e  # Exit on error

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
    import asynkit._cext
    print(f'✓ C extension imports successfully: {dir(asynkit._cext)}')
    
    # Check if this is actually a C extension or a Python module
    module_file = getattr(asynkit._cext, '__file__', 'No __file__ attribute')
    print(f'Module __file__: {module_file}')
    
    if module_file and module_file.endswith('.py'):
        print('✗ WARNING: _cext is a Python module, not a C extension!')
        print('This suggests the C extension failed to build and Python is importing a fallback.')
        exit(1)
    elif module_file and (module_file.endswith('.so') or module_file.endswith('.pyd')):
        print('✓ Confirmed: _cext is a proper C extension')
    else:
        print(f'? Unknown module type: {module_file}')
    
    # Check for CoroStartBase (the proper export)
    if hasattr(asynkit._cext, 'CoroStartBase'):
        CoroStartClass = asynkit._cext.CoroStartBase
        print('✓ Found CoroStartBase')
    elif hasattr(asynkit._cext, 'CoroStart'):
        CoroStartClass = asynkit._cext.CoroStart  
        print('✓ Found CoroStart (fallback)')
    else:
        print('✗ No CoroStart or CoroStartBase found')
        exit(1)
    
    import asyncio
    async def test_coro():
        return 'test'
    
    cs = CoroStartClass(test_coro())
    print(f'✓ CoroStartBase created: {type(cs)}')
    print(f'✓ Done: {cs.done()}')
    
    iterator = cs.__await__()
    print(f'✓ __await__ works: {type(iterator)}')
    
except Exception as e:
    print(f'✗ C extension failed: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
"

echo "=== Build Complete ==="