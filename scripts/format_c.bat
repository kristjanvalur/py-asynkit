@echo off
REM Format all C files in the asynkit C extension
REM Optional - skips gracefully if clang-format is not available

cd /d "%~dp0\.."

REM Check if clang-format is available
where clang-format >nul 2>&1
if %errorlevel% neq 0 (
    echo ^⚠️  clang-format not found - skipping C code formatting
    echo    Install clang-format for C code formatting support
    exit /b 0
)

echo ✅ Formatting C code with clang-format...

REM Format all C files in _cext directory
for /r "src\asynkit\_cext" %%f in (*.c *.h) do (
    if exist "%%f" (
        echo   📝 Formatting: %%f
        clang-format -i "%%f"
    )
)

echo ✅ C code formatting complete!