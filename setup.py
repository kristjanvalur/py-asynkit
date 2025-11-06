#!/usr/bin/env python3
"""
Setup script for asynkit with optional C extension.

The C extension (_cext) provides performance-critical implementations
of coroutine utilities, particularly CoroStart.
"""

import os
import sys

from setuptools import setup
from setuptools.command.build_ext import build_ext as _build_ext
from setuptools.extension import Extension


class OptionalBuildExt(_build_ext):
    """Custom build_ext that gracefully handles C extension failures."""

    def build_extension(self, ext):
        try:
            super().build_extension(ext)
            print(f"[OK] Successfully built C extension: {ext.name}")
            print("  -> asynkit will use high-performance C implementation")
        except Exception as e:
            print(f"[WARNING] Failed to build C extension {ext.name}:")
            print(f"  -> {e}")
            print("  -> asynkit will use Python implementation")
            print("  -> For 4x performance boost, install build tools:")

            # Platform-specific guidance
            import platform

            system = platform.system().lower()
            if system == "windows":
                print("    pip install setuptools")
                print("    Install Visual Studio Build Tools")
            elif system == "darwin":
                print("    xcode-select --install")
            elif system == "linux":
                print("    apt install python3-dev build-essential  # Ubuntu/Debian")
                print("    yum install python3-devel gcc  # CentOS/RHEL")

            # Don't re-raise - let setup continue without the extension


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
    """Get compilation arguments based on environment variables and compiler."""
    import platform

    args = []
    is_msvc = platform.system() == "Windows"

    # Enable modern C standards
    if is_msvc:
        # Enable C17 standard for MSVC (latest C standard)
        args.append("/std:c17")
    else:
        # Enable C17 standard for GCC/Clang (latest C standard)
        args.append("-std=c17")

    # Check for debug build
    if os.environ.get("ASYNKIT_DEBUG", "").lower() in ("1", "true", "yes"):
        print("Building C extension in DEBUG mode")
        if is_msvc:
            args.extend(
                [
                    "/Zi",  # Debug symbols
                    "/Od",  # No optimization
                    "/UNDEBUG",  # Undefine NDEBUG to enable asserts
                    "/W3",  # Warning level 3
                ]
            )
        else:
            args.extend(
                [
                    "-g",  # Debug symbols
                    "-O0",  # No optimization
                    "-UNDEBUG",  # Undefine NDEBUG to enable asserts
                    "-Wall",  # All warnings
                    "-Wextra",  # Extra warnings
                ]
            )
    else:
        print("Building C extension in OPTIMIZED mode")
        if is_msvc:
            args.extend(
                [
                    "/O2",  # Maximum optimization
                    "/DNDEBUG",  # Disable asserts
                    "/Zi",  # Keep debug symbols for profiling
                ]
            )
        else:
            args.extend(
                [
                    "-O3",  # Maximum optimization
                    "-DNDEBUG",  # Disable asserts
                    "-g",  # Keep debug symbols for profiling
                ]
            )

    # Add strict warnings to catch MSVC compatibility issues
    if not is_msvc:
        # These warnings help catch issues that would fail on MSVC
        args.extend(
            [
                "-Wstrict-prototypes",  # Require function prototypes
                "-Wincompatible-pointer-types",  # Catch pointer type mismatches
                "-Wold-style-definition",  # Require modern function definitions
                "-Wmissing-prototypes",  # Require function declarations
                "-Wunused-variable",  # Catch unused variables (like our typecasts)
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
    # Check if we should force compilation and fail on errors
    force_cext = os.environ.get("ASYNKIT_FORCE_CEXT", "").lower() in (
        "1",
        "true",
        "yes",
    )

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
        optional=not force_cext,  # Make required if forcing, optional otherwise
    )
    ext_modules.append(corostart_ext)

if __name__ == "__main__":
    setup(
        ext_modules=ext_modules,
        cmdclass={"build_ext": OptionalBuildExt},  # Use our custom build class
        zip_safe=False,  # C extensions require this
    )
