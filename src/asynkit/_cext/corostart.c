/*
 * asynkit C Extension - CoroStart implementation
 * 
 * High-performance C implementation of CoroStart to eliminate Python
 * generator overhead in the suspend/resume hot path.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <structmember.h>

/* Forward declarations */
static PyTypeObject CoroStartType;

/* CoroStart object structure */
typedef struct {
    PyObject_HEAD
    PyObject *wrapped_coro;  /* The wrapped coroutine */
    int started;             /* Have we started execution? */
    PyObject *result;        /* Cached result if completed synchronously */
    int done;                /* Has execution finished? */
} CoroStartObject;

/* Deallocation */
static void
corostart_dealloc(CoroStartObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->wrapped_coro);
    Py_XDECREF(self->result);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* Garbage collection traversal */
static int
corostart_traverse(CoroStartObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->wrapped_coro);
    Py_VISIT(self->result);
    return 0;
}

/* Clear for garbage collection */
static int
corostart_clear(CoroStartObject *self)
{
    Py_CLEAR(self->wrapped_coro);
    Py_CLEAR(self->result);
    return 0;
}

/* Iterator next - the hot path function */
static PyObject *
corostart_iternext(PyObject *self_obj)
{
    CoroStartObject *self = (CoroStartObject *)self_obj;
    
    if (self->done) {
        /* Already completed - raise StopIteration with result */
        if (self->result != NULL) {
            PyErr_SetObject(PyExc_StopIteration, self->result);
        } else {
            PyErr_SetNone(PyExc_StopIteration);
        }
        return NULL;
    }
    
    /* Direct delegation to wrapped coroutine's tp_iternext */
    /* This is the key optimization - no Python generator frames */
    PyObject *result = Py_TYPE(self->wrapped_coro)->tp_iternext(self->wrapped_coro);
    
    if (result == NULL && PyErr_ExceptionMatches(PyExc_StopIteration)) {
        /* Coroutine completed - cache the result */
        PyObject *exc_type, *exc_value, *exc_tb;
        PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
        
        if (exc_value != NULL) {
            self->result = PyObject_GetAttrString(exc_value, "value");
            if (self->result == NULL) {
                /* If no 'value' attribute, use None */
                PyErr_Clear();
                self->result = Py_NewRef(Py_None);
            }
        } else {
            self->result = Py_NewRef(Py_None);
        }
        
        self->done = 1;
        
        /* Re-raise StopIteration with our cached result */
        PyErr_SetObject(PyExc_StopIteration, self->result);
        
        Py_XDECREF(exc_type);
        Py_XDECREF(exc_value);
        Py_XDECREF(exc_tb);
    }
    
    return result;
}

/* Send method - delegate to wrapped coroutine */
static PyObject *
corostart_send(CoroStartObject *self, PyObject *arg)
{
    if (self->done) {
        PyErr_SetString(PyExc_StopIteration, "cannot send to a completed coroutine");
        return NULL;
    }
    
    if (!self->started) {
        if (arg != Py_None) {
            PyErr_SetString(PyExc_TypeError, "can't send non-None value to a just-started coroutine");
            return NULL;
        }
        self->started = 1;
    }
    
    /* Direct call to wrapped coroutine's send method */
    PyObject *result = PyObject_CallMethod(self->wrapped_coro, "send", "O", arg);
    
    if (result == NULL && PyErr_ExceptionMatches(PyExc_StopIteration)) {
        /* Handle completion same as iternext */
        PyObject *exc_type, *exc_value, *exc_tb;
        PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
        
        if (exc_value != NULL) {
            self->result = PyObject_GetAttrString(exc_value, "value");
            if (self->result == NULL) {
                PyErr_Clear();
                self->result = Py_NewRef(Py_None);
            }
        } else {
            self->result = Py_NewRef(Py_None);
        }
        
        self->done = 1;
        
        PyErr_SetObject(PyExc_StopIteration, self->result);
        
        Py_XDECREF(exc_type);
        Py_XDECREF(exc_value);
        Py_XDECREF(exc_tb);
    }
    
    return result;
}

/* Throw method - delegate to wrapped coroutine */
static PyObject *
corostart_throw(CoroStartObject *self, PyObject *args)
{
    if (self->done) {
        PyErr_SetString(PyExc_StopIteration, "cannot throw to a completed coroutine");
        return NULL;
    }
    
    /* Forward throw call to wrapped coroutine */
    PyObject *result = PyObject_CallMethod(self->wrapped_coro, "throw", "O", args);
    
    if (result == NULL && PyErr_ExceptionMatches(PyExc_StopIteration)) {
        /* Handle completion */
        PyObject *exc_type, *exc_value, *exc_tb;
        PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
        
        if (exc_value != NULL) {
            self->result = PyObject_GetAttrString(exc_value, "value");
            if (self->result == NULL) {
                PyErr_Clear();
                self->result = Py_NewRef(Py_None);
            }
        } else {
            self->result = Py_NewRef(Py_None);
        }
        
        self->done = 1;
        
        PyErr_SetObject(PyExc_StopIteration, self->result);
        
        Py_XDECREF(exc_type);
        Py_XDECREF(exc_value);
        Py_XDECREF(exc_tb);
    }
    
    return result;
}

