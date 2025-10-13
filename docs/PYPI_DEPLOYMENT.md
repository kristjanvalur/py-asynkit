# PyPI Deployment Setup

This document explains how the PyPI deployment workflow is configured and how to set up the required GitHub environment.

## Overview

The project uses GitHub Actions to automatically build and publish to PyPI when a new version tag is pushed. The workflow leverages:

- **uv** for building Python packages
- **GitHub Environments** for deployment protection and approval
- **Trusted Publishers (OIDC)** for secure, passwordless authentication to PyPI

## Workflow Configuration

The deployment job in `.github/workflows/ci.yml` is configured as follows:

```yaml
build-n-publish:
  name: Build and publish Python distributions to PyPI
  runs-on: ubuntu-latest
  if: startsWith(github.ref, 'refs/tags/v')  # Only runs on version tags like v0.13.0
  needs:
    - tests
    - lint
  environment:
    name: pypi
    url: https://pypi.org/p/asynkit
  permissions:
    id-token: write  # Required for Trusted Publishers
  steps:
    - uses: actions/checkout@v3
    - name: Install uv
      uses: astral-sh/setup-uv@v4
      with:
        enable-cache: true
    - name: Set up Python 3.10
      run: uv python install 3.10
    - name: Build a binary wheel and a source tarball
      run: uv build
    - name: Publish distribution to PyPI
      uses: pypa/gh-action-pypi-publish@release/v1
```

## GitHub Environment Setup

To enable deployment, you need to create a GitHub Environment named `pypi`:

### Step 1: Create the Environment

1. Go to your repository on GitHub
1. Navigate to **Settings** → **Environments**
1. Click **New environment**
1. Name it `pypi` (must match the workflow configuration)
1. Click **Configure environment**

### Step 2: Configure Protection Rules (Optional but Recommended)

You can add protection rules to require manual approval before deployment:

1. **Required reviewers**: Add team members who must approve deployments
1. **Wait timer**: Add a delay before deployment proceeds
1. **Deployment branches**: Restrict to specific branches (tags are always allowed)

### Step 3: Set Up PyPI Trusted Publisher

Instead of using API tokens, configure PyPI to trust GitHub Actions via OIDC:

1. Go to [PyPI](https://pypi.org) and log in
1. Navigate to your project's settings (or create the project first)
1. Go to **Publishing** → **Add a new publisher**
1. Fill in the following details:
   - **PyPI Project Name**: `asynkit`
   - **Owner**: `kristjanvalur` (GitHub username or organization)
   - **Repository name**: `py-asynkit`
   - **Workflow name**: `ci.yml`
   - **Environment name**: `pypi`
1. Click **Add**

This allows GitHub Actions to publish without storing any secrets. The `id-token: write` permission in the workflow enables OIDC authentication.

## Publishing a New Version

To publish a new version to PyPI:

1. **Update the version** in `pyproject.toml`:

   ```toml
   [project]
   version = "0.13.1"  # Increment version
   ```

1. **Update the changelog** in `CHANGES.md`:

   ```markdown
   ## [0.13.1] - 2025-01-15

   ### Fixed
   - Bug fix description
   ```

1. **Commit the changes**:

   ```bash
   git add pyproject.toml CHANGES.md
   git commit -m "Bump version to 0.13.1"
   ```

1. **Create and push a version tag**:

   ```bash
   git tag v0.13.1
   git push origin master
   git push origin v0.13.1
   ```

1. The workflow will automatically:

   - Run all tests and linting
   - Build the package using `uv build`
   - Request approval if reviewers are configured
   - Publish to PyPI using Trusted Publishers

1. **Monitor the deployment**:

   - Go to **Actions** tab in GitHub
   - Find the workflow run for your tag
   - Check the **build-n-publish** job
   - If reviewers are configured, approve the deployment
   - Verify publication at https://pypi.org/p/asynkit

## Benefits of This Approach

### Security

- **No API tokens stored**: Trusted Publishers eliminate the need for `PYPI_API_TOKEN` secrets
- **Scoped permissions**: GitHub only gets permission to publish this specific package
- **Audit trail**: All deployments are logged in GitHub and PyPI

### Safety

- **Environment protection**: Optional approval workflow prevents accidental releases
- **Test gates**: Deployment only proceeds if all tests pass
- **Tag-based**: Only runs on explicit version tags, not every master commit

### Efficiency

- **Fast builds**: uv is 10-100x faster than pip/Poetry for dependency resolution
- **Simple workflow**: Single tool (`uv`) handles Python setup and building
- **Caching**: Dependencies are cached for faster subsequent runs

## Troubleshooting

### "Environment not found" error

Make sure you've created the `pypi` environment in repository settings.

### "Permission denied" when publishing

Verify that:

- The Trusted Publisher is configured correctly on PyPI
- The workflow has `permissions: id-token: write`
- The environment name matches (`pypi`)
- The repository and workflow names match exactly

### Version already exists on PyPI

You cannot republish the same version. Increment the version number in `pyproject.toml` and create a new tag.

### Tests fail before deployment

The `build-n-publish` job depends on `tests` and `lint` jobs passing. Fix any test failures before the deployment will proceed.

## Migration from Previous Setup

The previous workflow published to both Test PyPI (on every master commit) and PyPI (on tags). The new workflow:

- ✅ Only publishes to PyPI (production)
- ✅ Only runs on version tags (v\*)
- ✅ Uses Trusted Publishers (more secure than API tokens)
- ✅ Uses deployment environments (enables approval workflows)
- ✅ Uses uv consistently throughout (faster, simpler)

If you need Test PyPI for testing, you can manually test builds:

```bash
# Build locally
uv build

# Install from local build
pip install dist/asynkit-0.13.0-py3-none-any.whl

# Or upload to Test PyPI manually
uv run twine upload --repository testpypi dist/*
```

## References

- [GitHub Environments Documentation](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [PyPI Trusted Publishers Guide](https://docs.pypi.org/trusted-publishers/)
- [uv Documentation](https://docs.astral.sh/uv/)
- [GitHub Actions OIDC](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
