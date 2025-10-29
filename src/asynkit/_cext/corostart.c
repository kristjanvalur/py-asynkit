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

/* Forward declarations */
static PyTypeObject CoroStartType;
static PyTypeObject CoroStartWrapperType;

/* Forward declaration of methods */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs);

/* CoroStartWrapper - implements both iterator and coroutine protocols */
typedef struct {
    PyObject_HEAD;
    PyObject *corostart; /* Reference to our CoroStart object */
} CoroStartWrapperObject;

/* Forward declaration of wrapper methods */
static PyObject *corostart_wrapper_send(CoroStartWrapperObject *self, PyObject *arg);

/* CoroStart object structure */
typedef struct {
    PyObject_HEAD;
    PyObject *wrapped_coro;
    PyObject *context;
    PyObject *s_value;          // completed value (if not exception)
    PyObject *s_exc_type;       // exception type (if completed with exception)
    PyObject *s_exc_value;      // exception value
    PyObject *s_exc_traceback;  // exception traceback
} CoroStartObject;

/* State checking macros for CoroStart objects */
#define IS_DONE(self) ((self)->s_exc_type != NULL)
#define IS_PENDING(self) ((self)->s_value != NULL)
#define IS_CONTINUED(self)                                                             \
    ((self)->s_value == NULL && (self)->s_exc_type == NULL &&                          \
     (self)->s_exc_value == NULL && (self)->s_exc_traceback == NULL)

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
    /* Try to send None to start the coroutine (with context support) */
    if(self->context != NULL) {
        /* Use context.run(coro.send, None) */
        PyObject *send_method = PyObject_GetAttrString(self->wrapped_coro, "send");
        if(send_method == NULL) {
            return -1;
        }
        self->s_value =
            PyObject_CallMethod(self->context, "run", "OO", send_method, Py_None);
        Py_DECREF(send_method);
    } else {
        /* Direct call to coro.send(None) */
        self->s_value = PyObject_CallMethod(self->wrapped_coro, "send", "O", Py_None);
    }

    if(IS_PENDING(self)) {
        /* Coroutine yielded a value - it's pending */
        assert_corostart_invariant(self);
        return 0; /* Success */
    } else {
        /* Exception occurred - fetch and store it */
        PyErr_Fetch(&self->s_exc_type, &self->s_exc_value, &self->s_exc_traceback);
        assert_corostart_invariant(self);
        return 0; /* Success (we handled the exception) */
    }
}

/* CoroStartWrapper deallocation */
static void corostart_wrapper_dealloc(CoroStartWrapperObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->corostart);
    Py_TYPE(self)->tp_free((PyObject *) self);
}

/* CoroStartWrapper garbage collection traversal */
static int corostart_wrapper_traverse(CoroStartWrapperObject *self,
                                      visitproc visit,
                                      void *arg)
{
    Py_VISIT(self->corostart);
    return 0;
}

/* CoroStartWrapper garbage collection clear */
static int corostart_wrapper_clear(CoroStartWrapperObject *self)
{
    Py_CLEAR(self->corostart);
    return 0;
}

/* CoroStartWrapper __iter__ method - required for iterator protocol */
static PyObject *corostart_wrapper_iter(CoroStartWrapperObject *self)
{
    Py_INCREF(self);
    return (PyObject *) self;
}

/* CoroStartWrapper __next__ method - alias for send(None) */
static PyObject *corostart_wrapper_iternext(CoroStartWrapperObject *self)
{
    /* __next__ is equivalent to send(None) */
    return corostart_wrapper_send(self, Py_None);
}

