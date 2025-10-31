/*
 * asynkit C Extension - CoroStart with CoroStartWrapper
 *
 * Phase 3: Create CoroStartWrapper that implements both iterator and coroutine
 * protocols following the PyCoroWrapper pattern discovered in CPython source
 *
 * Updated: 2025-10-29 - Updated to continued() and pending() API methods (renamed from
 * consumed/suspended)
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>

/* Debug logging macros */
#define DEBUG_TRACE 0
#if DEBUG_TRACE
    #define TRACE_LOG(fmt, ...) printf("[C-TRACE] " fmt "\n", ##__VA_ARGS__)
#else
    #define TRACE_LOG(fmt, ...)
#endif

// Silence function pointer cast warnings for PyMethodDef tables
#if defined(__GNUC__) && !defined(__clang__)
    #pragma GCC diagnostic push
    #pragma GCC diagnostic ignored "-Wcast-function-type"
#elif defined(__clang__)
    #pragma clang diagnostic push
    #pragma clang diagnostic ignored "-Wcast-function-type"
#elif defined(_MSC_VER)
    #pragma warning(push)
    #pragma warning(disable : 4152)
#endif

/* Forward declarations */
static PyTypeObject *CoroStartType = NULL;        /* Will be created from spec */
static PyTypeObject *CoroStartWrapperType = NULL; /* Will be created from spec */

/* Forward declaration of methods */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs);
static PyObject *corostart_done(PyObject *_self);
static PyObject *corostart_continued(PyObject *_self, PyObject *args);
static PyObject *corostart_pending(PyObject *_self, PyObject *args);
static PyObject *corostart_result(PyObject *_self);
static PyObject *corostart_exception(PyObject *_self);
static PyObject *corostart__throw(PyObject *_self, PyObject *exc);
static PyObject *corostart_close(PyObject *_self);

/* Helper function forward declarations */
static PyObject *invalid_state_error(void);

/* Module initialization function */
PyMODINIT_FUNC PyInit__cext(void);

/* CoroStartWrapper - implements both iterator and coroutine protocols */
typedef struct CoroStartWrapperObject {
    PyObject_HEAD;
    PyObject *corostart; /* Reference to our CoroStart object */
} CoroStartWrapperObject;

/* Forward declaration of wrapper methods */
static PyObject *corostart_wrapper_send(PyObject *_self, PyObject *arg);
static PyObject *corostart_wrapper_throw(PyObject *_self, PyObject *exc);
static PyObject *corostart_wrapper_close(PyObject *_self, PyObject *ignored);
static void corostart_wrapper_dealloc(PyObject *_self);
static int corostart_wrapper_traverse(PyObject *_self, visitproc visit, void *arg);
static int corostart_wrapper_clear(PyObject *_self);
static PyObject *corostart_wrapper_iter(PyObject *_self);
static PyObject *corostart_wrapper_iternext(PyObject *_self);
static PySendResult corostart_wrapper_am_send_slot(PyObject *_self,
                                                   PyObject *arg,
                                                   PyObject **result);

/* CoroStart object structure */
typedef struct CoroStartObject {
    PyObject_HEAD;
    PyObject *wrapped_coro;
    PyObject *context;
    PySendResult initial_result; /* Result from initial PyIter_Send call */
    PyObject *s_value;           // completed value (if not exception)
    PyObject *s_exc_type;        // exception type (if completed with exception)
    PyObject *s_exc_value;       // exception value
    PyObject *s_exc_traceback;   // exception traceback
} CoroStartObject;

/* Forward declaration of CoroStart object methods */
static void corostart_dealloc(CoroStartObject *self);
static int corostart_traverse(CoroStartObject *self, visitproc visit, void *arg);
static int corostart_clear(CoroStartObject *self);
static PyObject *corostart_await(CoroStartObject *self);

