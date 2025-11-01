@echo off
REM Check C code formatting with clang-format
REM Optional - skips gracefully if clang-format is not available

cd /d "%~dp0\.."

REM Check if clang-format is available
where clang-format >nul 2>&1
if %errorlevel% neq 0 (
    echo ^⚠️  clang-format not found - skipping C code style check
    echo    Install clang-format for C code style validation
    exit /b 0
)

echo ✅ Checking C code formatting...

set "exit_code=0"
set "checked_count=0"

for /r "src\asynkit\_cext" %%f in (*.c *.h) do (
    if exist "%%f" (
        echo   🔍 Checking: %%f
        clang-format --dry-run --Werror "%%f" >nul 2>&1
        if !errorlevel! equ 0 (
            echo     ✅ %%f is properly formatted
        ) else (
            echo     ❌ %%f is not properly formatted
            set "exit_code=1"
        )
        set /a "checked_count+=1"
    )
)

if %checked_count% equ 0 (
    echo ℹ️  No C files found to check
    exit /b 0
)

if %exit_code% equ 0 (
    echo ✅ All %checked_count% C files are properly formatted!
) else (
    echo ❌ Some C files need formatting. Run: uv run poe format-c
    exit /b 1
)