/* CoroStartWrapper send method - simplified to handle start state */
static PyObject *corostart_wrapper_send(CoroStartWrapperObject *self, PyObject *arg)
{
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    /* Check if we have start results (first call) */
    if(!IS_CONTINUED(corostart)) {
        /* This is the first send call - process the eager execution result */
        /* According to PEP 342, first send() must be None */
        if(arg != Py_None) {
            PyErr_SetString(PyExc_TypeError,
                            "can't send non-None value to a just-started coroutine");
            return NULL;
        }

        if(IS_DONE(corostart)) {
            /* Exception occurred during start - re-raise it and clear state */
            PyErr_Restore(corostart->s_exc_type,
                          corostart->s_exc_value,
                          corostart->s_exc_traceback);
            /* Clear the fields (PyErr_Restore steals references) - marks as continued
             */
            corostart->s_exc_type = NULL;
            corostart->s_exc_value = NULL;
            corostart->s_exc_traceback = NULL;
            return NULL;
        }

        // we are pending
        /* Coroutine yielded a value - return it and clear state to mark as continued */
        PyObject *result = corostart->s_value;
        corostart->s_value =
            NULL; /* Clear and transfer ownership - marks as continued */
        return result;
    }

    /* No start results - coroutine was already started, delegate to wrapped coroutine
     */

    /* Call send() on the wrapped coroutine (with context support) */
    if(corostart->context != NULL) {
        PyObject *send_method = PyObject_GetAttrString(corostart->wrapped_coro, "send");
        if(send_method == NULL) {
            return NULL;
        }
        /* Use context.run(coro.send, arg) */
        PyObject *result =
            PyObject_CallMethod(corostart->context, "run", "OO", send_method, arg);
        Py_DECREF(send_method);
        return result;
    } else {
        /* Direct call to coro.send(arg) */
        return PyObject_CallMethod(corostart->wrapped_coro, "send", "O", arg);
    }
}

/* CoroStartWrapper throw method - required for coroutine protocol */
static PyObject *corostart_wrapper_throw(CoroStartWrapperObject *self, PyObject *exc)
{
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    /* Call throw() on the wrapped coroutine (with context support) */
    /* Single exception argument - matches coroutine protocol */
    if(corostart->context != NULL) {
        /* Use context.run(coro.throw, exc) */
        PyObject *throw_method = PyObject_GetAttrString(corostart->wrapped_coro,
                                                        "throw");
        if(throw_method == NULL) {
            return NULL;
        }
        PyObject *result =
            PyObject_CallMethod(corostart->context, "run", "OO", throw_method, exc);
        Py_DECREF(throw_method);
        return result;
    } else {
        /* Direct call to coro.throw(exc) */
        return PyObject_CallMethod(corostart->wrapped_coro, "throw", "O", exc);
    }
}