/* Close method - delegate to wrapped coroutine */
static PyObject *
corostart_close(CoroStartObject *self, PyObject *Py_UNUSED(ignored))
{
    if (self->done) {
        Py_RETURN_NONE;
    }
    
    PyObject *result = PyObject_CallMethod(self->wrapped_coro, "close", NULL);
    if (result != NULL) {
        self->done = 1;
    }
    return result;
}

/* Check if coroutine completed synchronously */
static PyObject *
corostart_done(CoroStartObject *self, PyObject *Py_UNUSED(ignored))
{
    return PyBool_FromLong(self->done);
}

/* Get result (only valid if done) */
static PyObject *
corostart_result(CoroStartObject *self, PyObject *Py_UNUSED(ignored))
{
    if (!self->done) {
        PyErr_SetString(PyExc_RuntimeError, "coroutine not yet completed");
        return NULL;
    }
    
    return Py_NewRef(self->result ? self->result : Py_None);
}

/* Method definitions */
static PyMethodDef corostart_methods[] = {
    {"send", (PyCFunction)corostart_send, METH_O, "Send a value into the coroutine."},
    {"throw", (PyCFunction)corostart_throw, METH_VARARGS, "Throw an exception into the coroutine."},
    {"close", (PyCFunction)corostart_close, METH_NOARGS, "Close the coroutine."},
    {"done", (PyCFunction)corostart_done, METH_NOARGS, "Check if coroutine completed synchronously."},
    {"result", (PyCFunction)corostart_result, METH_NOARGS, "Get result (only valid if done)."},
    {NULL, NULL, 0, NULL}
};

/* Type object definition */
static PyTypeObject CoroStartType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "asynkit._cext.CoroStart",
    .tp_doc = "C implementation of CoroStart for performance",
    .tp_basicsize = sizeof(CoroStartObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_new = PyType_GenericNew,
    .tp_dealloc = (destructor)corostart_dealloc,
    .tp_traverse = (traverseproc)corostart_traverse,
    .tp_clear = (inquiry)corostart_clear,
    .tp_iter = PyObject_SelfIter,
    .tp_iternext = corostart_iternext,
    .tp_methods = corostart_methods,
};

/* Constructor function - starts the coroutine eagerly */
static PyObject *
corostart_new_wrapper(PyObject *self, PyObject *args)
{
    PyObject *coro;
    if (!PyArg_ParseTuple(args, "O", &coro)) {
        return NULL;
    }
    
    /* Create new CoroStart object */
    CoroStartObject *cs = (CoroStartObject *)CoroStartType.tp_alloc(&CoroStartType, 0);
    if (cs == NULL) {
        return NULL;
    }
    
    cs->wrapped_coro = Py_NewRef(coro);
    cs->started = 0;
    cs->done = 0;
    cs->result = NULL;
    
    /* Try to start the coroutine immediately (eager execution) */
    PyObject *initial = Py_TYPE(coro)->tp_iternext(coro);
    if (initial == NULL) {
        /* Coroutine completed synchronously */
        if (PyErr_ExceptionMatches(PyExc_StopIteration)) {
            /* Extract result from StopIteration */
            PyObject *exc_type, *exc_value, *exc_tb;
            PyErr_Fetch(&exc_type, &exc_value, &exc_tb);
            
            if (exc_value != NULL) {
                cs->result = PyObject_GetAttrString(exc_value, "value");
                if (cs->result == NULL) {
                    PyErr_Clear();
                    cs->result = Py_NewRef(Py_None);
                }
            } else {
                cs->result = Py_NewRef(Py_None);
            }
            
            cs->done = 1;
            PyErr_Clear();  /* Clear the StopIteration */
            
            Py_XDECREF(exc_type);
            Py_XDECREF(exc_value);
            Py_XDECREF(exc_tb);
        } else {
            /* Some other exception occurred */
            Py_DECREF(cs);
            return NULL;
        }
    } else {
        /* Coroutine suspended - we'll resume later via iterator protocol */
        Py_DECREF(initial);
    }
    
    cs->started = 1;
    return (PyObject *)cs;
}

/* Module method definitions */
static PyMethodDef module_methods[] = {
    {"CoroStart", corostart_new_wrapper, METH_VARARGS, "Create a new CoroStart object"},
    {NULL, NULL, 0, NULL}
};

/* Module definition */
static struct PyModuleDef cext_module = {
    PyModuleDef_HEAD_INIT,
    "asynkit._cext",
    "C extension for asynkit performance-critical components",
    -1,
    module_methods
};

/* Module initialization */
PyMODINIT_FUNC
PyInit__cext(void)
{
    PyObject *module;
    
    /* Create the module */
    module = PyModule_Create(&cext_module);
    if (module == NULL) {
        return NULL;
    }
    
    /* Finalize the CoroStart type */
    if (PyType_Ready(&CoroStartType) < 0) {
        Py_DECREF(module);
        return NULL;
    }
    
    /* Add CoroStart type to module */
    Py_INCREF(&CoroStartType);
    if (PyModule_AddObject(module, "CoroStartType", (PyObject *)&CoroStartType) < 0) {
        Py_DECREF(&CoroStartType);
        Py_DECREF(module);
        return NULL;
    }
    
    return module;
}