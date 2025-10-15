# Example: README with Emoji-Enhanced Notes

This shows what the existing README would look like with emojis added to Note sections (the quick-win improvement).

## Snippet 1: Eager execution note (Informational)

**Before:**
```markdown
> **Note:** Python 3.12+ introduced native eager task execution via `asyncio.eager_task_factory`. See [docs/eager_tasks.md](docs/eager_tasks.md) for a detailed comparison of Python's built-in eager tasks and asynkit's `eager()` feature.
```

**After:**
```markdown
> ℹ️ **Note:** Python 3.12+ introduced native eager task execution via `asyncio.eager_task_factory`. See [docs/eager_tasks.md](docs/eager_tasks.md) for a detailed comparison of Python's built-in eager tasks and asynkit's `eager()` feature.
```

---

## Snippet 2: Experimental feature note

**Before:**
```markdown
> **Note:** This is currently an __experimental__ feature.
```

**After:**
```markdown
> 🧪 **Note:** This is currently an experimental feature.
```

---

## Snippet 3: Deprecation warning

**Before:**
```markdown
> **Note:** Event loop policies are deprecated as of Python 3.14 and will be removed in Python 3.16.
```

**After:**
```markdown
> ⚠️ **Note:** Event loop policies are deprecated as of Python 3.14 and will be removed in Python 3.16.
```

---

## Snippet 4: Platform/version-specific limitation

**Before:**
```markdown
> **Note:** Task interruption with `_PyTask` objects does not work on Python 3.14.0 due to a bug
> in `asyncio.current_task()` that prevents it from recognizing tasks created by custom task factories.
> This affects the `create_pytask()` function and any code using it.
> C Tasks (from `asyncio.create_task()`) have limited interrupt support.
```

**After:**
```markdown
> ⚠️ **Note:** Task interruption with `_PyTask` objects does not work on Python 3.14.0 due to a bug
> in `asyncio.current_task()` that prevents it from recognizing tasks created by custom task factories.
> This affects the `create_pytask()` function and any code using it.
> C Tasks (from `asyncio.create_task()`) have limited interrupt support.
```

---

## Impact

These small changes make the README significantly more scannable:

1. **Visual breaks**: Emojis catch the eye when scrolling
2. **Information hierarchy**: Quick identification of note type
3. **Professional appearance**: Modern documentation style
4. **Consistency**: Matches patterns used by FastAPI, Pydantic V2, and other modern Python projects

## Implementation

All four Note blocks in the current README can be updated with just 4 simple edits.
No other content needs to change.
