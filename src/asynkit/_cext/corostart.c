/*
 * asynkit C Extension - CoroStartBase  with CoroStartWrapper
 *
 * This module implements a C version of CoroStartBase from asynkit.
 * The purpose of this is to optimize the execution of the coroutine protocol.
 * In the Python code, this is done with a complicated generator function which
 * implements the protocol in python to act as an intermediate between the event
 * loop and the user coroutine.  This function is necessarily entered twice for
 * each yield point of the coroutine.
 * In C it is possible to do this much more efficiently by directly implementing
 * the PyIter_Send() protocol.
 * This virtually eliminates the runtime overhead of driving a coroutine through
 * the CoroStart mechanism.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>

/* Debug logging macros */
#define DEBUG_TRACE 0
#if DEBUG_TRACE
    #define TRACE_LOG(fmt, ...)                                                        \
        do {                                                                           \
            printf("[C-TRACE] " fmt "\n", ##__VA_ARGS__);                              \
            fflush(stdout);                                                            \
        } while(0)
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

// use new exception semantics in python 12 and higher
#define NEW_EXC (PY_VERSION_HEX >= 0x030C0000)

/* ========== MODULE STATE STRUCTURE ========== */
typedef struct {
    PyTypeObject *CoroStartType;
    PyTypeObject *CoroStartWrapperType;
} module_state;

/* Helper function to get module state */
static module_state *get_module_state(PyObject *module)
{
    return (module_state *) PyModule_GetState(module);
}

#if PY_VERSION_HEX < 0x030B0000
/* Global module reference for compatibility with Python < 3.11 */
static PyObject *_cext_module_ref = NULL;

/* Helper function to get module state from global reference */
static module_state *get_global_module_state(void)
{
    if(_cext_module_ref == NULL) {
        return NULL;
    }
    return get_module_state(_cext_module_ref);
}
#endif

/* ========== FORWARD DECLARATIONS ========== */

/* CoroStart method forward declarations */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs);
static PyObject *corostart_done(PyObject *_self);
static PyObject *corostart_continued(PyObject *_self, PyObject *args);
static PyObject *corostart_pending(PyObject *_self, PyObject *args);
static PyObject *corostart_result(PyObject *_self);
static PyObject *corostart_exception(PyObject *_self);
static PyObject *corostart__throw(PyObject *_self, PyObject *exc);
static PyObject *corostart_close(PyObject *_self);

/* CoroStartWrapper method forward declarations */
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

/* Helper function forward declarations */
static PyObject *invalid_state_error(void);
static PyObject *coro_get_iterator(PyObject *coro);
static PyObject *call_iter_next(PyObject *iter);
static int call_iter_next_result(PyObject *iter, PyObject **result);
static PyObject *extract_current_stopiteration_value(void);
static PyObject *check_stopiteration_value(void);
static int cext_exec(PyObject *module);
#if NEW_EXC
static PyObject *extract_stopiteration_value(PyObject *exc_value);
#else
static PyObject *extract_stopiteration_value(PyObject *exc_type, PyObject *exc_value);
#endif
static int cext_traverse(PyObject *module, visitproc visit, void *arg);
static int cext_clear(PyObject *module);

/* Forward declaration of module definition */
static struct PyModuleDef cext_module;

/* Module initialization function */
PyMODINIT_FUNC PyInit__cext(void);

/* ========== STRUCTURES AND MACROS ========== */

/* CoroStart object structure */
typedef struct CoroStartObject {
    PyObject_HEAD
        // Type-specific fields go here
        PyObject *await_iter;
    PyObject *context;
    int started;                  // Flag indicating if start() has been called
    PySendResult initial_result;  // Result from initial PyIter_Send call
    PyObject *s_value;            // completed value (if not exception)
    PyObject *s_exc_value;        // exception value
#if !NEW_EXC
    PyObject *s_exc_type;       // exception type (if completed with exception)
    PyObject *s_exc_traceback;  // exception traceback
#endif
} CoroStartObject;

/* CoroStartWrapper - implements both iterator and coroutine protocols */
typedef struct CoroStartWrapperObject {
    PyObject_HEAD
        // Type-specific fields go here
        PyObject *corostart;  // Reference to our CoroStart object
} CoroStartWrapperObject;

/* Forward declaration of CoroStart object methods */
static void corostart_dealloc(CoroStartObject *self);
static int corostart_traverse(CoroStartObject *self, visitproc visit, void *arg);
static int corostart_clear(CoroStartObject *self);
static PyObject *corostart_await(CoroStartObject *self);
static int corostart_start(CoroStartObject *self, PyObject *context);
static PyObject *corostart_start_method(PyObject *_self,
                                        PyObject *args,
                                        PyObject *kwargs);

/* State checking macros for CoroStart objects
 * UNSTARTED means started flag is 0 (start() not yet called)
 * DONE guarantees that s_value or _IS_EXC is set
 * CONTINUED means all fields are NULL (exception or value has
 *   been consumed by the PyIter_Send)
 * PENDING is derived.  it is not Done, and not yet consumed.
 * these are the four valid states, further validation is done
 * in the invariant checker.
 */
