/*
 * asynkit C Extension - CoroStart with CoroStartWrapper
 * 
 * Phase 3: Create CoroStartWrapper that implements both iterator and coroutine protocols
 * following the PyCoroWrapper pattern discovered in CPython source
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

/* Forward declarations */
static PyTypeObject CoroStartType;
static PyTypeObject CoroStartWrapperType;

/* CoroStartWrapper - implements both iterator and coroutine protocols */
typedef struct {
    PyObject_HEAD
    PyObject *corostart;     /* Reference to our CoroStart object */
    PyObject *wrapped_iter;  /* The wrapped coroutine iterator (lazy-initialized) */
} CoroStartWrapperObject;

/* CoroStart object structure */
typedef struct {
    PyObject_HEAD
    PyObject *wrapped_coro;  /* The wrapped coroutine */
    PyObject *context;       /* Context for execution (can be NULL) */
} CoroStartObject;

/* Helper function to get or create the wrapped iterator */
static PyObject *
corostart_wrapper_get_iterator(CoroStartWrapperObject *self)
{
    if (self->wrapped_iter != NULL) {
        return self->wrapped_iter;  /* Already have it */
    }
    
    if (self->corostart == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "CoroStart object is NULL");
        return NULL;
    }
    
    /* Get the CoroStart object */
    CoroStartObject *corostart = (CoroStartObject *)self->corostart;
    
    if (corostart->wrapped_coro == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "wrapped coroutine is NULL");
        return NULL;
    }
    
    /* Get the coroutine's iterator via __await__ */
    PyObject *coro_iter = PyObject_CallMethod(corostart->wrapped_coro, "__await__", NULL);
    if (coro_iter == NULL) {
        return NULL;
    }
    
    /* Cache it for future use */
    self->wrapped_iter = coro_iter;  /* Transfer ownership */
    
    return coro_iter;
}

/* CoroStartWrapper deallocation */
static void
corostart_wrapper_dealloc(CoroStartWrapperObject *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->corostart);
    Py_XDECREF(self->wrapped_iter);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* CoroStartWrapper garbage collection traversal */
static int
corostart_wrapper_traverse(CoroStartWrapperObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->corostart);
    Py_VISIT(self->wrapped_iter);
    return 0;
}

/* CoroStartWrapper garbage collection clear */
static int
corostart_wrapper_clear(CoroStartWrapperObject *self)
{
    Py_CLEAR(self->corostart);
    Py_CLEAR(self->wrapped_iter);
    return 0;
}

/* CoroStartWrapper __iter__ method - required for iterator protocol */
static PyObject *
corostart_wrapper_iter(CoroStartWrapperObject *self)
{
    Py_INCREF(self);
    return (PyObject *)self;
}

/* CoroStartWrapper __next__ method - required for iterator protocol */
static PyObject *
corostart_wrapper_iternext(CoroStartWrapperObject *self)
{
    PyObject *wrapped_iter = corostart_wrapper_get_iterator(self);
    if (wrapped_iter == NULL) {
        return NULL;
    }
    
    /* Call __next__ on the wrapped iterator using PyObject_CallMethod */
    return PyObject_CallMethod(wrapped_iter, "__next__", NULL);
}

/* CoroStartWrapper send method - required for coroutine protocol */
static PyObject *
corostart_wrapper_send(CoroStartWrapperObject *self, PyObject *arg)
{
    PyObject *wrapped_iter = corostart_wrapper_get_iterator(self);
    if (wrapped_iter == NULL) {
        return NULL;
    }
    
    /* Call send() on the wrapped iterator using PyObject_CallMethod */
    return PyObject_CallMethod(wrapped_iter, "send", "O", arg);
}

/* CoroStartWrapper throw method - required for coroutine protocol */
static PyObject *
corostart_wrapper_throw(CoroStartWrapperObject *self, PyObject *args)
{
    PyObject *wrapped_iter = corostart_wrapper_get_iterator(self);
    if (wrapped_iter == NULL) {
        return NULL;
    }
    
    /* Call throw() on the wrapped iterator using PyObject_CallMethod */
    /* Note: we pass the args tuple directly since throw can take 1-3 args */
    return PyObject_CallMethod(wrapped_iter, "throw", "O", args);
}

/* CoroStartWrapper close method - required for coroutine protocol */
static PyObject *
corostart_wrapper_close(CoroStartWrapperObject *self, PyObject *Py_UNUSED(ignored))
{
    if (self->wrapped_iter == NULL) {
        Py_RETURN_NONE;  /* Nothing to close yet */
    }
    
    PyObject *result = PyObject_CallMethod(self->wrapped_iter, "close", NULL);
    if (result != NULL) {
        Py_CLEAR(self->wrapped_iter);  /* Clear the cached iterator */
    }
    return result;
}

/* CoroStartWrapper methods */
static PyMethodDef corostart_wrapper_methods[] = {
    {"send", (PyCFunction)corostart_wrapper_send, METH_O, "Send a value into the wrapper."},
    {"throw", (PyCFunction)corostart_wrapper_throw, METH_VARARGS, "Throw an exception into the wrapper."},
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
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* CoroStart garbage collection traversal */
static int
corostart_traverse(CoroStartObject *self, visitproc visit, void *arg)
{
    Py_VISIT(self->wrapped_coro);
    Py_VISIT(self->context);
    return 0;
}

/* CoroStart garbage collection clear */
static int
corostart_clear(CoroStartObject *self)
{
    Py_CLEAR(self->wrapped_coro);
    Py_CLEAR(self->context);
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
    
    wrapper->wrapped_iter = NULL;  /* Will be created lazily when needed */
    
    return (PyObject *)wrapper;
}

/* Async protocol support */
static PyAsyncMethods corostart_as_async = {
    .am_await = (unaryfunc)corostart_await,
};

/* CoroStart methods */
static PyMethodDef corostart_methods[] = {
    {NULL, NULL, 0, NULL}
};

/* CoroStart type definition */
static PyTypeObject CoroStartType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "asynkit._cext.CoroStart",
    .tp_basicsize = sizeof(CoroStartObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_new = PyType_GenericNew,
    .tp_dealloc = (destructor)corostart_dealloc,
    .tp_traverse = (traverseproc)corostart_traverse,
    .tp_clear = (inquiry)corostart_clear,
    .tp_methods = corostart_methods,
    .tp_as_async = &corostart_as_async,
};

/* Constructor function - updated for new structure */
static PyObject *
corostart_new_wrapper(PyObject *self, PyObject *args)
{
    PyObject *coro;
    PyObject *context = NULL;  /* Optional context parameter */
    
    if (!PyArg_ParseTuple(args, "O|O", &coro, &context)) {
        return NULL;
    }
    
    /* Create CoroStart object */
    CoroStartObject *cs = (CoroStartObject *)CoroStartType.tp_alloc(&CoroStartType, 0);
    if (cs == NULL) {
        return NULL;
    }
    
    /* Store the coroutine and context */
    cs->wrapped_coro = Py_NewRef(coro);
    cs->context = context;
    Py_XINCREF(cs->context);
    
    return (PyObject *)cs;
}

/* Module methods */
static PyMethodDef module_methods[] = {
    {"CoroStart", corostart_new_wrapper, METH_VARARGS, "Create CoroStart wrapper"},
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
    
    return module;
}
