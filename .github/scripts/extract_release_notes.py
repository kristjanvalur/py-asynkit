#!/usr/bin/env python3
"""
Extract release notes for a specific version from CHANGES.md.

This script extracts the changelog section for a given version tag
to use as GitHub release notes.
"""

import re
import sys
from pathlib import Path


def extract_release_notes(changelog_path: Path, version: str) -> str:
    """
    Extract release notes for a specific version from CHANGES.md.

    Args:
        changelog_path: Path to CHANGES.md
        version: Version string (e.g., "0.13.0")

    Returns:
        Release notes text for the version
    """
    content = changelog_path.read_text()

    # Match version header like "## [0.13.0] - 2025"
    version_pattern = rf"^## \[{re.escape(version)}\]"

    lines = content.split("\n")
    start_idx = None
    end_idx = None

    # Find start of this version's section
    for i, line in enumerate(lines):
        if re.match(version_pattern, line):
            start_idx = i
            break

    if start_idx is None:
        return f"Release {version}\n\nNo changelog entry found for this version."

    # Find start of next version section (or end of file)
    for i in range(start_idx + 1, len(lines)):
        # Next version header starts with "## ["
        if re.match(r"^## \[", lines[i]):
            end_idx = i
            break

    if end_idx is None:
        end_idx = len(lines)

    # Extract the section (skip the version header itself)
    section_lines = lines[start_idx + 1 : end_idx]

    # Remove leading/trailing empty lines
    while section_lines and not section_lines[0].strip():
        section_lines.pop(0)
    while section_lines and not section_lines[-1].strip():
        section_lines.pop()

    if not section_lines:
        return f"Release {version}\n\nNo detailed changes documented."

    return "\n".join(section_lines)


def main():
    if len(sys.argv) != 2:
        print("Usage: extract_release_notes.py VERSION", file=sys.stderr)
        print("Example: extract_release_notes.py 0.13.0", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1]
    # Remove 'v' prefix if present
    if version.startswith("v"):
        version = version[1:]

    repo_root = Path(__file__).parent.parent.parent
    changelog_path = repo_root / "CHANGES.md"

    if not changelog_path.exists():
        print(f"Error: {changelog_path} not found", file=sys.stderr)
        sys.exit(1)

    notes = extract_release_notes(changelog_path, version)
    print(notes)


if __name__ == "__main__":
    main()