/* State checking macros for CoroStart objects */
#define IS_DONE(self) ((self)->initial_result != PYGEN_NEXT)
#define IS_CONTINUED(self) ((self)->s_value == NULL && (self)->s_exc_type == NULL)
#define IS_PENDING(self) (!IS_DONE(self) && !IS_CONTINUED(self))

/* State invariant checker for debugging and validation */
static inline void assert_corostart_invariant(CoroStartObject *self)
{
#ifdef NDEBUG
    /* Skip checks in release builds */
    (void) self;
#else
    /* Validate state model invariants:
     * 1. Exactly one of three states: done, pending, or continued
     * 2. done: s_exc_type != NULL (and s_value == NULL)
     * 3. pending: s_value != NULL (and s_exc_type == NULL)
     * 4. continued: all fields are NULL
     */
    int is_done = IS_DONE(self);
    int is_pending = IS_PENDING(self);
    int is_continued = IS_CONTINUED(self);

    /* Exactly one state should be true */
    int state_count = is_done + is_pending + is_continued;
    assert(state_count == 1 && "CoroStart must be in exactly one state");

    /* Additional consistency checks */
    if(is_done) {
        /* done() state - should not have s_value */
        assert(self->s_value == NULL && "done() state should not have s_value");
    }
    if(is_pending) {
        /* pending() state - should not have exception fields */
        assert(self->s_exc_type == NULL && "pending() state should not have exception");
        assert(self->s_exc_value == NULL &&
               "pending() state should not have exception value");
        assert(self->s_exc_traceback == NULL &&
               "pending() state should not have exception traceback");
    }
#endif
}

/* CoroStart _start method - simplified eager execution logic */
static int corostart_start(CoroStartObject *self)
{
    TRACE_LOG("corostart_start called - about to start coroutine execution");

    /* Enter context if provided */
    if(self->context != NULL) {
        TRACE_LOG("Using context enter/exit for coroutine start");
        if(PyContext_Enter(self->context) < 0) {
            return -1;
        }
    } else {
        TRACE_LOG("Direct coro.send(None) call");
    }

    /* Call coro.send(None) using PyIter_Send API */
    self->initial_result = PyIter_Send(self->wrapped_coro, Py_None, &self->s_value);

    TRACE_LOG("PyIter_Send returned: %d (NEXT=1, RETURN=0, ERROR=-1)",
              self->initial_result);

    switch(self->initial_result) {
        case PYGEN_NEXT:
            /* Coroutine yielded a value */
            TRACE_LOG("PYGEN_NEXT: coroutine yielded a value");
            break;
        case PYGEN_RETURN:
            /* Coroutine completed normally - create StopIteration */
            TRACE_LOG("PYGEN_RETURN: coroutine completed normally");
            break;
        case PYGEN_ERROR:
            /* Exception occurred - PyIter_Send already set the exception */
            TRACE_LOG("PYGEN_ERROR: exception occurred");
            PyErr_Fetch(&self->s_exc_type, &self->s_exc_value, &self->s_exc_traceback);
            break;
    }

    /* Exit context if we entered one */
    if(self->context != NULL) {
        if(PyContext_Exit(self->context) < 0) {
            Py_CLEAR(self->s_value);
            return -1;
        }
    }

    if(IS_PENDING(self)) {
        TRACE_LOG("Coroutine yielded a value - now pending");
    } else {
        TRACE_LOG("Coroutine completed or raised exception");
    }

    assert_corostart_invariant(self);
    return 0; /* Success (we handled the exception) */
}

/* CoroStartWrapper deallocation */
static void corostart_wrapper_dealloc(PyObject *_self)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->corostart);
    Py_TYPE(self)->tp_free((PyObject *) self);
}

/* CoroStartWrapper garbage collection traversal */
static int corostart_wrapper_traverse(PyObject *_self, visitproc visit, void *arg)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    Py_VISIT(self->corostart);
    return 0;
}

/* CoroStartWrapper garbage collection clear */
static int corostart_wrapper_clear(PyObject *_self)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    Py_CLEAR(self->corostart);
    return 0;
}

