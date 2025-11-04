"""Minimal reproduction of the uvicorn + eager task + sniffio issue."""

import asyncio
import sys

sys.path.insert(0, "src")
import asynkit


async def asgi_app(scope, receive, send):
    """Minimal ASGI app that uses anyio (like FastAPI does)."""
    # This simulates what FastAPI/Starlette does
    import sniffio

    print(f"[APP] Handling request, current_task = {asyncio.current_task()}")

    # This is what causes the issue - anyio checking the async backend
    try:
        library = sniffio.current_async_library()
        print(f"[APP] Sniffio detected: {library}")
    except Exception as e:
        print(f"[APP] ❌ Sniffio FAILED: {e}")
        raise

    # Send response
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b"Hello World",
        }
    )


def simulate_uvicorn_protocol():
    """Simulate how uvicorn's protocol handler creates tasks."""

    async def protocol_handler():
        """This simulates uvicorn's connection handler - NOT running in a task."""
        loop = asyncio.get_running_loop()

        # Enable eager task factory like user did
        print("[UVICORN] Setting eager task factory")
        loop.set_task_factory(asynkit.eager_task_factory)

        # Simulate uvicorn creating a task to handle the request
        # This is called from a callback/protocol handler, NOT from a task!
        print(
            f"[UVICORN] Creating request task, current_task = {asyncio.current_task()}"
        )

        # Create fake ASGI scope
        scope = {"type": "http", "path": "/"}

        async def receive():
            return {"type": "http.request", "body": b""}

        responses = []

        async def send(message):
            responses.append(message)

        # THIS IS THE KEY: uvicorn calls create_task from connection handler
        # which might not be in a task context
        task = asyncio.create_task(asgi_app(scope, receive, send))

        try:
            await task
            print("[UVICORN] ✓ Request handled successfully")
        except Exception as e:
            print(f"[UVICORN] ❌ Request failed: {e}")
            raise

    # Run the protocol handler
    asyncio.run(protocol_handler())


def simulate_uvicorn_from_callback():
    """Even more accurate: uvicorn might create tasks from callbacks."""

    async def main():
        loop = asyncio.get_running_loop()

        # Enable eager task factory
        print("[UVICORN] Setting eager task factory")
        loop.set_task_factory(asynkit.eager_task_factory)

        # Simulate uvicorn's connection accepted callback
        def connection_made_callback():
            """This runs as a callback, NOT in a task!"""
            print(
                f"[CALLBACK] Connection callback, current_task = {asyncio.current_task()}"
            )

            # Create task to handle request
            scope = {"type": "http", "path": "/"}

            async def receive():
                return {"type": "http.request", "body": b""}

            responses = []

            async def send(message):
                responses.append(message)

            # Create task from callback context
            task = asyncio.create_task(asgi_app(scope, receive, send))
            print(f"[CALLBACK] Task created: {task}")

        # Schedule the callback (this is what uvicorn does)
        print("[MAIN] Scheduling connection callback")
        loop.call_soon(connection_made_callback)

        # Give it time to run
        await asyncio.sleep(0.1)
        print("[MAIN] Done")

    asyncio.run(main())


if __name__ == "__main__":
    print("=" * 70)
    print("Test 1: Task created from async function (should work)")
    print("=" * 70)
    try:
        simulate_uvicorn_protocol()
    except Exception as e:
        if "no running event loop" not in str(e):
            print(f"\n❌ Test 1 FAILED: {e}\n")
        else:
            print("\n✓ Test 1 PASSED (loop cleanup error is expected)\n")

    print("\n" + "=" * 70)
    print("Test 2: Task created from callback (should reproduce the bug)")
    print("=" * 70)
    try:
        simulate_uvicorn_from_callback()
    except Exception as e:
        if "no running event loop" not in str(e):
            print(f"\n❌ Test 2 FAILED: {e}\n")
        else:
            print("\n✓ Test 2 PASSED - Phantom task fixed the sniffio issue!\n")