#if NEW_EXC
    #define _IS_EXC(self) ((self)->s_exc_value != NULL)
#else
    #define _IS_EXC(self) ((self)->s_exc_type != NULL)
#endif

#define _IS_UNSTARTED(self) (!(self)->started)
#define _IS_DONE(self) ((self)->started && (self)->initial_result != PYGEN_NEXT)
#define _IS_CONTINUED(self)                                                            \
    ((self)->started && (self)->s_value == NULL && !_IS_EXC(self))
#define _IS_PENDING(self) ((self)->started && !_IS_DONE(self) && !_IS_CONTINUED(self))

#define IS_UNSTARTED(self)                                                             \
    (assert_corostart_invariant_impl((self), __LINE__), _IS_UNSTARTED(self))
#define IS_DONE(self)                                                                  \
    (assert_corostart_invariant_impl((self), __LINE__), _IS_DONE(self))
#define IS_CONTINUED(self)                                                             \
    (assert_corostart_invariant_impl((self), __LINE__), _IS_CONTINUED(self))
#define IS_PENDING(self)                                                               \
    (assert_corostart_invariant_impl((self), __LINE__), _IS_PENDING(self))

/* Macro to call invariant checker with current line number */
#define ASSERT_COROSTART_INVARIANT(self)                                               \
    assert_corostart_invariant_impl((self), __LINE__)

/* State invariant checker for debugging and validation */
static inline void assert_corostart_invariant_impl(CoroStartObject *self,
                                                   int line_number)
{
#ifdef NDEBUG
    // Skip checks in release builds
    (void) self;
    (void) line_number;
#else
    // Validate state model invariants:
    // 1. Exactly one of four states: unstarted, done, pending, or continued
    // 2. unstarted: started == 0
    // 3. done: _IS_EXC() (and s_value == NULL) or s_value set
    // 4. pending: s_value != NULL (and !_IS_EXC())
    // 5. continued: all fields are NULL
    int is_unstarted = _IS_UNSTARTED(self);
    int is_done = _IS_DONE(self);
    int is_pending = _IS_PENDING(self);
    int is_continued = _IS_CONTINUED(self);

    // Exactly one state should be true
    int state_count = is_unstarted + is_done + is_pending + is_continued;
    if(state_count != 1) {
        fprintf(stderr, __FILE__ ":%d: ", line_number);
    }
    assert(state_count == 1 && "CoroStart must be in exactly one state");

    // Additional consistency checks
    if(is_unstarted) {
        // unstarted state - should have no result fields set
        if(!(self->s_value == NULL && !(_IS_EXC(self)))) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->s_value == NULL && !(_IS_EXC(self)));
    } else if(is_done) {
        // done() state can have either s_value (PYGEN_RETURN) or exception
        // (PYGEN_ERROR)
        if(!(self->initial_result == PYGEN_RETURN ||
             self->initial_result == PYGEN_ERROR)) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->initial_result == PYGEN_RETURN ||
               self->initial_result == PYGEN_ERROR);
        // either s_value is non-NULL or _IS_EXC() (exclusive or)
        if(!((self->s_value != NULL) ^ _IS_EXC(self))) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert((self->s_value != NULL) ^ _IS_EXC(self));
    } else if(is_pending) {
        // pending() state - should only have s_value set
        if(!(self->initial_result == PYGEN_NEXT)) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->initial_result == PYGEN_NEXT);
        if(!(self->s_value != NULL && !(_IS_EXC(self)))) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->s_value != NULL && !(_IS_EXC(self)));
    } else {
        // continued() state - all fields should be NULL
        if(!(self->initial_result == PYGEN_NEXT)) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->initial_result == PYGEN_NEXT);
        if(!(self->s_value == NULL && !_IS_EXC(self))) {
            fprintf(stderr, __FILE__ ":%d: ", line_number);
        }
        assert(self->s_value == NULL && !_IS_EXC(self));
    }
#endif
}

/* ========== HELPER/UTILITY FUNCTIONS ========== */

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

/* Get the await iterator from a coroutine object */
static PyObject *coro_get_iterator(PyObject *coro)
{
    PyObject *await_iterator = NULL;
    // Use the most efficient approach
    PyTypeObject *type = Py_TYPE(coro);
    if(type->tp_as_async != NULL && type->tp_as_async->am_await != NULL) {
        await_iterator = type->tp_as_async->am_await(coro);
    } else {
        await_iterator = PyObject_CallMethod(coro, "__await__", NULL);
    }

    if(await_iterator == NULL) {
        TRACE_LOG("Failed to get await iterator");
    }
    return await_iterator;
}

// Call the __next__ method of an iterator using direct slot access if possible
// for better performance.
// Returns NULL with StopIteration set when iterator is exhausted (sets it if needed).
static PyObject *call_iter_next(PyObject *iter)
{
    PyTypeObject *type = Py_TYPE(iter);

    // Fast path: direct slot call
    if(type->tp_iternext != NULL) {
        return type->tp_iternext(iter);
    }

    // Slow path: method lookup
    PyObject *next_method = PyObject_GetAttrString(iter, "__next__");
    if(next_method == NULL) {
        return NULL;
    }

    PyObject *result = PyObject_CallNoArgs(next_method);
    Py_DECREF(next_method);
    return result;
}

