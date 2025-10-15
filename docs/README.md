# Development Documentation

This folder contains documentation for developers and maintainers of py-asynkit.

## Contents

### User Documentation Planning
- **[README_RESTRUCTURING_RECOMMENDATIONS.md](README_RESTRUCTURING_RECOMMENDATIONS.md)**: Comprehensive recommendations for improving README.md structure
  - Feature-first organization approach
  - Guidance on using backticks in headlines (with examples from popular libraries)
  - Emoji usage recommendations for Note sections
  - Implementation priorities
- **[README_PROPOSED_TOP_SECTION.md](README_PROPOSED_TOP_SECTION.md)**: Concrete examples of improved README top section
  - Detailed version with code examples
  - Concise version for quick scanning
  - Hybrid approach recommendation

### Technical Documentation
- **[MIGRATION_TO_UV.md](MIGRATION_TO_UV.md)**: Guide for the Poetry to uv migration, including:
  - Usage comparison between Poetry and uv
  - How to test with different Python versions
  - Build system changes
  - Ruff formatter migration
- **[PYPI_DEPLOYMENT.md](PYPI_DEPLOYMENT.md)**: PyPI deployment and GitHub releases setup, including:
  - GitHub Actions workflow configuration
  - PyPI Trusted Publishers setup
  - GitHub Releases automation
  - Release notes generation from CHANGES.md
