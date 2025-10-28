/*
 * asynkit C Extension - CoroStart with CoroStartWrapper
 * 
 * Phase 3: Create CoroStartWrapper that implements both iterator and coroutine protocols
 * following the PyCoroWrapper pattern discovered in CPython source
 * 
 * Updated: 2025-10-28 - Added consumed() and suspended() API methods
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
    PyObject_HEAD
    PyObject *corostart;     /* Reference to our CoroStart object */
} CoroStartWrapperObject;

/* Forward declaration of wrapper methods */
static PyObject *corostart_wrapper_send(CoroStartWrapperObject *self, PyObject *arg);

/* CoroStart object structure */
typedef struct {
    PyObject_HEAD
    PyObject *wrapped_coro;
    PyObject *context;
    PyObject *s_value;        // completed value (if not exception)
    PyObject *s_exc_type;     // exception type (if completed with exception)
    PyObject *s_exc_value;    // exception value
    PyObject *s_exc_traceback; // exception traceback
} CoroStartObject;

/* CoroStart _start method - simplified eager execution logic */
static int
corostart_start(CoroStartObject *self)
{
    if (self->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return -1;
    }
    
    /* Try to send None to start the coroutine (with context support) */
    if (self->context != NULL) {
        /* Use context.run(coro.send, None) */
        PyObject *send_method = PyObject_GetAttrString(self->wrapped_coro, "send");
        if (send_method == NULL) {
            return -1;
        }
        self->s_value = PyObject_CallMethod(self->context, "run", "OO", send_method, Py_None);
        Py_DECREF(send_method);
    } else {
        /* Direct call to coro.send(None) */
        self->s_value = PyObject_CallMethod(self->wrapped_coro, "send", "O", Py_None);
    }

    if (self->s_value != NULL) {
        /* Coroutine yielded a value - it's suspended */
        return 0;  /* Success */
    } else {
        /* Exception occurred - fetch and store it */
        PyErr_Fetch(&self->s_exc_type, &self->s_exc_value, &self->s_exc_traceback);
        return 0;  /* Success (we handled the exception) */
    }
}

/* CoroStartWrapper deallocation */
static void
corostart_wrapper_dealloc(CoroStartWrapperObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->corostart);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* CoroStartWrapper garbage collection traversal */
static int
corostart_wrapper_traverse(CoroStartWrapperObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->corostart);
    return 0;
}

/* CoroStartWrapper garbage collection clear */
static int
corostart_wrapper_clear(CoroStartWrapperObject *self)
{
    Py_CLEAR(self->corostart);
    return 0;
}

/* CoroStartWrapper __iter__ method - required for iterator protocol */
static PyObject *
corostart_wrapper_iter(CoroStartWrapperObject *self)
{
    Py_INCREF(self);
    return (PyObject *)self;
}

/* CoroStartWrapper __next__ method - alias for send(None) */
static PyObject *
corostart_wrapper_iternext(CoroStartWrapperObject *self)
{
    /* __next__ is equivalent to send(None) */
    return corostart_wrapper_send(self, Py_None);
}