/* CoroStartWrapper __iter__ method - required for iterator protocol */
static PyObject *corostart_wrapper_iter(PyObject *_self)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    Py_INCREF(self);
    return (PyObject *) self;
}

/* CoroStartWrapper __next__ method - alias for send(None) */
static PyObject *corostart_wrapper_iternext(PyObject *_self)
{
    /* __next__ is equivalent to send(None) */
    return corostart_wrapper_send(_self, Py_None);
}

/* CoroStartWrapper send method - simplified to handle start state */
/* CoroStartWrapper send method - delegates to am_send slot for optimization */
static PyObject *corostart_wrapper_send(PyObject *_self, PyObject *arg)
{
    PyObject *result;
    PySendResult send_result = corostart_wrapper_am_send_slot(_self, arg, &result);

    if(send_result == PYGEN_ERROR) {
        return NULL;
    } else if(send_result == PYGEN_RETURN) {
        PyErr_SetObject(PyExc_StopIteration, result);
        Py_DECREF(result);
        return NULL;
    } else {
        /* PYGEN_NEXT - return the yielded value */
        return result;
    }
}

/* CoroStartWrapper throw method - required for coroutine protocol */
static PyObject *corostart_wrapper_throw(PyObject *_self, PyObject *exc)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    /* Enter context if provided */
    if(corostart->context != NULL) {
        TRACE_LOG("Using context enter/exit for throw");
        if(PyContext_Enter(corostart->context) < 0) {
            return NULL;
        }
    }

    /* Call throw() on the wrapped coroutine */
    PyObject *result = PyObject_CallMethod(corostart->wrapped_coro, "throw", "O", exc);

    /* Exit context if we entered one */
    if(corostart->context != NULL) {
        if(PyContext_Exit(corostart->context) < 0) {
            Py_XDECREF(result);
            return NULL;
        }
    }

    return result;
}

/* CoroStartWrapper close method - required for coroutine protocol */
static PyObject *corostart_wrapper_close(PyObject *_self, PyObject *Py_UNUSED(ignored))
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    /* Enter context if provided */
    if(corostart->context != NULL) {
        if(PyContext_Enter(corostart->context) < 0) {
            return NULL;
        }
    }

    /* Call close() on the wrapped coroutine */
    PyObject *result = PyObject_CallMethod(corostart->wrapped_coro, "close", NULL);

    /* Exit context if we entered one */
    if(corostart->context != NULL) {
        if(PyContext_Exit(corostart->context) < 0) {
            Py_XDECREF(result);
            return NULL;
        }
    }

    return result;
}

#if DEBUG_TRACE
/* CoroStartWrapper am_send implementation for PyIter_Send optimization (debug version)
 */
static PyObject *corostart_wrapper_am_send(PyObject *_self, PyObject *arg)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    TRACE_LOG("corostart_wrapper_am_send() called - optimized PyIter_Send path");

    /* Delegate to the regular send method */
    return corostart_wrapper_send(_self, arg);
}
#endif

