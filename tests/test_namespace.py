import asynkit
import asynkit.coroutine
import asynkit.experimental.anyio
import asynkit.loop.default
import asynkit.loop.eventloop
import asynkit.loop.extensions
import asynkit.loop.schedulingloop
import asynkit.loop.types
import asynkit.monitor
import asynkit.scheduling
import asynkit.tools


def test_package_star_exports_public_api_only():
    namespace = {}

    exec("from asynkit import *", namespace)

    exports = {name for name in namespace if not name.startswith("_")}
    assert exports == set(asynkit.__all__)
    assert "coro_start" in exports
    assert "coro_drive" in exports
    assert "syncmethod" in exports
    assert "SyncMethod" in exports
    assert "cancelling" in exports
    assert "coroutine" not in exports
    assert "loop" not in exports
    assert "monitor" not in exports
    assert "scheduling" not in exports
    assert "tools" not in exports


def test_package_all_is_composed_from_public_modules():
    assert asynkit.__all__ == [
        *asynkit.coroutine.__all__,
        *asynkit.loop.eventloop.__all__,
        *asynkit.monitor.__all__,
        *asynkit.scheduling.__all__,
        "cancelling",
    ]


def test_submodule_all_hides_internal_helpers():
    assert "PriEntry" not in asynkit.tools.__all__
    assert "Sortable" not in asynkit.tools.__all__
    assert "TaskStatusForwarder" not in asynkit.experimental.anyio.__all__
    assert "TaskTypes" not in asynkit.loop.default.__all__


def test_submodules_have_explicit_exports():
    modules = [
        asynkit.tools,
        asynkit.loop.default,
        asynkit.loop.extensions,
        asynkit.loop.schedulingloop,
        asynkit.loop.types,
        asynkit.experimental.anyio,
    ]

    for module in modules:
        assert module.__all__
        for name in module.__all__:
            assert hasattr(module, name)