// A method with the same signature as PyIter_Send() but uses
// the tp_iternext slot directly for better performance.
static int call_iter_next_result(PyObject *iter, PyObject **result)
{
    *result = call_iter_next(iter);
    if(*result) {
        return PYGEN_NEXT;  // Got a value
    }
    if(!PyErr_Occurred()) {
        // Optimization: coroutine tp_iternext may return NULL without setting
        // StopIteration when the return value is None (common case optimization)
        *result = Py_NewRef(Py_None);
        return PYGEN_RETURN;
    }
    *result = check_stopiteration_value();
    if(*result) {
        return PYGEN_RETURN;  // Got StopIteration value
    }
    return PYGEN_ERROR;  // Error occurred
}

#if NEW_EXC

/* check the current exception for a StopIteration.  Return the value if found
 * and clears the exception state, otherwise returns NULL with exception set.
 */
static PyObject *check_stopiteration_value(void)
{
    PyObject *exc_value;
    assert(PyErr_Occurred() != NULL);

    if(!PyErr_ExceptionMatches(PyExc_StopIteration)) {
        // This is some other exception
        return NULL;
    }

    // Fetch the exception
    exc_value = PyErr_GetRaisedException();
    PyObject *result = extract_stopiteration_value(exc_value);
    Py_DECREF(exc_value);
    return result;
}


/* extract the value of a stopiteration.  Assumes that we have
 * a StopIteration error state.  clears the error state on
 * success.  Returns NULL with exception set on error.
 */
static PyObject *extract_current_stopiteration_value(void)
{
    PyObject *exc_value = PyErr_GetRaisedException();
    assert(PyErr_GivenExceptionMatches(exc_value, PyExc_StopIteration));

    PyObject *result = extract_stopiteration_value(exc_value);
    Py_DECREF(exc_value);
    return result;
}

static PyObject *extract_stopiteration_value(PyObject *exc_value)
{
    // in 3.12+, exc_type is not needed, exc_value is always an instance
    assert(exc_value != NULL);
    assert(PyErr_GivenExceptionMatches(exc_value, PyExc_StopIteration));
    return Py_NewRef(((PyStopIterationObject *) exc_value)->value);
}

#else

/* check the current exception for a StopIteration.  Return the value if found
 * and clears the exception state, otherwise returns NULL with exception set.
 */
static PyObject *check_stopiteration_value(void)
{
    PyObject *exc_type, *exc_value, *exc_traceback;
    assert(PyErr_Occurred() != NULL);

    if(!PyErr_ExceptionMatches(PyExc_StopIteration)) {
        // This is some other exception
        return NULL;
    }

    // Fetch the exception
    PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);
    PyObject *result = extract_stopiteration_value(exc_type, exc_value);
    Py_DECREF(exc_type);
    Py_XDECREF(exc_value);
    Py_XDECREF(exc_traceback);
    return result;
}


/* extract the value of a stopiteration.  Assumes that we have
 * a StopIteration error state.  clears the error state on
 * success.  Returns NULL with exception set on error.
 */
static PyObject *extract_current_stopiteration_value(void)
{
    PyObject *exc_type, *exc_value, *exc_traceback;

    // get the current exception, not clearing it yet
    PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);
    assert(PyErr_GivenExceptionMatches(exc_type, PyExc_StopIteration));

    PyObject *result = extract_stopiteration_value(exc_type, exc_value);
    Py_DECREF(exc_type);
    Py_XDECREF(exc_value);
    Py_XDECREF(exc_traceback);
    return result;
}


static PyObject *extract_stopiteration_value(PyObject *exc_type, PyObject *exc_value)
{
    assert(exc_type != NULL);
    assert(PyErr_GivenExceptionMatches(exc_type, PyExc_StopIteration));

    if(exc_value != NULL) {
        int is_instance = PyObject_IsInstance(exc_value, exc_type);
        if(is_instance < 0) {
            // PyObject_IsInstance failed - return NULL with exception set
            return NULL;
        }
        if(is_instance == 1) {
            // exc_value is an actual StopIteration instance - extract .value
            return Py_NewRef(((PyStopIterationObject *) exc_value)->value);
        }
    }

    // exc_value is the raw value (internal C python optimization)
    // or NULL if StopIteration was raised with no value
    if(exc_value == NULL) {
        // No return value - return None
        Py_RETURN_NONE;
    }
    return Py_NewRef(exc_value);
}
#endif

/* ========== COROSTART TYPE IMPLEMENTATION ========== */