/* CoroStartWrapper am_send implementation for PyIter_Send optimization */
static PySendResult corostart_wrapper_am_send_slot(PyObject *_self,
                                                   PyObject *arg,
                                                   PyObject **result)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    TRACE_LOG("corostart_wrapper_am_send_slot() called - PyIter_Send optimized path");

    /* Check if we have start results (first call) */
    if(!IS_CONTINUED(corostart)) {
        TRACE_LOG("First am_send call - processing eager execution result");
        /* This is the first send call - process the eager execution result */
        /* According to PEP 342, first send() must be None */
        if(arg != Py_None) {
            PyErr_SetString(PyExc_TypeError,
                            "can't send non-None value to a just-started coroutine");
            *result = NULL;
            return PYGEN_ERROR;
        }

        if(IS_DONE(corostart)) {
            TRACE_LOG(
                "Coroutine completed during start - we have a result or an exception");
            if(corostart->s_value != NULL) {
                // We have a result
                TRACE_LOG("Coroutine completed with result");
                *result = corostart->s_value;
                corostart->s_value =
                    NULL; /* Clear and transfer ownership - marks as continued */
                return PYGEN_RETURN;
            }

            // we have an exception, restore it and return error
            PyErr_Restore(corostart->s_exc_type,
                          corostart->s_exc_value,
                          corostart->s_exc_traceback);
            /* Clear the fields (PyErr_Restore steals references) - marks as continued
             */
            corostart->s_exc_type = NULL;
            corostart->s_exc_value = NULL;
            corostart->s_exc_traceback = NULL;
            *result = NULL;
            return PYGEN_ERROR;
        }

        // we are pending
        TRACE_LOG("Coroutine yielded during start - returning yielded value");
        /* Coroutine yielded a value - return it and clear state to mark as continued */
        *result = corostart->s_value;
        corostart->s_value =
            NULL; /* Clear and transfer ownership - marks as continued */
        return PYGEN_NEXT;
    }

    TRACE_LOG("Subsequent am_send call - delegating to wrapped coroutine");
    /* No start results - coroutine was already started, delegate to wrapped coroutine
     */

    /* Enter context if provided */
    if(corostart->context != NULL) {
        TRACE_LOG("Using context enter/exit for continued am_send");
        if(PyContext_Enter(corostart->context) < 0) {
            *result = NULL;
            return PYGEN_ERROR;
        }
    } else {
        TRACE_LOG("Direct coro.send for continued am_send");
    }

    /* Call send() on the wrapped coroutine using PyIter_Send */
    PySendResult send_result = PyIter_Send(corostart->wrapped_coro, arg, result);

    /* Exit context if we entered one */
    if(corostart->context != NULL) {
        if(PyContext_Exit(corostart->context) < 0) {
            if(send_result != PYGEN_ERROR) {
                Py_CLEAR(*result);
            }
            return PYGEN_ERROR;
        }
    }

    /* Return PyIter_Send result directly - no conversion needed */
    return send_result;
}

/* CoroStartWrapper methods */

static PyMethodDef corostart_wrapper_methods[] = {
    {"send",
     (PyCFunction) corostart_wrapper_send,
     METH_O,
     "Send a value into the wrapper."},
    {"throw",
     (PyCFunction) corostart_wrapper_throw,
     METH_O,
     "Throw an exception into the wrapper."},
    {"close", (PyCFunction) corostart_wrapper_close, METH_NOARGS, "Close the wrapper."},
    {NULL, NULL, 0, NULL}};


/* CoroStartWrapper type definition using PyType_Spec for am_send optimization */
static PyType_Slot corostart_wrapper_slots[] = {
    {Py_tp_dealloc, corostart_wrapper_dealloc},
    {Py_tp_traverse, corostart_wrapper_traverse},
    {Py_tp_clear, corostart_wrapper_clear},
    {Py_tp_iter, corostart_wrapper_iter},
    {Py_tp_iternext, corostart_wrapper_iternext},
    {Py_tp_methods, corostart_wrapper_methods},
    {Py_tp_new, PyType_GenericNew},

    /* Async protocol slot for PyIter_Send optimization */
    {Py_am_send, corostart_wrapper_am_send_slot}, /* Proper am_send implementation */

    {0, NULL},
};

static PyType_Spec corostart_wrapper_spec = {
    .name = "asynkit._cext.CoroStartWrapper",
    .basicsize = sizeof(CoroStartWrapperObject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = corostart_wrapper_slots,
};

/* CoroStart deallocation */
static void corostart_dealloc(CoroStartObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->wrapped_coro);
    Py_XDECREF(self->context);
    Py_XDECREF(self->s_value);
    Py_XDECREF(self->s_exc_type);
    Py_XDECREF(self->s_exc_value);
    Py_XDECREF(self->s_exc_traceback);
    Py_TYPE(self)->tp_free((PyObject *) self);
}

