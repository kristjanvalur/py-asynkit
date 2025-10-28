"""
Example of how to parametrize tests over Python/C implementations
"""

import pytest
import asynkit.coroutine as coroutine_module


# Collect available implementations
def get_corostart_implementations():
    implementations = [
        ("python", coroutine_module.PyCoroStart),
    ]

    # Add C implementation if available
    if hasattr(coroutine_module, "_CCoroStart") and coroutine_module._CCoroStart:
        implementations.append(("c", coroutine_module._CCoroStart))

    return implementations


# Parametrize over available implementations
@pytest.mark.parametrize("impl_name,impl_class", get_corostart_implementations())
async def test_corostart_basic_functionality(impl_name, impl_class):
    """Test that both Python and C implementations behave identically"""

    async def sample_coro():
        return 42

    # Test the specific implementation
    cs = impl_class(sample_coro())
    assert cs.done()
    assert cs.result() == 42

    print(f"✅ {impl_name} implementation works correctly")


# Test C-specific behavior when available
def test_c_implementation_performance():
    """Test C implementation specific features"""
    if not hasattr(coroutine_module, "_CCoroStart") or not coroutine_module._CCoroStart:
        pytest.skip("C implementation not available")

    # C-specific tests here
    assert coroutine_module._CCoroStart is not None


# Monkeypatch example for forcing specific implementations
async def test_force_python_implementation(monkeypatch):
    """Test forcing Python implementation via monkeypatch"""

    # Temporarily force Python implementation
    original_corostart = coroutine_module.CoroStart
    monkeypatch.setattr(coroutine_module, "CoroStart", coroutine_module.PyCoroStart)

    # Now all code will use Python implementation
    async def sample_coro():
        return "forced_python"

    cs = coroutine_module.CoroStart(sample_coro())
    assert cs.done()
    assert cs.result() == "forced_python"

    # Verify we're actually using Python implementation
    assert type(cs).__name__ == "CoroStart"  # Python class name