/* CoroStart type constructor (will be used by PyType_FromSpec) */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    PyObject *coro;
    PyObject *context = NULL;  // Optional context parameter
    int autostart = 1;         // Default to True

    static char *kwlist[] = {"coro", "context", "autostart", NULL};

    TRACE_LOG("CoroStart.__new__ called");

    if(!PyArg_ParseTupleAndKeywords(
           args, kwargs, "O|Op", kwlist, &coro, &context, &autostart)) {
        return NULL;
    }

    PyObject *await_iterator = coro_get_iterator(coro);
    if(await_iterator == NULL) {
        // Failed to get await iterator
        return NULL;
    }

    // Create CoroStart object
    CoroStartObject *cs = (CoroStartObject *) type->tp_alloc(type, 0);
    if(cs == NULL) {
        Py_DECREF(await_iterator);
        return NULL;
    }

    TRACE_LOG("CoroStart object allocated, about to start coroutine");

    // Store the coroutine and context
    cs->await_iter = await_iterator;

    // Convert None to NULL for context - this makes context checks work properly
    if(context == Py_None) {
        cs->context = NULL;
    } else {
        cs->context = context;
        Py_XINCREF(cs->context);
    }

    // STATE INITIALIZATION: All state fields start as NULL
    cs->started = 0;  // Not started yet
    cs->s_value = NULL;
    cs->s_exc_value = NULL;
#if !NEW_EXC
    cs->s_exc_type = NULL;
    cs->s_exc_traceback = NULL;
#endif

    // Perform eager execution if autostart is True
    if(autostart) {
        if(corostart_start(cs, cs->context) < 0) {
            // _start failed
            Py_DECREF(cs);
            return NULL;
        }
    }

    ASSERT_COROSTART_INVARIANT(cs);
    return (PyObject *) cs;
}

/* CoroStart _start method - simplified eager execution logic */
static int corostart_start(CoroStartObject *self, PyObject *context)
{
    TRACE_LOG("corostart_start called");

    // Mark as started
    self->started = 1;

    // Enter context if provided
    if(context != NULL) {
        if(PyContext_Enter(context) < 0) {
            return -1;
        }
    }

    // Call next(await_iter)
    // STATE MODIFICATION: Sets initial_result and may set s_value or exception fields
    self->initial_result = call_iter_next_result(self->await_iter, &self->s_value);

    switch(self->initial_result) {
        case PYGEN_NEXT:
            // Coroutine yielded a value
            // STATE: PENDING (s_value set by PyIter_Send)
            assert(IS_PENDING(self));
            break;
        case PYGEN_RETURN:
            // Coroutine completed normally - create StopIteration
            // STATE: DONE (s_value set by PyIter_Send)
            assert(IS_DONE(self));
            break;
        case PYGEN_ERROR:
            // Exception occurred - PyIter_Send already set the exception
            // STATE MODIFICATION: Transition to DONE with exception
#if NEW_EXC
            self->s_exc_value = PyErr_GetRaisedException();
#else
            PyErr_Fetch(&self->s_exc_type, &self->s_exc_value, &self->s_exc_traceback);
#endif
            assert(IS_DONE(self));
            break;
    }

    // Exit context if we entered one
    if(context != NULL) {
        if(PyContext_Exit(context) < 0) {
            Py_CLEAR(self->s_value);
            return -1;
        }
    }

    ASSERT_COROSTART_INVARIANT(self);
    return 0;  // Success (we handled the exception)
}

/* CoroStart deallocation */
static void corostart_dealloc(CoroStartObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->await_iter);
    Py_XDECREF(self->context);
    Py_XDECREF(self->s_value);
    Py_XDECREF(self->s_exc_value);
#if !NEW_EXC
    Py_XDECREF(self->s_exc_type);
    Py_XDECREF(self->s_exc_traceback);
#endif
    Py_TYPE(self)->tp_free((PyObject *) self);
}

/* CoroStart garbage collection traversal */
static int corostart_traverse(CoroStartObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->await_iter);
    Py_VISIT(self->context);
    Py_VISIT(self->s_value);
    Py_VISIT(self->s_exc_value);
#if !NEW_EXC
    Py_VISIT(self->s_exc_type);
    Py_VISIT(self->s_exc_traceback);
#endif
    return 0;
}

/* CoroStart garbage collection clear */
static int corostart_clear(CoroStartObject *self)
{
    Py_CLEAR(self->await_iter);
    Py_CLEAR(self->context);
    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_value);
#if !NEW_EXC
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_traceback);
#endif
    return 0;
}

/* __await__ method - return our CoroStartWrapper */
static PyObject *corostart_await(CoroStartObject *self)
{
    // Get module state using compatibility approach
#if PY_VERSION_HEX >= 0x030B0000
    // Python 3.11+ has PyType_GetModuleByDef
    PyObject *module = PyType_GetModuleByDef(Py_TYPE(self), &cext_module);
    if(module == NULL) {
        return NULL;
    }
    module_state *state = get_module_state(module);
    if(state == NULL) {
        return NULL;
    }
#else
    // Python < 3.11: use global module reference
    module_state *state = get_global_module_state();
    if(state == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "Module state not available");
        return NULL;
    }
#endif

    // Create our CoroStartWrapper that holds a reference to this CoroStart
    CoroStartWrapperObject *wrapper =
        (CoroStartWrapperObject *)
            state->CoroStartWrapperType->tp_alloc(state->CoroStartWrapperType, 0);
    if(wrapper == NULL) {
        return NULL;
    }

    wrapper->corostart = (PyObject *) self;
    Py_INCREF(wrapper->corostart);

    return (PyObject *) wrapper;
}