/* CoroStart garbage collection traversal */
static int corostart_traverse(CoroStartObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->wrapped_coro);
    Py_VISIT(self->context);
    Py_VISIT(self->s_value);
    Py_VISIT(self->s_exc_type);
    Py_VISIT(self->s_exc_value);
    Py_VISIT(self->s_exc_traceback);
    return 0;
}

/* CoroStart garbage collection clear */
static int corostart_clear(CoroStartObject *self)
{
    Py_CLEAR(self->wrapped_coro);
    Py_CLEAR(self->context);
    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_value);
    Py_CLEAR(self->s_exc_traceback);
    return 0;
}

/* __await__ method - return our CoroStartWrapper */
static PyObject *corostart_await(CoroStartObject *self)
{
    /* Create our CoroStartWrapper that holds a reference to this CoroStart */
    CoroStartWrapperObject *wrapper = (CoroStartWrapperObject *) CoroStartWrapperType
                                          ->tp_alloc(CoroStartWrapperType, 0);
    if(wrapper == NULL) {
        return NULL;
    }

    wrapper->corostart = (PyObject *) self;
    Py_INCREF(wrapper->corostart);

    return (PyObject *) wrapper;
}

/* CoroStart method definitions - defined before slots to avoid MSVC forward declaration
 * issues */
static PyMethodDef corostart_methods[] =
    {{"done",
      (PyCFunction) corostart_done,
      METH_NOARGS,
      "Return True if coroutine finished synchronously during initial start"},
     {"continued",
      (PyCFunction) corostart_continued,
      METH_NOARGS,
      "Return True if coroutine has been continued (awaited) after initial start"},
     {"pending",
      (PyCFunction) corostart_pending,
      METH_NOARGS,
      "Return True if coroutine is pending, waiting for async operation"},
     {"result",
      (PyCFunction) corostart_result,
      METH_NOARGS,
      "Return result or raise exception"},
     {"exception",
      (PyCFunction) corostart_exception,
      METH_NOARGS,
      "Return exception or None"},
     {"_throw",
      (PyCFunction) corostart__throw,
      METH_O,
      "Core throw method - throw an exception into the coroutine"},
     {"close", (PyCFunction) corostart_close, METH_NOARGS, "Close the coroutine"},
     {NULL, NULL, 0, NULL}};

/* CoroStart slots for PyType_Spec */
static PyType_Slot corostart_slots[] = {
    {Py_tp_new, corostart_new},
    {Py_tp_dealloc, corostart_dealloc},
    {Py_tp_traverse, corostart_traverse},
    {Py_tp_clear, corostart_clear},
    {Py_tp_methods, corostart_methods},
    {Py_am_await,
     corostart_await}, /* Direct implementation - no need for debug wrapper */

    {0, NULL},
};

