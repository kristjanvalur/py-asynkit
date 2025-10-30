# Optional C Extension Strategy for asynkit

## Current Implementation Status ✅

We already implement several best practices:

1. **Graceful Fallback**: `src/asynkit/coroutine.py` automatically uses Python implementation if C extension unavailable
2. **Optional Build**: `setup.py` marks extension as `optional=True`
3. **Environment Control**: `ASYNKIT_DISABLE_CEXT` environment variable
4. **Platform Detection**: Automatically skips PyPy builds

## Industry Best Practices Research

### **Wheel Distribution Strategy**

**Standard Approach:**
- Use **cibuildwheel** for automated wheel building across platforms
- Cover major platforms: Windows (x64), macOS (x64/arm64), Linux (x64/aarch64)
- Support Python 3.10-3.14+ (our current range: 3.10+)
- Total wheels: ~40-60 variants

**Example from successful projects:**
```yaml
# .github/workflows/wheels.yml (cibuildwheel approach)
- uses: pypa/cibuildwheel@v2.16.2
  env:
    CIBW_BUILD: "cp310-* cp311-* cp312-* cp313-* cp314-*"
    CIBW_SKIP: "*-musllinux_* pp*"  # Skip PyPy, musl variants
```

### **Fallback Mechanisms**

**1. Import-Time Fallback (Current - GOOD):**
```python
try:
    from ._cext import CoroStartBase as _CCoroStartBase
    _HAVE_C_EXTENSION = True
except ImportError:
    _CCoroStartBase = None
    _HAVE_C_EXTENSION = False
```

**2. Enhanced Setup.py Error Handling:**
```python
class OptionalBuildExt(build_ext):
    """Custom build_ext that gracefully handles C extension failures."""
    
    def build_extension(self, ext):
        try:
            super().build_extension(ext)
            print(f"✓ Successfully built {ext.name}")
        except Exception as e:
            print(f"⚠ Failed to build {ext.name}: {e}")
            print("  → asynkit will use Python implementation")
```

**3. Runtime Feature Detection:**
```python
def get_implementation_info():
    """Return information about which implementation is active."""
    if _HAVE_C_EXTENSION:
        import asynkit._cext
        return {
            'implementation': 'C extension',
            'build_info': asynkit._cext.get_build_info(),
            'performance_multiplier': '4-5x faster'
        }
    else:
        return {
            'implementation': 'Pure Python',
            'performance_multiplier': '1x (baseline)'
        }
```

## Recommended Implementation Plan

### **Phase 1: Enhanced Build Robustness**

1. **Custom build_ext class** to handle compilation failures gracefully
2. **Compiler detection** to skip build if tools unavailable
3. **Better user messaging** about what's happening

### **Phase 2: CI/CD Wheel Building**

1. **GitHub Actions** workflow with cibuildwheel
2. **Platform matrix**: Windows/macOS/Linux × Python 3.10-3.14
3. **PyPI upload** automation for releases

### **Phase 3: Documentation & User Experience**

1. **Installation guide** explaining wheel vs source install
2. **Performance benchmarks** showing C extension benefits
3. **Troubleshooting** for build issues

## Immediate Next Steps

The most impactful improvement would be implementing a custom `build_ext` class that:

1. **Catches compilation errors** and continues with Python-only install
2. **Provides clear messaging** about what happened
3. **Gives installation guidance** for users who want the C extension

This would make `pip install asynkit` always succeed, even without build tools.

## Example Error Messages

**Good user experience:**
```
Building C extension... FAILED
→ Continuing with Python implementation
→ Install build tools for 4x performance boost: 
  pip install setuptools-cpp-build-tools  # or platform equivalent
```

**Bad user experience:**
```
error: Microsoft Visual C++ 14.0 is required
Command "python setup.py egg_info" failed
```

## Conclusion

asynkit is already well-positioned with good fallback mechanisms. The main improvements needed are:

1. **Robust build error handling** (highest impact)
2. **Automated wheel building** (best user experience)  
3. **Clear documentation** (reduces support burden)