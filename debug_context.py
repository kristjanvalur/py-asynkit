#!/usr/bin/env python3
"""
Debug script to understand context behavior
"""
import asyncio
import contextvars
import asynkit

async def main():
    var = contextvars.ContextVar('test_var')
    var.set('original')
    
    # Create a fresh context 
    ctx = contextvars.copy_context()
    ctx.run(var.set, 'modified')
    
    print(f"Current context var: {var.get()}")
    print(f"Context object id: {id(ctx)}")
    
    # Check if we can use this context with context.run()
    try:
        result = ctx.run(lambda: var.get())
        print(f"ctx.run() result: {result}")
    except Exception as e:
        print(f"ctx.run() failed: {e}")
    
    # Now try creating a CoroStart with this context
    async def test_coro():
        print(f"Inside coro, var = {var.get()}")
        await asyncio.sleep(0)
        print(f"After sleep, var = {var.get()}")
        return "done"
    
    print("\n--- Testing CoroStart with fresh context ---")
    try:
        cs = asynkit.CoroStart(test_coro(), context=ctx)
        if not cs.done():
            result = await cs
            print(f"CoroStart result: {result}")
    except Exception as e:
        print(f"CoroStart failed: {e}")
    
    print("\n--- Testing what happens when context is 'current' ---")
    # Try to make the context current and see what happens
    def test_with_current_context():
        print(f"In context.run, var = {var.get()}")
        
        # Try using the same context again
        try:
            result = ctx.run(lambda: var.get())
            print(f"Nested ctx.run() result: {result}")
        except Exception as e:
            print(f"Nested ctx.run() failed: {e}")
    
    ctx.run(test_with_current_context)

if __name__ == "__main__":
    asyncio.run(main())