static PyType_Spec corostart_spec = {
    .name = "asynkit._cext.CoroStart",
    .basicsize = sizeof(CoroStartObject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_BASETYPE,
    .slots = corostart_slots,
};

/* CoroStart methods */
static PyObject *corostart_done(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    assert_corostart_invariant(self);
    // Return True if we have completed (indicated by having an exception)
    // Either StopIteration (normal completion) or any other exception (error)
    if(IS_DONE(self)) {
        TRACE_LOG("corostart_done() -> True (coroutine completed)");
        Py_RETURN_TRUE;
    }
    TRACE_LOG("corostart_done() -> False (coroutine still pending)");
    Py_RETURN_FALSE;
}

static PyObject *corostart_continued(PyObject *_self, PyObject *Py_UNUSED(args))
{
    CoroStartObject *self = (CoroStartObject *) _self;
    assert_corostart_invariant(self);
    // Return True if the coroutine has been continued (awaited) after initial start
    // In C implementation, continued means all start result fields are NULL
    if(IS_CONTINUED(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_pending(PyObject *_self, PyObject *Py_UNUSED(args))
{
    CoroStartObject *self = (CoroStartObject *) _self;
    assert_corostart_invariant(self);
    // Return True if the coroutine is pending, waiting for async operation
    // This means we have a yielded value (s_value != NULL)
    if(IS_PENDING(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *invalid_state_error(void)
{
    // Use asyncio.InvalidStateError to match Python implementation
    PyObject *asyncio_module = PyImport_ImportModule("asyncio");
    if(asyncio_module) {
        PyObject *invalid_state_error = PyObject_GetAttrString(asyncio_module,
                                                               "InvalidStateError");
        Py_DECREF(asyncio_module);
        if(invalid_state_error) {
            PyErr_SetString(invalid_state_error, "CoroStart: coroutine not done()");
            Py_DECREF(invalid_state_error);
            return NULL;
        }
    }
    PyErr_SetString(PyExc_RuntimeError, "CoroStart: coroutine not done()");
    return NULL;
}

static PyObject *corostart_result(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    TRACE_LOG("corostart_result() called");

    // Check if we're done (must have an exception)
    if(!IS_DONE(self)) {
        TRACE_LOG("corostart_result() -> InvalidStateError (not done)");
        return invalid_state_error();
    }

    // Check if it's StopIteration (normal completion)
    if(self->initial_result == PYGEN_RETURN) {
        TRACE_LOG("corostart_result() -> StopIteration value (normal completion)");
        return Py_NewRef(self->s_value);
    } else {
        TRACE_LOG("corostart_result() -> Re-raising exception (error completion)");
        // Re-raise other exceptions using Restore (steals references)
        // Use Py_XNewRef to handle potential NULL values safely
        PyErr_Restore(Py_XNewRef(self->s_exc_type),
                      Py_XNewRef(self->s_exc_value),
                      Py_XNewRef(self->s_exc_traceback));
        return NULL;
    }
}

static PyObject *corostart_exception(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    // Check if we're done (must have an exception)
    if(!IS_DONE(self)) {
        return invalid_state_error();
    }
    if(self->initial_result != PYGEN_ERROR) {
        // No exception occurred
        Py_RETURN_NONE;
    }


    // Return the exception (not re-raise it like result() does)
    if(self->s_exc_value && PyObject_IsInstance(self->s_exc_value, self->s_exc_type)) {
        // s_exc_value is an actual exception instance
        Py_INCREF(self->s_exc_value);
        return self->s_exc_value;
    } else {
        // s_exc_value is the raw value, need to construct exception
        PyObject *exc_instance = PyObject_CallFunction(self->s_exc_type,
                                                       "O",
                                                       self->s_exc_value
                                                           ? self->s_exc_value
                                                           : Py_None);
        return exc_instance;
    }
}

static PyObject *corostart__throw(PyObject *_self, PyObject *exc)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    assert_corostart_invariant(self);

    // Convert exception type to instance if needed
    PyObject *value;
    if(PyExceptionInstance_Check(exc)) {
        // exc is already an exception instance
        value = exc;
        Py_INCREF(value);
    } else if(PyExceptionClass_Check(exc)) {
        // exc is an exception type, instantiate it
        value = PyObject_CallFunction(exc, NULL);
        if(value == NULL) {
            return NULL;
        }
    } else {
        PyErr_SetString(PyExc_TypeError, "_throw() arg must be an exception");
        return NULL;
    }

    PyObject *result;

    // Call throw() with context support
    if(self->context != NULL) {
        /* Enter context */
        if(PyContext_Enter(self->context) < 0) {
            Py_DECREF(value);
            return NULL;
        }

        result = PyObject_CallMethod(self->wrapped_coro, "throw", "O", value);

        /* Exit context (even if call failed) */
        if(PyContext_Exit(self->context) < 0) {
            Py_DECREF(value);
            Py_XDECREF(result);
            return NULL;
        }
    } else {
        result = PyObject_CallMethod(self->wrapped_coro, "throw", "O", value);
    }

    if(result != NULL) {
        // Coroutine yielded a value - update state to pending with the new value
        Py_CLEAR(self->s_value);
        Py_CLEAR(self->s_exc_type);
        Py_CLEAR(self->s_exc_value);
        Py_CLEAR(self->s_exc_traceback);
        self->s_value = result;  // Store new yielded value (becomes pending state)
        self->initial_result =
            PYGEN_NEXT;  // Update initial_result for new state macros

        Py_DECREF(value);
        Py_RETURN_NONE;
    }

    // Check if we got StopIteration (normal completion)
    if(PyErr_ExceptionMatches(PyExc_StopIteration)) {
        PyObject *exc_type, *exc_value, *exc_traceback;
        PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);

        // Coroutine finished synchronously - update state to done
        Py_CLEAR(self->s_value);
        Py_CLEAR(self->s_exc_type);
        Py_CLEAR(self->s_exc_value);
        Py_CLEAR(self->s_exc_traceback);

        // For PYGEN_RETURN, store the return value in s_value (like corostart_start
        // does) Extract the value from StopIteration - it might be an instance or raw
        // value
        if(exc_value && PyObject_IsInstance(exc_value, exc_type)) {
            // exc_value is an actual StopIteration instance - extract .value
            PyObject *return_value = PyObject_GetAttrString(exc_value, "value");
            if(return_value == NULL) {
                PyErr_Clear();
                return_value = Py_NewRef(Py_None);
            }
            self->s_value = return_value;
            Py_DECREF(exc_value);  // Clean up the StopIteration instance
        } else {
            // exc_value is the raw value (Python optimization)
            if(exc_value) {
                self->s_value = exc_value;  // Transfer ownership from PyErr_Fetch
            } else {
                self->s_value = Py_NewRef(Py_None);
            }
        }
        self->initial_result = PYGEN_RETURN;  // Update for new state macros

        // Clean up the exception objects we don't need
        Py_DECREF(exc_type);
        Py_XDECREF(exc_traceback);

        Py_DECREF(value);
        Py_RETURN_NONE;
    }

    // Any other exception - update state to done with the exception
    PyObject *exc_type, *exc_value, *exc_traceback;
    PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);

    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_value);
    Py_CLEAR(self->s_exc_traceback);

    // Set done state with the exception
    self->s_exc_type = exc_type;
    self->s_exc_value = exc_value;
    self->s_exc_traceback = exc_traceback;
    self->initial_result = PYGEN_ERROR;  // Update for new state macros

    Py_DECREF(value);
    Py_RETURN_NONE;
}


static PyObject *corostart_close(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    assert_corostart_invariant(self);

    PyObject *result;

    // Always close the underlying coroutine
    if(self->context != NULL) {
        /* Enter context */
        if(PyContext_Enter(self->context) < 0) {
            return NULL;
        }

        // Direct call to coro.close()
        result = PyObject_CallMethod(self->wrapped_coro, "close", NULL);

        /* Exit context (even if call failed) */
        if(PyContext_Exit(self->context) < 0) {
            Py_XDECREF(result);
            return NULL;
        }
    } else {
        // Direct call to coro.close()
        result = PyObject_CallMethod(self->wrapped_coro, "close", NULL);
    }

    // Transition to continued() state so that subsequent await attempts
    // trigger the "cannot reuse already awaited coroutine" error in __await__
    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_value);
    Py_CLEAR(self->s_exc_traceback);

    assert_corostart_invariant(self);
    return result;
}


/* CoroStart type constructor (will be used by PyType_FromSpec) */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    PyObject *coro;
    PyObject *context = NULL; /* Optional context parameter */

    static char *kwlist[] = {"coro", "context", NULL};

    TRACE_LOG("CoroStart.__new__ called");

    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "O|O", kwlist, &coro, &context)) {
        return NULL;
    }

    /* Create CoroStart object */
    CoroStartObject *cs = (CoroStartObject *) type->tp_alloc(type, 0);
    if(cs == NULL) {
        return NULL;
    }

    TRACE_LOG("CoroStart object allocated, about to start coroutine");

    /* Store the coroutine and context */
    cs->wrapped_coro = Py_NewRef(coro);

    /* Convert None to NULL for context - this makes context checks work properly */
    if(context == Py_None) {
        cs->context = NULL;
    } else {
        cs->context = context;
        Py_XINCREF(cs->context);
    }

    /* Initialize start result fields */
    cs->s_value = NULL;
    cs->s_exc_type = NULL;
    cs->s_exc_value = NULL;
    cs->s_exc_traceback = NULL;

    /* Perform eager execution */
    if(corostart_start(cs) < 0) {
        /* _start failed */
        Py_DECREF(cs);
        return NULL;
    }

    assert_corostart_invariant(cs);
    return (PyObject *) cs;
}

