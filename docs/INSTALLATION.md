# Installation Options for asynkit

## Standard Installation (Recommended)

```bash
pip install asynkit
```

This automatically selects the best option:

1. **Binary wheel** with C extension (4-5x faster) if available for your platform
2. **Pure Python wheel** for universal compatibility
3. **Source compilation** as final fallback

## Force Source Compilation

For custom optimizations or debug builds:

```bash
# Force source compilation with custom flags
CFLAGS="-march=native -O3" pip install --no-binary=asynkit asynkit

# Build debug version
ASYNKIT_DEBUG=1 pip install --no-binary=asynkit asynkit

# Disable C extension entirely
ASYNKIT_DISABLE_CEXT=1 pip install --no-binary=asynkit asynkit
```

## Check Your Installation

```python
import asynkit

info = asynkit.get_implementation_info()
print(f"Using: {info['implementation']}")
print(f"Performance: {info['performance_info']}")
```

## Platform Coverage

- **Binary wheels**: Windows, macOS, Linux × Python 3.10-3.14 (95% of users)
- **Pure Python wheel**: Universal fallback for any platform/version
- **Source distribution**: Custom compilation for specific needs
