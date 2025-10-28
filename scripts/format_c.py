#!/usr/bin/env python3
"""
Cross-platform C code formatting using clang-format.
Gracefully handles missing clang-format installation.
"""

import os
import subprocess
import sys
from pathlib import Path


def find_clang_format():
    """Find clang-format executable."""
    try:
        result = subprocess.run(
            ["clang-format", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def find_c_files(root_dir):
    """Find all C source files in the _cext directory."""
    cext_dir = root_dir / "src" / "asynkit" / "_cext"
    if not cext_dir.exists():
        return []

    c_files = []
    for pattern in ["*.c", "*.h"]:
        c_files.extend(cext_dir.glob(pattern))
    return c_files


def format_c_files():
    """Format all C files using clang-format."""
    root_dir = Path(__file__).parent.parent

    if not find_clang_format():
        print("⚠️  clang-format not found - skipping C code formatting")
        print("   Install clang-format for C code formatting support")
        return 0

    c_files = find_c_files(root_dir)
    if not c_files:
        print("ℹ️  No C files found to format")
        return 0

    print("✅ Formatting C code with clang-format...")

    for c_file in c_files:
        print(f"  📝 Formatting: {c_file.relative_to(root_dir)}")
        subprocess.run(["clang-format", "-i", str(c_file)], check=True)

    print(f"✅ Formatted {len(c_files)} C files!")
    return 0


def check_c_style():
    """Check C code formatting with clang-format."""
    root_dir = Path(__file__).parent.parent

    if not find_clang_format():
        print("⚠️  clang-format not found - skipping C code style check")
        print("   Install clang-format for C code style validation")
        return 0

    c_files = find_c_files(root_dir)
    if not c_files:
        print("ℹ️  No C files found to check")
        return 0

    print("✅ Checking C code formatting...")

    exit_code = 0
    for c_file in c_files:
        print(f"  🔍 Checking: {c_file.relative_to(root_dir)}")
        try:
            subprocess.run(
                ["clang-format", "--dry-run", "--Werror", str(c_file)],
                capture_output=True,
                check=True,
            )
            print(f"    ✅ {c_file.name} is properly formatted")
        except subprocess.CalledProcessError as e:
            print(f"    ❌ {c_file.name} is not properly formatted")
            if e.stderr:
                # Show first few lines of error
                error_lines = e.stderr.decode().split("\n")[:3]
                for line in error_lines:
                    if line.strip():
                        print(f"      {line}")
            exit_code = 1

    if exit_code == 0:
        print(f"✅ All {len(c_files)} C files are properly formatted!")
    else:
        print("❌ Some C files need formatting. Run: uv run poe format-c")

    return exit_code


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python format_c.py [format|check]")
        return 1

    command = sys.argv[1]

    if command == "format":
        return format_c_files()
    elif command == "check":
        return check_c_style()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python format_c.py [format|check]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
