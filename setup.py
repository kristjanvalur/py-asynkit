#!/usr/bin/env python3
"""
Setup script for asynkit with optional C extension.

The C extension (_cext) provides performance-critical implementations
of coroutine utilities, particularly CoroStart.
"""

import os
import sys

from setuptools import Extension, setup

# Determine if we should build the C extension
build_ext = True

# Skip C extension on PyPy or if explicitly disabled
if hasattr(sys, "pypy_version_info"):
    build_ext = False
    print("PyPy detected - skipping C extension build")

if os.environ.get("ASYNKIT_DISABLE_CEXT", "").lower() in ("1", "true", "yes"):
    build_ext = False
    print("C extension disabled via ASYNKIT_DISABLE_CEXT")


# Define compilation flags based on build type
def get_compile_args():
    """Get compilation arguments based on environment variables."""
    args = []

    # Check for debug build
    if os.environ.get("ASYNKIT_DEBUG", "").lower() in ("1", "true", "yes"):
        print("Building C extension in DEBUG mode")
        args.extend(
            [
                "-g",  # Debug symbols
                "-O0",  # No optimization
                "-DDEBUG",  # Debug macro
                "-Wall",  # All warnings
                "-Wextra",  # Extra warnings
            ]
        )
    else:
        print("Building C extension in OPTIMIZED mode")
        args.extend(
            [
                "-O3",  # Maximum optimization
                "-DNDEBUG",  # Disable asserts
                "-g",  # Keep debug symbols for profiling
            ]
        )

    # Allow override via CFLAGS environment variable
    env_cflags = os.environ.get("CFLAGS", "")
    if env_cflags:
        print(f"Adding CFLAGS from environment: {env_cflags}")
        args.extend(env_cflags.split())

    return args


# Define the C extension
ext_modules = []
if build_ext:
    corostart_ext = Extension(
        name="asynkit._cext",
        sources=[
            "src/asynkit/_cext/corostart.c",
        ],
        include_dirs=[],
        define_macros=[],
        libraries=[],
        library_dirs=[],
        extra_compile_args=get_compile_args(),
        extra_link_args=[],
        optional=True,  # Don't fail the entire build if C extension fails
    )
    ext_modules.append(corostart_ext)

if __name__ == "__main__":
    setup(
        ext_modules=ext_modules,
        zip_safe=False,  # C extensions require this
    )