/* Module methods */
static PyObject *cext_get_build_info(PyObject *_self)
{
    (void) _self;
    /* Return build configuration information */
    PyObject *info = PyDict_New();
    if(info == NULL) {
        return NULL;
    }

#ifdef DEBUG
    PyDict_SetItemString(info, "build_type", PyUnicode_FromString("debug"));
    PyDict_SetItemString(info, "debug_enabled", Py_True);
#else
    PyDict_SetItemString(info, "build_type", PyUnicode_FromString("optimized"));
    PyDict_SetItemString(info, "debug_enabled", Py_False);
#endif

#ifdef NDEBUG
    PyDict_SetItemString(info, "ndebug_enabled", Py_True);
#else
    PyDict_SetItemString(info, "ndebug_enabled", Py_False);
#endif

    return info;
}

static PyMethodDef module_methods[] = {{"get_build_info",
                                        (PyCFunction) cext_get_build_info,
                                        METH_NOARGS,
                                        "Get build configuration information"},
                                       {NULL, NULL, 0, NULL}};

/* Module definition */
static struct PyModuleDef cext_module = {
    PyModuleDef_HEAD_INIT,
    "asynkit._cext",
    "Simple C extension for CoroStart",
    -1,
    module_methods,
    NULL, /* m_slots */
    NULL, /* m_traverse */
    NULL, /* m_clear */
    NULL  /* m_free */
};

