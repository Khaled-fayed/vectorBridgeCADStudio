# Contributing to VectorBridge CAD Studio

Thanks for your interest in contributing. This document covers the basics for
contributing to VectorBridge.

## Getting started

1. Fork the repository and clone your fork.
2. Create a feature branch from `main`.
3. Install the application dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Install the test runner:

   ```powershell
   python -m pip install pytest
   ```

5. Run the existing test suite:

   ```powershell
   python -m unittest discover -s tests
   ```

## Workflow

- Keep changes focused on a single concern. Open one pull request per feature
  or bug fix.
- Write or update tests for any new behavior or bug fix.
- Update the README if your change affects how to build or run the project.
- Use the project's line length (100 characters) and import conventions.

## Linting

The repository uses [ruff](https://docs.astral.sh/ruff/) for linting.

Install it with:

```powershell
python -m pip install ruff
```

Run it with:

```powershell
ruff check .
```

## Pull requests

- Open a pull request against `main`.
- Ensure CI passes (lint and test).
- Provide a clear description of the problem and solution.
- Reference any related issues.

## Versioning and releases

- Tags are created as `v<major>.<minor>.<patch>`.
- The `release.yml` workflow builds the Windows executable and Inno Setup
  installer automatically when a tag matching `v*` is pushed.
