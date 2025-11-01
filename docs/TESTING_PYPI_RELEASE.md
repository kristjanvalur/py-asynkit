# Testing PyPI Release Process

This document describes how to test the PyPI release process using PyPI Test.

## Prerequisites

Before testing the release, ensure:

1. **GitHub Secrets**: The repository needs `TEST_PYPI_API_TOKEN` configured

   - Go to GitHub repository → Settings → Secrets and variables → Actions
   - Add `TEST_PYPI_API_TOKEN` with your PyPI Test API token
   - Get token from: https://test.pypi.org/account/

2. **Version**: Ensure the version in `pyproject.toml` is correct and hasn't been uploaded to PyPI Test before

## Testing Process

### 1. Manual Trigger

The test release workflow can be triggered manually:

1. Go to GitHub Actions in the repository
2. Select "Test Release to PyPI Test" workflow
3. Click "Run workflow"
4. Enter the version to test (e.g., `0.15.0`)
5. Click "Run workflow"

### 2. What the Test Does

The workflow will:

1. **Build all wheels** (Windows, macOS, Linux × Python 3.10-3.14)
2. **Build source distribution**
3. **Build pure Python wheel** (fallback)
4. **Test all artifacts** to ensure they import correctly
5. **Upload to PyPI Test** (https://test.pypi.org)
6. **Test installation** from PyPI Test to verify the upload worked

### 3. Expected Artifacts

The test should produce:

- **~15 binary wheels** (platform-specific with C extension)
- **1 pure Python wheel** (py3-none-any fallback)
- **1 source distribution** (.tar.gz)

### 4. Verification Steps

After the workflow completes successfully:

1. **Check PyPI Test**: Visit https://test.pypi.org/project/asynkit/
2. **Manual installation test**:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ asynkit==0.15.0
   python -c "import asynkit; print(asynkit.get_implementation_info())"
   ```

### 5. What to Look For

✅ **C Extension Availability**: Binary wheels should show "C extension" implementation\
✅ **Pure Python Fallback**: Pure Python wheel should show "Pure Python" implementation\
✅ **Performance Claims**: Check that performance info is accurate\
✅ **Import Success**: All wheels should import without errors\
✅ **Platform Coverage**: Wheels for all major platforms (Windows, macOS, Linux)

## Troubleshooting

### Common Issues

1. **Upload Conflicts**: If version already exists on PyPI Test, increment version
2. **C Extension Build Failures**: Check build logs, should gracefully fall back to Pure Python
3. **Import Errors**: Verify dependencies are correctly specified
4. **Missing Wheels**: Check cibuildwheel configuration and platform support

### Debug Steps

1. **Check workflow logs** for specific error messages
2. **Download artifacts** to inspect wheel contents locally
3. **Test locally** before uploading:
   ```bash
   # Build locally
   uv build

   # Test wheel
   pip install dist/*.whl
   python -c "import asynkit; print(asynkit.get_implementation_info())"
   ```

## Clean Up

After successful testing:

1. **Delete test releases** from PyPI Test (optional, they expire anyway)
2. **Document any issues** found during testing
3. **Update version** if needed for the real release
4. **Remove test workflow** if no longer needed

## Production Release

Once testing is successful, the production release process will be similar but:

- Uses `secrets.PYPI_API_TOKEN` (production PyPI)
- Uploads to https://pypi.org (not test.pypi.org)
- Usually triggered by git tags rather than manual dispatch
- Should be done from `master` branch after merging this feature branch
