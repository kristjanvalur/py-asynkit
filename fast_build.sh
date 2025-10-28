#!/bin/bash
# Fast C extension development script

set -e  # Exit on error

echo "=== Fast C Extension Build ==="

# Clean any existing build artifacts
echo "Cleaning build artifacts..."
rm -rf build/
rm -f src/asynkit/_cext*.so

# Rebuild the extension
echo "Building C extension..."
source .venv/bin/activate
python setup.py build_ext --inplace

# Test if it worked
echo "Testing C extension..."
python -c "
try:
    from asynkit._cext import CoroStart
    print('✓ C extension imports successfully')
    
    import asyncio
    async def test_coro():
        return 'test'
    
    cs = CoroStart(test_coro())
    print(f'✓ CoroStart created: {type(cs)}')
    
    iterator = cs.__await__()
    print(f'✓ __await__ works: {type(iterator)}')
    
except Exception as e:
    print(f'✗ C extension failed: {e}')
    exit(1)
"

echo "=== Build Complete ==="