/* CoroStartWrapper close method - required for coroutine protocol */
static PyObject *corostart_wrapper_close(CoroStartWrapperObject *self,
                                         PyObject *Py_UNUSED(ignored))
{
    CoroStartObject *corostart = (CoroStartObject *) self->corostart;

    PyObject *result;

    // If a context is provided, use context.run() to call close
    if(corostart->context != Py_None && corostart->context != NULL) {
        // Create a callable that will invoke close()
        PyObject *close_callable = PyObject_GetAttrString(corostart->wrapped_coro,
                                                          "close");
        if(close_callable == NULL) {
            return NULL;
        }
        // Call context.run(close_callable)
        result = PyObject_CallMethod(corostart->context, "run", "O", close_callable);
        Py_DECREF(close_callable);
    } else {
        // Direct call to coro.close()
        result = PyObject_CallMethod(corostart->wrapped_coro, "close", NULL);
    }

    return result;
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

/* CoroStartWrapper type definition */
static PyTypeObject CoroStartWrapperType = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "asynkit._cext.CoroStartWrapper",
    .tp_basicsize = sizeof(CoroStartWrapperObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_new = PyType_GenericNew,
    .tp_dealloc = (destructor) corostart_wrapper_dealloc,
    .tp_traverse = (traverseproc) corostart_wrapper_traverse,
    .tp_clear = (inquiry) corostart_wrapper_clear,
    .tp_iter = (getiterfunc) corostart_wrapper_iter,
    .tp_iternext = (iternextfunc) corostart_wrapper_iternext,
    .tp_methods = corostart_wrapper_methods,
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
                                          .tp_alloc(&CoroStartWrapperType, 0);
    if(wrapper == NULL) {
        return NULL;
    }

    wrapper->corostart = (PyObject *) self;
    Py_INCREF(wrapper->corostart);

    return (PyObject *) wrapper;
}

/* Async protocol support */
static PyAsyncMethods corostart_as_async = {
    .am_await = (unaryfunc) corostart_await,
};

/* CoroStart methods */
static PyObject *corostart_done(CoroStartObject *self, PyObject *args)
{
    assert_corostart_invariant(self);
    // Return True if we have completed (indicated by having an exception)
    // Either StopIteration (normal completion) or any other exception (error)
    if(IS_DONE(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_continued(CoroStartObject *self, PyObject *Py_UNUSED(args))
{
    assert_corostart_invariant(self);
    // Return True if the coroutine has been continued (awaited) after initial start
    // In C implementation, continued means all start result fields are NULL
    if(IS_CONTINUED(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_pending(CoroStartObject *self, PyObject *Py_UNUSED(args))
{
    assert_corostart_invariant(self);
    // Return True if the coroutine is pending, waiting for async operation
    // This means we have a yielded value (s_value != NULL)
    if(IS_PENDING(self)) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *corostart_result(CoroStartObject *self, PyObject *args)
{
    // Check if we're done (must have an exception)
    if(self->s_exc_type == NULL) {
        // Use asyncio.InvalidStateError to match Python implementation
        PyObject *asyncio_module = PyImport_ImportModule("asyncio");
        if(asyncio_module) {
            PyObject *invalid_state_error = PyObject_GetAttrString(asyncio_module,
                                                                   "InvalidStateError");
            Py_DECREF(asyncio_module);
            if(invalid_state_error) {
                PyErr_SetString(invalid_state_error, "CoroStart: coroutine not done()");
                Py_DECREF(invalid_state_error);
            } else {
                PyErr_SetString(PyExc_RuntimeError, "CoroStart: coroutine not done()");
            }
        } else {
            PyErr_SetString(PyExc_RuntimeError, "CoroStart: coroutine not done()");
        }
        return NULL;
    }

    // Check if it's StopIteration (normal completion)
    if(PyErr_GivenExceptionMatches(self->s_exc_type, PyExc_StopIteration)) {
        // Check if s_exc_value is an instance of the exception type
        if(self->s_exc_value &&
           PyObject_IsInstance(self->s_exc_value, self->s_exc_type)) {
            // s_exc_value is an actual StopIteration instance
            PyObject *value = PyObject_GetAttrString(self->s_exc_value, "value");
            if(value == NULL) {
                PyErr_Clear();
                Py_RETURN_NONE;
            }
            return value;
        } else {
            // s_exc_value is the raw value (Python optimization)
            if(self->s_exc_value) {
                Py_INCREF(self->s_exc_value);
                return self->s_exc_value;
            } else {
                Py_RETURN_NONE;
            }
        }
    } else {
        // Re-raise other exceptions using Restore
        PyErr_Restore(Py_XNewRef(self->s_exc_type),
                      Py_XNewRef(self->s_exc_value),
                      Py_XNewRef(self->s_exc_traceback));
        return NULL;
    }
}

static PyObject *corostart_exception(CoroStartObject *self, PyObject *args)
{
    // Check if we're done (must have an exception)
    if(self->s_exc_type == NULL) {
        // Use asyncio.InvalidStateError to match Python implementation
        PyObject *asyncio_module = PyImport_ImportModule("asyncio");
        if(asyncio_module) {
            PyObject *invalid_state_error = PyObject_GetAttrString(asyncio_module,
                                                                   "InvalidStateError");
            Py_DECREF(asyncio_module);
            if(invalid_state_error) {
                PyErr_SetString(invalid_state_error, "CoroStart: coroutine not done()");
                Py_DECREF(invalid_state_error);
            } else {
                PyErr_SetString(PyExc_RuntimeError, "CoroStart: coroutine not done()");
            }
        } else {
            PyErr_SetString(PyExc_RuntimeError, "CoroStart: coroutine not done()");
        }
        return NULL;
    }

    // Check if it's StopIteration (normal completion)
    if(PyErr_GivenExceptionMatches(self->s_exc_type, PyExc_StopIteration)) {
        // Normal completion - return None
        Py_RETURN_NONE;
    } else {
        // Return the exception (not re-raise it like result() does)
        if(self->s_exc_value &&
           PyObject_IsInstance(self->s_exc_value, self->s_exc_type)) {
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
}

static PyObject *corostart__throw(CoroStartObject *self, PyObject *exc)
{
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
        PyObject *throw_method = PyObject_GetAttrString(self->wrapped_coro, "throw");
        if(throw_method == NULL) {
            Py_DECREF(value);
            return NULL;
        }
        result = PyObject_CallMethod(self->context, "run", "OO", throw_method, value);
        Py_DECREF(throw_method);
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

        // Set done state with StopIteration exception
        self->s_exc_type = exc_type;
        self->s_exc_value = exc_value;
        self->s_exc_traceback = exc_traceback;

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

    Py_DECREF(value);
    Py_RETURN_NONE;
}


static PyObject *corostart_close(CoroStartObject *self, PyObject *args)
{
    assert_corostart_invariant(self);

    PyObject *result;

    // Always close the underlying coroutine
    if(self->context != NULL) {
        // Create a callable that will invoke close()
        PyObject *close_callable = PyObject_GetAttrString(self->wrapped_coro, "close");
        if(close_callable == NULL) {
            return NULL;
        }
        // Call context.run(close_callable)
        result = PyObject_CallMethod(self->context, "run", "O", close_callable);
        Py_DECREF(close_callable);
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

/* CoroStart type definition */
static PyTypeObject CoroStartType = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "asynkit._cext.CoroStart",
    .tp_basicsize = sizeof(CoroStartObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_BASETYPE,
    .tp_new = corostart_new,
    .tp_dealloc = (destructor) corostart_dealloc,
    .tp_traverse = (traverseproc) corostart_traverse,
    .tp_clear = (inquiry) corostart_clear,
    .tp_methods = corostart_methods,
    .tp_as_async = &corostart_as_async,
};

/* CoroStart type constructor */
static PyObject *corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    PyObject *coro;
    PyObject *context = NULL; /* Optional context parameter */

    static char *kwlist[] = {"coro", "context", NULL};

    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "O|O", kwlist, &coro, &context)) {
        return NULL;
    }

    /* Create CoroStart object */
    CoroStartObject *cs = (CoroStartObject *) type->tp_alloc(type, 0);
    if(cs == NULL) {
        return NULL;
    }

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
static PyMethodDef module_methods[] = {{NULL, NULL, 0, NULL}};

/* Module definition */
static struct PyModuleDef cext_module = {PyModuleDef_HEAD_INIT,
                                         "asynkit._cext",
                                         "Simple C extension for CoroStart",
                                         -1,
                                         module_methods};

/* Module initialization */
PyMODINIT_FUNC PyInit__cext(void)
{
    PyObject *module = PyModule_Create(&cext_module);
    if(module == NULL) {
        return NULL;
    }

    /* Initialize CoroStartWrapper type */
    if(PyType_Ready(&CoroStartWrapperType) < 0) {
        Py_DECREF(module);
        return NULL;
    }

    /* Initialize CoroStart type */
    if(PyType_Ready(&CoroStartType) < 0) {
        Py_DECREF(module);
        return NULL;
    }

    /* Add types to module (for debugging/introspection) */
    Py_INCREF(&CoroStartWrapperType);
    if(PyModule_AddObject(module,
                          "CoroStartWrapperType",
                          (PyObject *) &CoroStartWrapperType) < 0) {
        Py_DECREF(&CoroStartWrapperType);
        Py_DECREF(module);
        return NULL;
    }

    /* Add CoroStartBase type to module */
    Py_INCREF(&CoroStartType);
    if(PyModule_AddObject(module, "CoroStartBase", (PyObject *) &CoroStartType) < 0) {
        Py_DECREF(&CoroStartType);
        Py_DECREF(module);
        return NULL;
    }

    return module;
}