/* CoroStartWrapper send method - simplified to handle start state */
static PyObject *
corostart_wrapper_send(CoroStartWrapperObject *self, PyObject *arg)
{
    if (self->corostart == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "CoroStart object is NULL");
        return NULL;
    }
    
    CoroStartObject *corostart = (CoroStartObject *)self->corostart;
    
    /* Check if we have start results (first call) */
    if (corostart->s_value != NULL || corostart->s_exc_type != NULL) {
        /* This is the first send call - process the eager execution result */
        /* According to PEP 342, first send() must be None */
        if (arg != Py_None) {
            PyErr_SetString(PyExc_TypeError, "can't send non-None value to a just-started coroutine");
            return NULL;
        }
        
        if (corostart->s_exc_type != NULL) {
            /* Exception occurred during start - re-raise it and clear state */
            PyErr_Restore(corostart->s_exc_type, corostart->s_exc_value, corostart->s_exc_traceback);
            /* Clear the fields (PyErr_Restore steals references) - marks as consumed */
            corostart->s_exc_type = NULL;
            corostart->s_exc_value = NULL;
            corostart->s_exc_traceback = NULL;
            return NULL;
        }
        
        if (corostart->s_value != NULL) {
            /* Coroutine yielded a value - return it and clear state to mark as consumed */
            PyObject *result = corostart->s_value;
            corostart->s_value = NULL;  /* Clear and transfer ownership - marks as consumed */
            return result;
        }
        
        /* This shouldn't happen */
        PyErr_SetString(PyExc_RuntimeError, "Invalid start state");
        return NULL;
    }

    /* Check if consumed (all start result fields are NULL) */
    if (corostart->s_value == NULL && corostart->s_exc_type == NULL && 
        corostart->s_exc_value == NULL && corostart->s_exc_traceback == NULL) {
        /* Consumed coroutine, trigger the "cannot reuse" error */
        return PyObject_CallMethod(corostart->wrapped_coro, "send", "O", Py_None);
    }

    /* No start results - coroutine was already started, delegate to wrapped coroutine */
    if (corostart->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    /* Call send() on the wrapped coroutine (with context support) */
    if (corostart->context != NULL) {
        /* Use context.run(coro.send, arg) */
        PyObject *send_method = PyObject_GetAttrString(corostart->wrapped_coro, "send");
        if (send_method == NULL) {
            return NULL;
        }
        PyObject *result = PyObject_CallMethod(corostart->context, "run", "OO", send_method, arg);
        Py_DECREF(send_method);
        return result;
    } else {
        /* Direct call to coro.send(arg) */
        return PyObject_CallMethod(corostart->wrapped_coro, "send", "O", arg);
    }
}

/* CoroStartWrapper throw method - required for coroutine protocol */
static PyObject *
corostart_wrapper_throw(CoroStartWrapperObject *self, PyObject *exc)
{
    if (self->corostart == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "CoroStart object is NULL");
        return NULL;
    }
    
    CoroStartObject *corostart = (CoroStartObject *)self->corostart;
    if (corostart->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    /* Call throw() on the wrapped coroutine (with context support) */
    /* Single exception argument - matches coroutine protocol */
    if (corostart->context != NULL) {
        /* Use context.run(coro.throw, exc) */
        PyObject *throw_method = PyObject_GetAttrString(corostart->wrapped_coro, "throw");
        if (throw_method == NULL) {
            return NULL;
        }
        PyObject *result = PyObject_CallMethod(corostart->context, "run", "OO", throw_method, exc);
        Py_DECREF(throw_method);
        return result;
    } else {
        /* Direct call to coro.throw(exc) */
        return PyObject_CallMethod(corostart->wrapped_coro, "throw", "O", exc);
    }
}

/* CoroStartWrapper close method - required for coroutine protocol */
static PyObject *
corostart_wrapper_close(CoroStartWrapperObject *self, PyObject *Py_UNUSED(ignored))
{
    if (self->corostart == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "CoroStart object is NULL");
        return NULL;
    }
    
    CoroStartObject *corostart = (CoroStartObject *)self->corostart;
    if (corostart->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    /* Call close() directly on the wrapped coroutine */
    return PyObject_CallMethod(corostart->wrapped_coro, "close", NULL);
}

/* CoroStartWrapper methods */
static PyMethodDef corostart_wrapper_methods[] = {
    {"send", (PyCFunction)corostart_wrapper_send, METH_O, "Send a value into the wrapper."},
    {"throw", (PyCFunction)corostart_wrapper_throw, METH_O, "Throw an exception into the wrapper."},
    {"close", (PyCFunction)corostart_wrapper_close, METH_NOARGS, "Close the wrapper."},
    {NULL, NULL, 0, NULL}
};

/* CoroStartWrapper type definition */
static PyTypeObject CoroStartWrapperType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "asynkit._cext.CoroStartWrapper",
    .tp_basicsize = sizeof(CoroStartWrapperObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_new = PyType_GenericNew,
    .tp_dealloc = (destructor)corostart_wrapper_dealloc,
    .tp_traverse = (traverseproc)corostart_wrapper_traverse,
    .tp_clear = (inquiry)corostart_wrapper_clear,
    .tp_iter = (getiterfunc)corostart_wrapper_iter,
    .tp_iternext = (iternextfunc)corostart_wrapper_iternext,
    .tp_methods = corostart_wrapper_methods,
};

/* CoroStart deallocation */
static void
corostart_dealloc(CoroStartObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->wrapped_coro);
    Py_XDECREF(self->context);
    Py_XDECREF(self->s_value);
    Py_XDECREF(self->s_exc_type);
    Py_XDECREF(self->s_exc_value);
    Py_XDECREF(self->s_exc_traceback);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* CoroStart garbage collection traversal */
