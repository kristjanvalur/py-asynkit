"""Compatibility routines for earlier asyncio versions"""

import asyncio
import sys
from typing import TYPE_CHECKING, Any, TypeVar
from weakref import ReferenceType

# Python version checks
PY_311 = sys.version_info >= (3, 11)

T = TypeVar("T")

# The following is needed because some generic types (like asyncio.Task and
# weakref.ReferenceType) cannot be subscripted at runtime, even in Python 3.10+.
# We use TYPE_CHECKING to provide subscripted types for mypy while using
# unsubscripted types at runtime to avoid TypeError.
if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
    FutureBool = asyncio.Future[bool]
    ReferenceTypeTaskAny = ReferenceType[_TaskAny]
else:
    _TaskAny = asyncio.Task
    FutureBool = asyncio.Future
    ReferenceTypeTaskAny = ReferenceType