/* Module initialization */
PyMODINIT_FUNC PyInit__cext(void)
{
    PyObject *module = PyModule_Create(&cext_module);
    if(module == NULL) {
        return NULL;
    }

    /* Add a simple test attribute first */
    if(PyModule_AddStringConstant(module, "__test__", "C extension loaded") < 0) {
        Py_DECREF(module);
        return NULL;
    }

    /* Create CoroStartWrapper type from spec for am_send optimization */
    CoroStartWrapperType = (PyTypeObject *) PyType_FromSpec(&corostart_wrapper_spec);
    if(CoroStartWrapperType == NULL) {
        Py_DECREF(module);
        return NULL;
    }

    /* Create CoroStart type from spec for am_await optimization */
    CoroStartType = (PyTypeObject *) PyType_FromSpec(&corostart_spec);
    if(CoroStartType == NULL) {
        Py_DECREF(module);
        return NULL;
    }

    /* Add types to module (for debugging/introspection) */
    Py_INCREF(CoroStartWrapperType);
    if(PyModule_AddObject(module,
                          "CoroStartWrapperType",
                          (PyObject *) CoroStartWrapperType) < 0) {
        Py_DECREF(CoroStartWrapperType);
        Py_DECREF(module);
        return NULL;
    }

    /* Add CoroStartBase type to module */
    Py_INCREF(CoroStartType);
    if(PyModule_AddObject(module, "CoroStartBase", (PyObject *) CoroStartType) < 0) {
        Py_DECREF(CoroStartType);
        Py_DECREF(module);
        return NULL;
    }

    return module;
}

// Restore warnings
#if defined(__GNUC__) && !defined(__clang__)
    #pragma GCC diagnostic pop
#elif defined(__clang__)
    #pragma clang diagnostic pop
#elif defined(_MSC_VER)
    #pragma warning(pop)
#endif