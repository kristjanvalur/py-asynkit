#include <Python.h>
#include "cpython/genobject.h"

int main() {
    Py_Initialize();
    
    // Create a simple coroutine to examine
    PyObject *code_str = PyUnicode_FromString("async def test(): return 42");
    PyObject *globals = PyDict_New();
    PyObject *locals = PyDict_New();
    
    // Compile and execute the coroutine definition
    PyObject *code_obj = Py_CompileString(PyUnicode_AsUTF8(code_str), "<test>", Py_file_input);
    if (code_obj) {
        PyObject *result = PyEval_EvalCode(code_obj, globals, locals);
        if (result) {
            // Get the test function
            PyObject *test_func = PyDict_GetItemString(locals, "test");
            if (test_func) {
                // Call it to get a coroutine
                PyObject *coro = PyObject_CallObject(test_func, NULL);
                if (coro) {
                    printf("Created coroutine: %p\n", coro);
                    printf("Type: %s\n", Py_TYPE(coro)->tp_name);
                    printf("Is PyCoro_Type: %d\n", PyCoro_CheckExact(coro));
                    
                    // Check the type's method table
                    PyTypeObject *coro_type = Py_TYPE(coro);
                    printf("tp_methods: %p\n", coro_type->tp_methods);
                    
                    if (coro_type->tp_methods) {
                        PyMethodDef *methods = coro_type->tp_methods;
                        for (int i = 0; methods[i].ml_name != NULL; i++) {
                            printf("  Method %d: %s -> %p\n", i, methods[i].ml_name, methods[i].ml_meth);
                        }
                    }
                    
                    // Try to call close
                    PyObject *close_result = PyObject_CallMethod(coro, "close", NULL);
                    if (close_result) {
                        Py_DECREF(close_result);
                    }
                    Py_DECREF(coro);
                }
            }
            Py_DECREF(result);
        }
        Py_DECREF(code_obj);
    }
    
    Py_DECREF(locals);
    Py_DECREF(globals);
    Py_DECREF(code_str);
    
    Py_Finalize();
    return 0;
}