static int
corostart_traverse(CoroStartObject *self, visitproc visit, void *arg)
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
static int
corostart_clear(CoroStartObject *self)
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
static PyObject *
corostart_await(CoroStartObject *self)
{
    if (self->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "no wrapped coroutine");
        return NULL;
    }
    
    /* Create our CoroStartWrapper that holds a reference to this CoroStart */
    CoroStartWrapperObject *wrapper = (CoroStartWrapperObject *)CoroStartWrapperType.tp_alloc(&CoroStartWrapperType, 0);
    if (wrapper == NULL) {
        return NULL;
    }
    
    wrapper->corostart = (PyObject *)self;
    Py_INCREF(wrapper->corostart);
    
    return (PyObject *)wrapper;
}

/* Async protocol support */
static PyAsyncMethods corostart_as_async = {
    .am_await = (unaryfunc)corostart_await,
};

/* CoroStart methods */
static PyObject *
corostart_done(CoroStartObject *self, PyObject *args) {
    // Return True if we have completed (indicated by having an exception)
    // Either StopIteration (normal completion) or any other exception (error)
    if (self->s_exc_type != NULL) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *
corostart_consumed(CoroStartObject *self, PyObject *Py_UNUSED(args)) {
    // Return True if the coroutine has been consumed by the await mechanism  
    // In C implementation, consumed means all start result fields are NULL
    if (self->s_value == NULL && self->s_exc_type == NULL && 
        self->s_exc_value == NULL && self->s_exc_traceback == NULL) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *
corostart_suspended(CoroStartObject *self, PyObject *Py_UNUSED(args)) {
    // Return True if the coroutine is suspended waiting for async operation
    // This means we have a yielded value but no exception
    if (self->s_value != NULL && self->s_exc_type == NULL) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *
corostart_result(CoroStartObject *self, PyObject *args) {
    // Check if we're done (must have an exception)
    if (self->s_exc_type == NULL) {
        // Use asyncio.InvalidStateError to match Python implementation
        PyObject *asyncio_module = PyImport_ImportModule("asyncio");
        if (asyncio_module) {
            PyObject *invalid_state_error = PyObject_GetAttrString(asyncio_module, "InvalidStateError");
            Py_DECREF(asyncio_module);
            if (invalid_state_error) {
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
    if (PyErr_GivenExceptionMatches(self->s_exc_type, PyExc_StopIteration)) {
        // Check if s_exc_value is an instance of the exception type
        if (self->s_exc_value && PyObject_IsInstance(self->s_exc_value, self->s_exc_type)) {
            // s_exc_value is an actual StopIteration instance
            PyObject *value = PyObject_GetAttrString(self->s_exc_value, "value");
            if (value == NULL) {
                PyErr_Clear();
                Py_RETURN_NONE;
            }
            return value;
        } else {
            // s_exc_value is the raw value (Python optimization)
            if (self->s_exc_value) {
                Py_INCREF(self->s_exc_value);
                return self->s_exc_value;
            } else {
                Py_RETURN_NONE;
            }
        }
    } else {
        // Re-raise other exceptions using Restore
        PyErr_Restore(
            Py_XNewRef(self->s_exc_type),
            Py_XNewRef(self->s_exc_value), 
            Py_XNewRef(self->s_exc_traceback)
        );
        return NULL;
    }
}

static PyObject *
corostart_exception(CoroStartObject *self, PyObject *args) {
    // Check if we're done (must have an exception)
    if (self->s_exc_type == NULL) {
        // Use asyncio.InvalidStateError to match Python implementation
        PyObject *asyncio_module = PyImport_ImportModule("asyncio");
        if (asyncio_module) {
            PyObject *invalid_state_error = PyObject_GetAttrString(asyncio_module, "InvalidStateError");
            Py_DECREF(asyncio_module);
            if (invalid_state_error) {
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
    if (PyErr_GivenExceptionMatches(self->s_exc_type, PyExc_StopIteration)) {
        // Normal completion - return None
        Py_RETURN_NONE;
    } else {
        // Return the exception (not re-raise it like result() does)
        if (self->s_exc_value && PyObject_IsInstance(self->s_exc_value, self->s_exc_type)) {
            // s_exc_value is an actual exception instance
            Py_INCREF(self->s_exc_value);
            return self->s_exc_value;
        } else {
            // s_exc_value is the raw value, need to construct exception
            PyObject *exc_instance = PyObject_CallFunction(self->s_exc_type, "O", 
                self->s_exc_value ? self->s_exc_value : Py_None);
            return exc_instance;
        }
    }
}

static PyObject *
corostart_throw(CoroStartObject *self, PyObject *args, PyObject *kwargs) {
    PyObject *exc;
    long tries = 1;  // Default tries = 1
    
    static char *kwlist[] = {"exc", "tries", NULL};
    
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|l", kwlist, &exc, &tries)) {
        return NULL;
    }
    
    if (self->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    // Convert exception type to instance if needed
    PyObject *value;
    if (PyExceptionInstance_Check(exc)) {
        // exc is already an exception instance
        value = exc;
        Py_INCREF(value);
    } else if (PyExceptionClass_Check(exc)) {
        // exc is an exception type, instantiate it
        value = PyObject_CallFunction(exc, NULL);
        if (value == NULL) {
            return NULL;
        }
    } else {
        PyErr_SetString(PyExc_TypeError, "throw() arg must be an exception");
        return NULL;
    }
    
    // State-aware handling: check if we're in post-start, pre-await phase
    if (self->s_value != NULL || self->s_exc_type != NULL) {
        // We're in the pre-await state - throw and update start_result
        // Apply the same retry logic as the post-await state
        for (long i = 0; i < tries; i++) {
            PyObject *result;
            
            // Call throw() with context support
            if (self->context != NULL) {
                PyObject *throw_method = PyObject_GetAttrString(self->wrapped_coro, "throw");
                if (throw_method == NULL) {
                    Py_DECREF(value);
                    return NULL;
                }
                result = PyObject_CallMethod(self->context, "run", "OO", throw_method, value);
                Py_DECREF(throw_method);
            } else {
                result = PyObject_CallMethod(self->wrapped_coro, "throw", "O", value);
            }
            
            if (result != NULL) {
                // Coroutine continued after throw - update start_result for later await
                Py_CLEAR(self->s_value);
                Py_CLEAR(self->s_exc_type);
                Py_CLEAR(self->s_exc_value);
                Py_CLEAR(self->s_exc_traceback);
                self->s_value = result;  // Store new yielded value
                // Continue retry loop since coroutine didn't exit
                continue;
            }
            
            // Check if we got StopIteration (normal completion)
            if (PyErr_ExceptionMatches(PyExc_StopIteration)) {
                PyObject *exc_type, *exc_value, *exc_traceback;
                PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);
                
                // Coroutine finished synchronously - clear state and return result
                Py_CLEAR(self->s_value);
                Py_CLEAR(self->s_exc_type);
                Py_CLEAR(self->s_exc_value);
                Py_CLEAR(self->s_exc_traceback);
                
                // Extract the value from StopIteration
                PyObject *stop_value = NULL;
                if (exc_value && PyObject_IsInstance(exc_value, PyExc_StopIteration)) {
                    stop_value = PyObject_GetAttrString(exc_value, "value");
                    if (stop_value == NULL) {
                        PyErr_Clear();
                    }
                }
                if (stop_value == NULL) {
                    stop_value = exc_value ? exc_value : Py_None;
                    Py_INCREF(stop_value);
                }
                
                Py_XDECREF(exc_type);
                if (exc_value != stop_value) {
                    Py_XDECREF(exc_value);
                }
                Py_XDECREF(exc_traceback);
                Py_DECREF(value);
                return stop_value;
            }
            
            // Other exception - update start_result and re-raise
            PyObject *exc_type, *exc_value, *exc_traceback;
            PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);
            
            Py_CLEAR(self->s_value);
            Py_CLEAR(self->s_exc_type);
            Py_CLEAR(self->s_exc_value);
            Py_CLEAR(self->s_exc_traceback);
            
            self->s_exc_type = exc_type;
            self->s_exc_value = exc_value;
            self->s_exc_traceback = exc_traceback;
            
            Py_DECREF(value);
            PyErr_Restore(Py_XNewRef(exc_type), Py_XNewRef(exc_value), Py_XNewRef(exc_traceback));
            return NULL;
        }
        
        // Exhausted retries in pre-await state
        PyObject *exc_type_name = PyObject_GetAttrString((PyObject *)Py_TYPE(value), "__name__");
        PyObject *error_msg = PyUnicode_FromFormat("coroutine ignored %U", exc_type_name);
        Py_XDECREF(exc_type_name);
        Py_DECREF(value);
        
        if (error_msg) {
            PyErr_SetObject(PyExc_RuntimeError, error_msg);
            Py_DECREF(error_msg);
        } else {
            PyErr_SetString(PyExc_RuntimeError, "coroutine ignored exception");
        }
        return NULL;
    }
    
    // Original retry logic for post-await state
    for (long i = 0; i < tries; i++) {
        PyObject *result;
        
        // Call throw() with context support
        if (self->context != NULL) {
            // Use context.run(coro.throw, value)
            PyObject *throw_method = PyObject_GetAttrString(self->wrapped_coro, "throw");
            if (throw_method == NULL) {
                Py_DECREF(value);
                return NULL;
            }
            result = PyObject_CallMethod(self->context, "run", "OO", throw_method, value);
            Py_DECREF(throw_method);
        } else {
            // Direct call to coro.throw(value)
            result = PyObject_CallMethod(self->wrapped_coro, "throw", "O", value);
        }
        
        if (result != NULL) {
            // throw() returned normally - coroutine didn't exit, it yielded a value
            // This means the coroutine caught the exception and continued
            Py_DECREF(result);  // Ignore the yielded value
            // Continue the loop to try again
            continue;
        }
        
        // Check if we got StopIteration (normal completion)
        if (PyErr_ExceptionMatches(PyExc_StopIteration)) {
            PyObject *exc_type, *exc_value, *exc_traceback;
            PyErr_Fetch(&exc_type, &exc_value, &exc_traceback);
            
            // Extract the value from StopIteration
            PyObject *stop_value = NULL;
            if (exc_value && PyObject_IsInstance(exc_value, PyExc_StopIteration)) {
                stop_value = PyObject_GetAttrString(exc_value, "value");
                if (stop_value == NULL) {
                    PyErr_Clear();
                }
            }
            if (stop_value == NULL) {
                // If we couldn't get the value attribute, use the exception value itself
                stop_value = exc_value ? exc_value : Py_None;
                Py_INCREF(stop_value);
            }
            
            Py_XDECREF(exc_type);
            if (exc_value != stop_value) {
                Py_XDECREF(exc_value);
            }
            Py_XDECREF(exc_traceback);
            Py_DECREF(value);
            return stop_value;
        }
        
        // Other exception occurred, continue the loop if we have more tries
        if (i < tries - 1) {
            PyErr_Clear();  // Clear the error for next iteration
        }
    }
    
    // All tries exhausted, raise RuntimeError
    PyObject *exc_type_name = PyObject_GetAttrString((PyObject *)Py_TYPE(value), "__name__");
    PyObject *error_msg = PyUnicode_FromFormat("coroutine ignored %U", exc_type_name);
    Py_XDECREF(exc_type_name);
    Py_DECREF(value);
    
    if (error_msg) {
        PyErr_SetObject(PyExc_RuntimeError, error_msg);
        Py_DECREF(error_msg);
    } else {
        PyErr_SetString(PyExc_RuntimeError, "coroutine ignored exception");
    }
    
    return NULL;
}

static PyObject *
corostart_close(CoroStartObject *self, PyObject *args) {
    // Close the coroutine - state-aware like Python implementation
    // Post-start, pre-await: Close coroutine and clear start_result  
    // Post-await: Close coroutine directly (original behavior)
    
    if (self->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    // State-aware handling: check if we're in post-start, pre-await phase
    if (self->s_value != NULL || self->s_exc_type != NULL) {
        // We're in the pre-await state - close the coroutine and clear state
        PyObject *result;
        
        // Call close() with context support
        if (self->context != NULL) {
            // Create a callable that will invoke close()
            PyObject *close_callable = PyObject_GetAttrString(self->wrapped_coro, "close");
            if (close_callable == NULL) {
                return NULL;
            }
            // Call context.run(close_callable)
            result = PyObject_CallMethod(self->context, "run", "O", close_callable);
            Py_DECREF(close_callable);
        } else {
            // Direct call to coro.close()
            result = PyObject_CallMethod(self->wrapped_coro, "close", NULL);
        }
        
        // Always clear start result after closing in pre-await state
        Py_CLEAR(self->s_value);
        Py_CLEAR(self->s_exc_type);
        Py_CLEAR(self->s_exc_value);
        Py_CLEAR(self->s_exc_traceback);
        
        return result;
    } else {
        // Post-await state - close the coroutine directly (original behavior)
        if (self->context != NULL) {
            // Create a callable that will invoke close()
            PyObject *close_callable = PyObject_GetAttrString(self->wrapped_coro, "close");
            if (close_callable == NULL) {
                return NULL;
            }
            // Call context.run(close_callable)
            PyObject *result = PyObject_CallMethod(self->context, "run", "O", close_callable);
            Py_DECREF(close_callable);
            return result;
        } else {
            // Direct call to coro.close()
            return PyObject_CallMethod(self->wrapped_coro, "close", NULL);
        }
    }
}

static PyMethodDef corostart_methods[] = {
    {"done", (PyCFunction)corostart_done, METH_NOARGS, "Return True if coroutine finished synchronously during initial start"},
    {"consumed", (PyCFunction)corostart_consumed, METH_NOARGS, "Return True if coroutine has been consumed by the await mechanism"},
    {"suspended", (PyCFunction)corostart_suspended, METH_NOARGS, "Return True if coroutine is suspended waiting for async operation"},
    {"result", (PyCFunction)corostart_result, METH_NOARGS, "Return result or raise exception"},
    {"exception", (PyCFunction)corostart_exception, METH_NOARGS, "Return exception or None"},
    {"throw", (PyCFunction)corostart_throw, METH_VARARGS | METH_KEYWORDS, "Throw an exception into the coroutine"},
    {"close", (PyCFunction)corostart_close, METH_NOARGS, "Close the coroutine"},
    {NULL, NULL, 0, NULL}
};

/* CoroStart type definition */
static PyTypeObject CoroStartType = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "asynkit._cext.CoroStart",
    .tp_basicsize = sizeof(CoroStartObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_BASETYPE,
    .tp_new = corostart_new,
    .tp_dealloc = (destructor)corostart_dealloc,
    .tp_traverse = (traverseproc)corostart_traverse,
    .tp_clear = (inquiry)corostart_clear,
    .tp_methods = corostart_methods,
    .tp_as_async = &corostart_as_async,
};

/* CoroStart type constructor */
static PyObject *
corostart_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    PyObject *coro;
    PyObject *context = NULL;  /* Optional context parameter */
    
    static char *kwlist[] = {"coro", "context", NULL};
    
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|O", kwlist, &coro, &context)) {
        return NULL;
    }
    
    /* Create CoroStart object */
    CoroStartObject *cs = (CoroStartObject *)type->tp_alloc(type, 0);
    if (cs == NULL) {
        return NULL;
    }
    
    /* Store the coroutine and context */
    cs->wrapped_coro = Py_NewRef(coro);
    
    /* Convert None to NULL for context - this makes context checks work properly */
    if (context == Py_None) {
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
    if (corostart_start(cs) < 0) {
        /* _start failed */
        Py_DECREF(cs);
        return NULL;
    }
    
    return (PyObject *)cs;
}

/* Module methods */
static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}
};

/* Module definition */
static struct PyModuleDef cext_module = {
    PyModuleDef_HEAD_INIT,
    "asynkit._cext",
    "Simple C extension for CoroStart",
    -1,
    module_methods
};

/* Module initialization */
PyMODINIT_FUNC
PyInit__cext(void)
{
    PyObject *module = PyModule_Create(&cext_module);
    if (module == NULL) {
        return NULL;
    }
    
    /* Initialize CoroStartWrapper type */
    if (PyType_Ready(&CoroStartWrapperType) < 0) {
        Py_DECREF(module);
        return NULL;
    }
    
    /* Initialize CoroStart type */
    if (PyType_Ready(&CoroStartType) < 0) {
        Py_DECREF(module);
        return NULL;
    }
    
    /* Add types to module (for debugging/introspection) */
    Py_INCREF(&CoroStartWrapperType);
    if (PyModule_AddObject(module, "CoroStartWrapperType", (PyObject *)&CoroStartWrapperType) < 0) {
        Py_DECREF(&CoroStartWrapperType);
        Py_DECREF(module);
        return NULL;
    }
    
    /* Add CoroStartBase type to module */
    Py_INCREF(&CoroStartType);
    if (PyModule_AddObject(module, "CoroStartBase", (PyObject *)&CoroStartType) < 0) {
        Py_DECREF(&CoroStartType);
        Py_DECREF(module);
        return NULL;
    }
    
    return module;
}
