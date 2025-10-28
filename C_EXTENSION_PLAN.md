# C Extension for CoroStart - Implementation Plan

## Objective

Implement a C extension version of `CoroStart` to eliminate the Python-level iterator overhead that occurs on every suspend/resume cycle of wrapped coroutines.

## Performance Problem

The current Python implementation of `CoroStart.__await__()` uses a generator:

```python
def __await__(self):
    return (yield from self._coro)
```

**The Issue:** When the wrapped coroutine suspends 100 times (e.g., `await asyncio.sleep(0)` in a loop):
- The event loop unwinds the stack 100 times, passing through this generator
- The event loop re-enters this generator 100 times on resume
- That's 200 Python generator frame operations just for the wrapper
- Each operation involves Python bytecode execution, frame creation/destruction, and `yield from` protocol overhead

For high-frequency coroutines (1000+ suspend/resume cycles), this overhead is significant.

## Solution: C Extension with Direct Delegation

Implement `CoroStart` in C as a transparent iterator that directly delegates to the wrapped coroutine's `tp_iternext` slot. No Python generator frames, no bytecode execution in the hot path.

### Key Insight from CPython

CPython's `_PyCoroWrapper_Type` (used for `coro.__await__()`) already does exactly this:

```c
// From Objects/genobject.c
static PyObject *
coro_wrapper_iternext(PyObject *self)
{
    PyCoroWrapper *cw = _PyCoroWrapper_CAST(self);
    return gen_iternext((PyObject *)cw->cw_coroutine);  // Direct delegation!
}
```

**No state machine needed** - the wrapped coroutine already maintains all generator state (frame, instruction pointer, locals). Our C wrapper is just a fast pass-through.

## Implementation Strategy

### 1. C Type Structure

```c
typedef struct {
    PyObject_HEAD
    PyObject *wrapped_coro;  // The wrapped coroutine
    int started;             // Have we started execution?
    PyObject *result;        // Cached result if completed synchronously
    int done;                // Has execution finished?
} CoroStartObject;
```

### 2. Iterator Protocol Implementation

```c
static PyTypeObject CoroStartType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "asynkit._cext.CoroStart",
    .tp_basicsize = sizeof(CoroStartObject),
    .tp_dealloc = corostart_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_traverse = corostart_traverse,
    .tp_iter = PyObject_SelfIter,         // Return self
    .tp_iternext = corostart_iternext,    // Forward to wrapped coro
    .tp_methods = corostart_methods,      // send, throw, close
};
```

### 3. Critical Functions

**Starting the coroutine:**
```c
static PyObject *
corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    PyObject *coro;
    if (!PyArg_ParseTuple(args, "O", &coro)) {
        return NULL;
    }
    
    CoroStartObject *self = (CoroStartObject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    
    self->wrapped_coro = Py_NewRef(coro);
    self->started = 0;
    self->done = 0;
    self->result = NULL;
    
    // Try to start the coroutine immediately
    PyObject *initial = Py_TYPE(coro)->tp_iternext(coro);
    if (initial == NULL) {
        // Coroutine completed synchronously
        if (PyErr_Occurred() && PyErr_ExceptionMatches(PyExc_StopIteration)) {
            // Extract result from StopIteration
            PyObject *exc_value;
            PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
            if (exc_value) {
                self->result = PyObject_GetAttrString(exc_value, "value");
                Py_DECREF(exc_value);
            }
            PyErr_Clear();
            self->done = 1;
        }
    } else {
        // Coroutine suspended - put the value back
        Py_DECREF(initial);
    }
    self->started = 1;
    
    return (PyObject *)self;
}
```

**Iterator next (the hot path):**
```c
static PyObject *
corostart_iternext(PyObject *self)
{
    CoroStartObject *cs = (CoroStartObject *)self;
    
    if (cs->done) {
        // Already completed
        if (cs->result != NULL) {
            PyErr_SetObject(PyExc_StopIteration, cs->result);
        } else {
            PyErr_SetNone(PyExc_StopIteration);
        }
        return NULL;
    }
    
    // Direct delegation - no generator state needed!
    return Py_TYPE(cs->wrapped_coro)->tp_iternext(cs->wrapped_coro);
}
```

**Send method:**
```c
static PyObject *
corostart_send(PyObject *self, PyObject *arg)
{
    CoroStartObject *cs = (CoroStartObject *)self;
    
    if (cs->done) {
        PyErr_SetString(PyExc_StopIteration, "coroutine already finished");
        return NULL;
    }
    
    // Direct call to wrapped coroutine's send
    return PyObject_CallMethod(cs->wrapped_coro, "send", "O", arg);
}
```

### 4. Module Structure

Create `src/asynkit/_cext/corostart.c` with:
- Module initialization
- Type definition and setup
- Factory function exposed to Python

### 5. Build Configuration

Update `pyproject.toml` to include C extension:
```toml
[tool.setuptools]
ext-modules = [
    {name = "asynkit._cext", sources = ["src/asynkit/_cext/corostart.c"]}
]
```

### 6. Python Integration

Modify `src/asynkit/coroutine.py` to use C extension when available:

```python
try:
    from asynkit._cext import CoroStart as _CCoroStart
    _use_c_extension = True
except ImportError:
    _use_c_extension = False

class CoroStart:
    """Python fallback implementation"""
    # ... existing code ...

# Use C version if available
if _use_c_extension:
    CoroStart = _CCoroStart
```

## Expected Performance Gains

For a coroutine that suspends N times:
- **Current:** 2N Python generator frame operations (unwinding + rewinding)
- **With C extension:** Direct C function calls, no frame overhead
- **Estimated speedup:** 10-50x reduction in wrapper overhead (depends on coroutine complexity)

The gain is most significant for:
- Tight loops with frequent `await` calls
- Middleware/wrapper patterns that stack multiple `CoroStart` instances
- Any code where coroutine startup overhead is measurable

## Development Environment

**WSL is preferred because:**
- Simpler C toolchain (GCC/Clang vs MSVC)
- Python dev headers easily available (`python3-dev`)
- Better debugging tools (GDB, valgrind)
- CI runs on Ubuntu anyway

**Build commands:**
```bash
# In WSL
uv sync  # Will build C extension automatically
uv run pytest tests/  # Test everything
```

## Testing Strategy

1. **Correctness tests:** Ensure C version behaves identically to Python version
2. **Performance benchmarks:** Measure speedup on high-frequency coroutines
3. **Fallback testing:** Verify Python version still works when C extension unavailable
4. **Cross-platform:** Test on Linux (WSL), Windows (if possible), and in CI

## References

- CPython's `_PyCoroWrapper_Type`: `Objects/genobject.c:1267-1379`
- CPython's iterator protocol: `Include/cpython/abstract.h`
- Extending tutorial: https://docs.python.org/3/extending/newtypes_tutorial.html

## Current Status

- Branch created: `feature/c-extension-corostart`
- `.gitattributes` updated for C/H files with LF line endings
- Ready to begin implementation in WSL

## Next Steps

1. Create `src/asynkit/_cext/` directory
2. Implement `corostart.c` with basic structure
3. Update build configuration
4. Write tests comparing C and Python implementations
5. Benchmark performance gains
6. Document usage and fallback behavior
