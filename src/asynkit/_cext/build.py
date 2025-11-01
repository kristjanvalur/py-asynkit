# C Extension Module
# This module will be built as asynkit._cext

from typing import Any

from setuptools import Extension


def build(setup_kwargs: dict[str, Any]) -> None:
    """Build configuration for the C extension"""

    ext_modules = [
        Extension(
            name="asynkit._cext",
            sources=[
                "src/asynkit/_cext/corostart.c",
            ],
            include_dirs=[],
            define_macros=[],
            libraries=[],
            library_dirs=[],
            extra_compile_args=[],
            extra_link_args=[],
        )
    ]

    setup_kwargs.update(
        {
            "ext_modules": ext_modules,
            "zip_safe": False,
        }
    )
