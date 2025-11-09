# Development Documentation

This folder contains documentation for developers and maintainers of py-asynkit.

## Contents

- **[PYPI_DEPLOYMENT.md](PYPI_DEPLOYMENT.md)**: PyPI deployment and GitHub releases setup, including:
  - GitHub Actions workflow configuration
  - PyPI Trusted Publishers setup
  - GitHub Releases automation
  - Release notes generation from CHANGES.md
- **[eager_tasks.md](eager_tasks.md)**: Comprehensive comparison between Python 3.12+ eager task factory and asynkit's eager execution, covering:
  - Timeline and history of eager execution development
  - Performance characteristics and implementation differences
  - Usage patterns and migration considerations
  - Context preservation and current task behavior
- **[eager_task_factory_performance.md](eager_task_factory_performance.md)**: Detailed performance analysis comparing implementations:
  - C extension vs pure Python performance metrics
  - Latency and throughput benchmarks across Python versions
  - Implementation recommendations and usage guidelines
- **[task_interruption.md](task_interruption.md)**: Task interruption capabilities (experimental feature):
  - Immediate exception injection into running tasks
  - Synchronous-style timeout handling
  - Python vs C task interruption limitations
  - Advanced usage patterns for task supervision
