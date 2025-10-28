#!/usr/bin/env python3
"""
Setup script for asynkit with optional C extension.

The C extension (_cext) provides performance-critical implementations
of coroutine utilities, particularly CoroStart.
"""

from setuptools import setup, Extension
import os
import sys

# Determine if we should build the C extension
build_ext = True

# Skip C extension on PyPy or if explicitly disabled
if hasattr(sys, 'pypy_version_info'):
    build_ext = False
    print("PyPy detected - skipping C extension build")

if os.environ.get('ASYNKIT_DISABLE_CEXT', '').lower() in ('1', 'true', 'yes'):
    build_ext = False
    print("C extension disabled via ASYNKIT_DISABLE_CEXT")

# Define the C extension
ext_modules = []
if build_ext:
    corostart_ext = Extension(
        name='asynkit._cext',
        sources=[
            'src/asynkit/_cext/corostart.c',
        ],
        include_dirs=[],
        define_macros=[],
        libraries=[],
        library_dirs=[],
        extra_compile_args=[],
        extra_link_args=[],
        optional=True,  # Don't fail the entire build if C extension fails
    )
    ext_modules.append(corostart_ext)

if __name__ == "__main__":
    setup(
        ext_modules=ext_modules,
        zip_safe=False,  # C extensions require this
    )