/* CoroStart public methods */

/* Public start() method */
static PyObject *corostart_start_method(PyObject *_self,
                                        PyObject *args,
                                        PyObject *kwargs)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    PyObject *context = NULL;

    static char *kwlist[] = {"context", NULL};

    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "|O", kwlist, &context)) {
        return NULL;
    }

    // Convert None to NULL for context - this makes context checks work properly
    if(context == Py_None) {
        context = NULL;
    }

    // Check if already started
    if(self->started) {
        PyErr_SetString(PyExc_RuntimeError,
                        "CoroStart.start() can only be called once");
        return NULL;
    }

    // Call internal start with provided context (or NULL)
    if(corostart_start(self, context) < 0) {
        return NULL;
    }

    // Return True if done, False if pending
    if(IS_DONE(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_done(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    // Return True if we have completed (indicated by having an exception)
    // Either StopIteration (normal completion) or any other exception (error)
    if(IS_DONE(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_continued(PyObject *_self, PyObject *Py_UNUSED(args))
{
    CoroStartObject *self = (CoroStartObject *) _self;
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
    // Return True if the coroutine is pending, waiting for async operation
    // This means we have a yielded value (s_value != NULL)
    if(IS_PENDING(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_result(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;

    // Check if we're done (must have an exception)
    if(!IS_DONE(self)) {
        return invalid_state_error();
    }

    // Check if it's StopIteration (normal completion)
    if(self->initial_result == PYGEN_RETURN) {
        return Py_NewRef(self->s_value);
    } else {
        // Re-raise other exceptions using Restore (steals references)
        // Use Py_XNewRef to handle potential NULL values safely
#if NEW_EXC
        PyErr_SetRaisedException(Py_NewRef(self->s_exc_value));
#else
        PyErr_Restore(Py_XNewRef(self->s_exc_type),
                      Py_XNewRef(self->s_exc_value),
                      Py_XNewRef(self->s_exc_traceback));
#endif
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
#if NEW_EXC
    return Py_NewRef(self->s_exc_value);
#else
    if(self->s_exc_value) {
        int res = PyObject_IsInstance(self->s_exc_value, self->s_exc_type);
        if(res < 0) {
            return NULL;  // error during IsInstance check
        }
        if(res == 1) {
            // s_exc_value is an actual exception instance
            return Py_NewRef(self->s_exc_value);
        }
    }
    // s_exc_value is the raw value, need to construct exception
    // if it is null, it is omitted by the following call
    // any failure is propagated to the caller.
    return PyObject_CallFunctionObjArgs(self->s_exc_type, self->s_exc_value, NULL);
#endif
}

// Throw an exception into the coroutine
// set the state accordingly. any error except validation will set the state to done
// with the exception.
static PyObject *corostart__throw(PyObject *_self, PyObject *exc)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    ASSERT_COROSTART_INVARIANT(self);

    // Convert exception type to instance if needed
    PyObject *value;
    if(PyExceptionInstance_Check(exc)) {
        // exc is already an exception instance
        value = Py_NewRef(exc);
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

    // Call throw() with context support
    PyObject *result;
    if(self->context != NULL) {
        // Enter context
        if(PyContext_Enter(self->context) < 0) {
            Py_DECREF(value);
            return NULL;
        }

        result = PyObject_CallMethod(self->await_iter, "throw", "O", value);

        // Exit context (even if call failed)
        if(PyContext_Exit(self->context) < 0) {
            Py_DECREF(value);
            Py_XDECREF(result);
            return NULL;
        }
    } else {
        result = PyObject_CallMethod(self->await_iter, "throw", "O", value);
    }
    Py_DECREF(value);  // done with this

    // STATE MODIFICATION: Clear all state fields before setting new state
    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_value);
#if !NEW_EXC
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_traceback);
#endif

    if(result != NULL) {
        // STATE MODIFICATION: Transition to PENDING with new yielded value
        // Coroutine yielded a value - update state to pending with the new value
        self->s_value = result;  // Store new yielded value (becomes pending state)
        self->initial_result = PYGEN_NEXT;
        assert(IS_PENDING(self));
        Py_RETURN_NONE;
    }
    assert(PyErr_Occurred());

    // Check if we got StopIteration (normal completion)
    // self->s_value is null here
    assert(self->s_value == NULL);
    if(PyErr_ExceptionMatches(PyExc_StopIteration)) {
        self->s_value = extract_current_stopiteration_value();
    }

    if(self->s_value == NULL) {
        // STATE MODIFICATION: Transition to DONE with exception
        // Either we had a stopiteration and we could not extract the value, or
        // a regular exception. clearing the current exception state
#if NEW_EXC
        self->s_exc_value = PyErr_GetRaisedException();
#else
        PyErr_Fetch(&self->s_exc_type, &self->s_exc_value, &self->s_exc_traceback);
#endif
        self->initial_result = PYGEN_ERROR;
    } else {
        // STATE MODIFICATION: Transition to DONE with return value
        self->initial_result = PYGEN_RETURN;
    }

    assert(IS_DONE(self));
    Py_RETURN_NONE;
}

static PyObject *corostart_close(PyObject *_self)
{
    CoroStartObject *self = (CoroStartObject *) _self;
    ASSERT_COROSTART_INVARIANT(self);

    PyObject *result;

    // Always close the underlying coroutine
    if(self->context != NULL) {
        // Enter context
        if(PyContext_Enter(self->context) < 0) {
            return NULL;
        }

        // Direct call to coro.close()
        result = PyObject_CallMethod(self->await_iter, "close", NULL);

        // Exit context (even if call failed)
        if(PyContext_Exit(self->context) < 0) {
            Py_XDECREF(result);
            return NULL;
        }
    } else {
        // Direct call to coro.close()
        result = PyObject_CallMethod(self->await_iter, "close", NULL);
    }

    // STATE MODIFICATION: Transition to CONTINUED state
    // Transition to continued() state so that subsequent await attempts
    // trigger the "cannot reuse already awaited coroutine" error in __await__
    Py_CLEAR(self->s_value);
    Py_CLEAR(self->s_exc_value);
#if !NEW_EXC
    Py_CLEAR(self->s_exc_type);
    Py_CLEAR(self->s_exc_traceback);
#endif
    self->initial_result = PYGEN_NEXT;  // Mark as not-done to enter CONTINUED state

    assert(IS_CONTINUED(self));
    return result;
}

/* CoroStart method definitions - defined before slots to avoid MSVC forward declaration
 * issues */
static PyMethodDef corostart_methods[] =
    {{"start",
      (PyCFunction) corostart_start_method,
      METH_VARARGS | METH_KEYWORDS,
      "Start the coroutine execution (only needed when autostart=False)"},
     {"done",
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
    {Py_am_await, corostart_await}, /* Async await protocol */

    {0, NULL},
};

static PyType_Spec corostart_spec = {
    .name = "asynkit._cext.CoroStart",
    .basicsize = sizeof(CoroStartObject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_BASETYPE,
    .slots = corostart_slots,
};

/* ========== COROSTARTWRAPPER TYPE IMPLEMENTATION ========== */

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
#if 0
    TRACE_LOG("corostart_wrapper_iternext() called - delegating to send(None)");
    // __next__ is equivalent to send(None)
    return corostart_wrapper_send(_self, Py_None);
#else
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    // Check if we have start results (first call)
    if(!IS_CONTINUED(corostart)) {
        // This is the first send call - process the eager execution result

        if(IS_DONE(corostart)) {
            if(corostart->s_value != NULL) {
                // We have a result
                if(corostart->s_value == Py_None) {
                    // Optimize StopIteration(None), case, just return NULL with no
                    // exception set
                    // tp_iternext protocol allows NULL and no error set for a regular
                    // None return of the iterator
                    Py_CLEAR(corostart->s_value);
                } else {
                    // set a stopiteration
                    PyErr_Restore(Py_NewRef(PyExc_StopIteration),
                                  corostart->s_value,
                                  NULL);
                    corostart->s_value = NULL;
                }
                // STATE MODIFICATION: Transfer ownership, transition to CONTINUED
                corostart->initial_result = PYGEN_NEXT;  // Mark as continued
                assert(IS_CONTINUED(corostart));
                return NULL;
            }

            // we have an exception, restore it and return error
            // STATE MODIFICATION: Transfer exception, transition to CONTINUED
    #if NEW_EXC
            PyErr_SetRaisedException(corostart->s_exc_value);
            corostart->s_exc_value = NULL;
    #else
            PyErr_Restore(corostart->s_exc_type,
                          corostart->s_exc_value,
                          corostart->s_exc_traceback);
            corostart->s_exc_type = NULL;
            corostart->s_exc_value = NULL;
            corostart->s_exc_traceback = NULL;
    #endif

            corostart->initial_result = PYGEN_NEXT;  // Mark as continued
            assert(IS_CONTINUED(corostart));
            return NULL;
        }

        // we are pending
        // Coroutine yielded a value - return it and clear state to mark as continued
        // STATE MODIFICATION: Transfer value, transition to CONTINUED
        PyObject *result = corostart->s_value;
        corostart->s_value = NULL;
        corostart->initial_result = PYGEN_NEXT;  // Mark as continued
        assert(IS_CONTINUED(corostart));
        return result;
    }

    // No start results - coroutine was already started, delegate to wrapped coroutine

    PyObject *iternext_result;

    // Enter context if provided
    if(corostart->context != NULL) {
        if(PyContext_Enter(corostart->context) < 0) {
            return NULL;
        }

        // Call send() on the wrapped coroutine using PyIter_Send
        iternext_result = call_iter_next(corostart->await_iter);

        if(PyContext_Exit(corostart->context) < 0) {
            Py_XDECREF(iternext_result);
            return NULL;
        }
    } else {
        iternext_result = call_iter_next(corostart->await_iter);
    }

    // Return PyIter_Send result directly - no conversion needed
    return iternext_result;
#endif
}

/* CoroStartWrapper send method - delegates to am_send slot for optimization */
static PyObject *corostart_wrapper_send(PyObject *_self, PyObject *arg)
{
    TRACE_LOG("corostart_wrapper_send() called");
    PyObject *result;
    PySendResult send_result = corostart_wrapper_am_send_slot(_self, arg, &result);

    if(send_result == PYGEN_ERROR) {
        return NULL;
    } else if(send_result == PYGEN_RETURN) {
        PyErr_SetObject(PyExc_StopIteration, result);
        Py_DECREF(result);
        return NULL;
    } else {
        // PYGEN_NEXT - return the yielded value
        return result;
    }
}

/* CoroStartWrapper throw method - required for coroutine protocol */
static PyObject *corostart_wrapper_throw(PyObject *_self, PyObject *exc)
{
    TRACE_LOG("corostart_wrapper_throw() called");
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    // Enter context if provided
    if(corostart->context != NULL) {
        if(PyContext_Enter(corostart->context) < 0) {
            return NULL;
        }
    }

    // Call throw() on the wrapped coroutine
    PyObject *result = PyObject_CallMethod(corostart->await_iter, "throw", "O", exc);

    // Exit context if we entered one
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
    TRACE_LOG("corostart_wrapper_close() called");
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    // Enter context if provided
    if(corostart->context != NULL) {
        if(PyContext_Enter(corostart->context) < 0) {
            return NULL;
        }
    }

    // Call close() on the wrapped coroutine
    PyObject *result = PyObject_CallMethod(corostart->await_iter, "close", NULL);

    // Exit context if we entered one
    if(corostart->context != NULL) {
        if(PyContext_Exit(corostart->context) < 0) {
            Py_XDECREF(result);
            return NULL;
        }
    }

    return result;
}

/* CoroStartWrapper am_send implementation for PyIter_Send optimization */
static PySendResult corostart_wrapper_am_send_slot(PyObject *_self,
                                                   PyObject *arg,
                                                   PyObject **result)
{
    CoroStartWrapperObject *self = (CoroStartWrapperObject *) _self;
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    // Check if we have start results (first call)
    if(!IS_CONTINUED(corostart)) {
        // This is the first send call - process the eager execution result
        // According to PEP 342, first send() must be None
        if(arg != Py_None) {
            PyErr_SetString(PyExc_TypeError,
                            "can't send non-None value to a just-started coroutine");
            *result = NULL;
            return PYGEN_ERROR;
        }

        if(IS_DONE(corostart)) {
            if(corostart->s_value != NULL) {
                // We have a result
                // STATE MODIFICATION: Transfer ownership, transition to CONTINUED
                *result = corostart->s_value;
                corostart->s_value = NULL;
                corostart->initial_result = PYGEN_NEXT;  // Mark as continued
                assert(IS_CONTINUED(corostart));
                return PYGEN_RETURN;
            }

            // we have an exception, restore it and return error
            // STATE MODIFICATION: Transfer exception, transition to CONTINUED
#if NEW_EXC
            PyErr_SetRaisedException(corostart->s_exc_value);
            corostart->s_exc_value = NULL;
#else
            PyErr_Restore(corostart->s_exc_type,
                          corostart->s_exc_value,
                          corostart->s_exc_traceback);
            // Clear (PyErr_Restore steals references) - marks as continued
            corostart->s_exc_type = NULL;
            corostart->s_exc_value = NULL;
            corostart->s_exc_traceback = NULL;
#endif
            corostart->initial_result = PYGEN_NEXT;  // Mark as continued
            *result = NULL;
            assert(IS_CONTINUED(corostart));
            return PYGEN_ERROR;
        }

        // we are pending
        // Coroutine yielded a value - return it and clear state to mark as continued
        // STATE MODIFICATION: Transfer value, transition to CONTINUED
        *result = corostart->s_value;
        corostart->s_value = NULL;
        corostart->initial_result = PYGEN_NEXT;  // Mark as continued
        assert(IS_CONTINUED(corostart));
        return PYGEN_NEXT;
    }

    // No start results - coroutine was already started, delegate to wrapped coroutine

    // Enter context if provided
    if(corostart->context != NULL) {
        if(PyContext_Enter(corostart->context) < 0) {
            *result = NULL;
            return PYGEN_ERROR;
        }
    }

    // Call send() on the wrapped coroutine using PyIter_Send
    PySendResult send_result = PyIter_Send(corostart->await_iter, arg, result);

    // Exit context if we entered one
    if(corostart->context != NULL) {
        if(PyContext_Exit(corostart->context) < 0) {
            if(send_result != PYGEN_ERROR) {
                // Api dictates we must clear result if we return PYGEN_ERROR
                // this error takes precedence over any send result we might
                // have gotten.  If there was an error from send, it will
                // be chained automatically by Python.
                Py_CLEAR(*result);
            }
            return PYGEN_ERROR;
        }
    }

    // Return PyIter_Send result directly - no conversion needed
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

    // Async protocol slot for PyIter_Send optimization
    {Py_am_send, corostart_wrapper_am_send_slot},  // Proper am_send implementation

    {0, NULL},
};

static PyType_Spec corostart_wrapper_spec = {
    .name = "asynkit._cext.CoroStartWrapper",
    .basicsize = sizeof(CoroStartWrapperObject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = corostart_wrapper_slots,
};

/* ========== MODULE DEFINITION ========== */

static PyObject *cext_get_build_info(PyObject *_self)
{
    (void) _self;
    // Return build configuration information
    PyObject *info = PyDict_New();
    if(info == NULL) {
        return NULL;
    }

    PyObject *temp;
    int res;

#ifndef NDEBUG
    const char *build_type = "debug";
#else
    const char *build_type = "optimized";
#endif

    temp = PyUnicode_FromString(build_type);
    if(temp == NULL) {
        Py_DECREF(info);
        return NULL;
    }
    res = PyDict_SetItemString(info, "build_type", temp);
    Py_DECREF(temp);
    if(res < 0) {
        Py_DECREF(info);
        return NULL;
    }
    return info;
}

static PyMethodDef module_methods[] = {{"get_build_info",
                                        (PyCFunction) cext_get_build_info,
                                        METH_NOARGS,
                                        "Get build configuration information"},
                                       {NULL, NULL, 0, NULL}};

/* Module slots for GIL configuration */
#if PY_VERSION_HEX >= 0x030D0000 /* Python 3.13+ */
static PyModuleDef_Slot module_slots[] = {{Py_mod_exec, (void *) cext_exec},
                                          {Py_mod_gil, Py_MOD_GIL_NOT_USED},
                                          {0, NULL}};
#else
static PyModuleDef_Slot module_slots[] = {{Py_mod_exec, (void *) cext_exec}, {0, NULL}};
#endif

/* Module definition */
static struct PyModuleDef cext_module = {
    PyModuleDef_HEAD_INIT,
    "asynkit._cext",
    "Simple C extension for CoroStart",
    sizeof(module_state), /* m_size for per-module state */
    module_methods,
    module_slots,  /* m_slots */
    cext_traverse, /* m_traverse */
    cext_clear,    /* m_clear */
    NULL           /* m_free */
};

/* Module exec function for multi-phase initialization */
static int cext_exec(PyObject *module)
{
    module_state *state = get_module_state(module);
    if(state == NULL) {
        return -1;
    }

#if PY_VERSION_HEX < 0x030B0000
    // Store global module reference for compatibility with Python < 3.11
    Py_XINCREF(module);
    _cext_module_ref = module;
#endif

    // Initialize module state
    state->CoroStartType = NULL;
    state->CoroStartWrapperType = NULL;

    // Add a simple test attribute first
    if(PyModule_AddStringConstant(module, "__test__", "C extension loaded") < 0) {
        return -1;
    }

    // Create CoroStartWrapper type with module association
    state->CoroStartWrapperType = (PyTypeObject *)
        PyType_FromModuleAndSpec(module, &corostart_wrapper_spec, NULL);
    if(state->CoroStartWrapperType == NULL) {
        return -1;
    }

    // Create CoroStart type with module association
    state->CoroStartType = (PyTypeObject *) PyType_FromModuleAndSpec(module,
                                                                     &corostart_spec,
                                                                     NULL);
    if(state->CoroStartType == NULL) {
        return -1;
    }

    // Add types to module (for debugging/introspection)
    Py_INCREF(state->CoroStartWrapperType);
    if(PyModule_AddObject(module,
                          "CoroStartWrapperType",
                          (PyObject *) state->CoroStartWrapperType) < 0) {
        Py_DECREF(state->CoroStartWrapperType);
        return -1;
    }

    // Add CoroStartBase type to module
    Py_INCREF(state->CoroStartType);
    if(PyModule_AddObject(module, "CoroStartBase", (PyObject *) state->CoroStartType) <
       0) {
        Py_DECREF(state->CoroStartType);
        return -1;
    }

    return 0;
}

/* Module traverse function for garbage collection */
static int cext_traverse(PyObject *module, visitproc visit, void *arg)
{
    module_state *state = get_module_state(module);
    if(state == NULL) {
        return 0;
    }

    // Visit all PyObject references in module state
    Py_VISIT(state->CoroStartType);
    Py_VISIT(state->CoroStartWrapperType);

    return 0;
}

/* Module clear function for garbage collection */
static int cext_clear(PyObject *module)
{
    module_state *state = get_module_state(module);
    if(state == NULL) {
        return 0;
    }

#if PY_VERSION_HEX < 0x030B0000
    // Clear global module reference
    if(_cext_module_ref == module) {
        Py_CLEAR(_cext_module_ref);
    }
#endif

    // Clear all PyObject references in module state
    Py_CLEAR(state->CoroStartType);
    Py_CLEAR(state->CoroStartWrapperType);

    return 0;
}

/* Module initialization */
PyMODINIT_FUNC PyInit__cext(void)
{
    return PyModuleDef_Init(&cext_module);
}

// Restore warnings
#if defined(__GNUC__) && !defined(__clang__)
    #pragma GCC diagnostic pop
#elif defined(__clang__)
    #pragma clang diagnostic pop
#elif defined(_MSC_VER)
    #pragma warning(pop)
#endif
